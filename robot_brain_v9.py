import requests
import time
import subprocess
import os
import re
import threading
import json
from http.server import HTTPServer, BaseHTTPRequestHandler

# ================================================
#   PHONEBOT BRAIN v9 — Button Fixed
#   Groq Whisper STT + local fallback
#   Groq/Laptop AI + noise filtered audio
# ================================================
#   ── EDIT ONLY THIS SECTION ──────────────────

# ── Network ────────────────────────────────────
ESP32_IP      = "***"    # ← ESP32 IP
LAPTOP_IP     = "***"     # ← Laptop IP

# ── AI + STT Keys ──────────────────────────────
GROQ_KEY      = "gsk_your_key"     # ← Groq API key (used for AI + Whisper!)
GROQ_MODEL    = "llama-3.1-8b-instant"
LAPTOP_MODEL  = "llama3.1:latest"

# ── Behaviour ──────────────────────────────────
SAFE_DIST     = 40     # cm
IDLE_TIMEOUT  = 60     # seconds
LISTEN_SEC    = 5      # voice recording seconds
NAV_INTERVAL  = 1.5    # seconds between nav decisions

# ── Whisper ────────────────────────────────────
WHISPER_BIN   = "/data/data/com.termux/files/home/whisper.cpp/build/bin/whisper-cli"
WHISPER_MDL   = "/data/data/com.termux/files/home/whisper.cpp/models/ggml-base.en.bin"

# ── Files ──────────────────────────────────────
AUDIO_RAW     = "/sdcard/robot_voice.wav"
AUDIO_FIXED   = "/sdcard/robot_voice_fixed.wav"

# ── END CONFIG ─────────────────────────────────

OLLAMA_LAPTOP = f"http://{LAPTOP_IP}:11434/api/generate"
HTTP_TIMEOUT  = 0.8

PERSONALITY = """You are companion robot, a playful home robot.
Short replies only — max 1 sentence.
Use Ooh!, Yay!, Beep boop! sometimes.
End with one movement: [forward] [backward] [left] [right] [stop]"""

MOOD_VOICES = {
    "happy":     ["-r","1.1","-p","2.0"],
    "curious":   ["-r","0.95","-p","1.5"],
    "angry":     ["-r","1.1","-p","0.8"],
    "listening": ["-r","0.85","-p","1.8"],
    "sleeping":  ["-r","0.75","-p","1.0"],
}

# ================================================
#   STATE
# ================================================
class S:
    esp32      = False
    laptop_ai  = False
    internet   = False
    sleeping   = False
    vision     = False
    mood       = "happy"
    ai_src     = "none"
    stt_src    = "none"
    step       = 0
    pan        = 90
    last_act   = time.time()

s = S()
voice_active = False  # prevents re-entry during recording

live = {
    "mood":"happy","esp32":False,"laptop":False,
    "net":False,"ai":"none","stt":"none","step":0,
    "cmd":"stop","said":"","heard":"","status":"starting"
}

# ================================================
#   ESP32 — fast HTTP
# ================================================
session = requests.Session()

def bot(path):
    try:
        session.get(f"http://{ESP32_IP}/{path}", timeout=HTTP_TIMEOUT)
        s.esp32 = True
    except:
        s.esp32 = False

def get_sensors():
    try:
        r = session.get(f"http://{ESP32_IP}/sensors", timeout=HTTP_TIMEOUT)
        d = r.json()
        return d["left"], d["right"]
    except:
        return 999, 999

def set_mood(mood):
    s.mood = mood
    m = {"happy":0,"curious":1,"angry":2,"listening":3,"sleeping":4}.get(mood,0)
    bot(f"mood?m={m}")

def pan(angle):
    s.pan = angle
    bot(f"pan?angle={angle}")

def ant(action):
    bot(f"antenna?{action}")

# ================================================
#   BUTTON WATCHER THREAD  ← the fix
#   Polls every 150ms independently of nav loop.
#   Sets an Event flag — never misses a press.
# ================================================
button_triggered = threading.Event()

def button_watcher():
    while True:
        try:
            r = session.get(f"http://{ESP32_IP}/button", timeout=0.3)
            if r.json().get("pressed"):
                print("🔘 Button pressed!")
                button_triggered.set()
        except:
            pass
        time.sleep(0.15)

# ================================================
#   ANIMATIONS
# ================================================
def wake_up():
    speak("Beep boop, I am awake!", "curious")
    set_mood("sleeping"); time.sleep(0.3)
    set_mood("curious");  time.sleep(0.2)
    pan(55); time.sleep(0.25)
    pan(125); time.sleep(0.25)
    pan(90)
    set_mood("happy")
    bot("lookaround")
    s.sleeping = False
    s.last_act = time.time()

def sleep_now():
    speak("Getting sleepy. Goodnight!", "sleeping")
    set_mood("sleeping")
    pan(90); bot("stop")
    s.sleeping = True

# ================================================
#   STATUS + VISION SERVERS
# ================================================
def upd(extra={}):
    live.update(extra)
    live.update({
        "mood":s.mood,"esp32":s.esp32,"laptop":s.laptop_ai,
        "net":s.internet,"ai":s.ai_src,"stt":s.stt_src,
        "step":s.step,"pan":s.pan
    })

class StatusH(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type","application/json")
        self.send_header("Access-Control-Allow-Origin","*")
        self.end_headers()
        self.wfile.write(json.dumps(live).encode())
    def log_message(self,*a): pass

class VisionH(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            data = json.loads(self.rfile.read(
                int(self.headers.get("Content-Length",0))))
            if not s.vision:
                threading.Thread(
                    target=on_vision,args=(data,),daemon=True).start()
        except: pass
        self.send_response(200); self.end_headers()
    def log_message(self,*a): pass

def on_vision(data):
    s.vision = True
    try:
        moods  = ["happy","curious","angry","listening","sleeping"]
        mood   = moods[data.get("mood",0)]
        msg    = data.get("msg","")
        cmd    = data.get("cmd","stop")
        label  = data.get("label","")
        print(f"👁️  {label}: {msg}")
        if s.sleeping: wake_up()
        set_mood(mood)
        speak(msg, mood)
        if cmd != "stop": bot(cmd); time.sleep(0.8); bot("stop")
        upd({"status":f"saw {label}"})
        s.last_act = time.time()
    finally:
        s.vision = False

# ================================================
#   AI — Laptop → Groq → offline fallback
# ================================================
def ask_laptop(prompt):
    try:
        r = requests.post(OLLAMA_LAPTOP,
            json={"model":LAPTOP_MODEL,"prompt":prompt,"stream":False},
            timeout=10)
        s.laptop_ai = True
        return r.json()["response"].strip()
    except:
        s.laptop_ai = False
        return None

def ask_groq(prompt):
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization":f"Bearer {GROQ_KEY}",
                     "Content-Type":"application/json"},
            json={"model":GROQ_MODEL,
                  "messages":[{"role":"user","content":prompt}],
                  "max_tokens":60,"temperature":0.7},
            timeout=8)
        return r.json()["choices"][0]["message"]["content"].strip()
    except:
        return None

def ask(prompt):
    if s.laptop_ai:
        print("🖥️ ",end="",flush=True)
        r = ask_laptop(prompt)
        if r: s.ai_src="laptop"; print("✓"); return r
    if s.internet:
        print("🌐 ",end="",flush=True)
        r = ask_groq(prompt)
        if r: s.ai_src="groq"; print("✓"); return r
    s.ai_src="none"
    return "Beep boop, brain offline! [stop]"

def get_cmd(text):
    for c in ["forward","backward","left","right","stop"]:
        if f"[{c}]" in text.lower(): return c
    return "stop"

# ================================================
#   TTS
# ================================================
def speak(text, mood=None):
    clean = re.sub(r'\[.*?\]','',text).strip()
    if not clean: return
    args = MOOD_VOICES.get(mood or s.mood, ["-r","1.0","-p","1.5"])
    ant("talk=1")
    subprocess.Popen(["termux-tts-speak"] + args + [clean])
    time.sleep(max(1.5, len(clean.split())*0.38))
    ant("talk=0")

# ================================================
#   AUDIO RECORDING + PROCESSING
# ================================================
def record():
    for f in [AUDIO_RAW, AUDIO_FIXED]:
        if os.path.exists(f): os.remove(f)

    # Mute volume during beep to avoid echo
    subprocess.Popen(["termux-volume","music","0"])
    time.sleep(0.1)
    set_mood("listening")

    # Three beep countdown so user knows when to speak
    subprocess.Popen(["termux-tts-speak","-r","2.0","-p","3.0","beep beep beep"])
    time.sleep(2.5)

    # Restore volume
    subprocess.Popen(["termux-volume","music","15"])

    print(f"🎤 Recording {LISTEN_SEC}s — speak now!")
    try:
        subprocess.Popen(
            ["termux-microphone-record","-l",str(LISTEN_SEC),"-f",AUDIO_RAW])
        time.sleep(LISTEN_SEC + 1.5)
        subprocess.run(["termux-microphone-record","-q"],timeout=3)
        time.sleep(0.8)
        size = os.path.getsize(AUDIO_RAW) if os.path.exists(AUDIO_RAW) else 0
        print(f"  Recorded: {size} bytes")
        return size > 1000
    except Exception as e:
        print(f"Record error: {e}"); return False

def convert():
    try:
        subprocess.run(
            ["ffmpeg","-i",AUDIO_RAW,
             "-af",
             "afftdn=nf=-25,"
             "volume=3.0,"
             "highpass=f=150,"
             "lowpass=f=3500,"
             "anlmdn",
             "-ar","16000",
             "-ac","1",
             "-c:a","pcm_s16le",
             AUDIO_FIXED,"-y"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15)
        ok = os.path.exists(AUDIO_FIXED) and os.path.getsize(AUDIO_FIXED)>0
        print(f"  Converted: {'✓' if ok else '✗'}")
        return ok
    except Exception as e:
        print(f"ffmpeg error: {e}"); return False

# ================================================
#   TRANSCRIPTION — Groq Cloud → Local fallback
# ================================================
def transcribe_groq():
    try:
        print("🎙️  Groq Whisper...", end=" ", flush=True)
        with open(AUDIO_FIXED, 'rb') as f:
            r = requests.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {GROQ_KEY}"},
                files={"file": ("audio.wav", f, "audio/wav")},
                data={
                    "model":    "whisper-large-v3-turbo",
                    "language": "en",
                    "prompt":   "Robot voice command. Short sentence.",
                },
                timeout=15
            )
        if r.status_code == 200:
            text = r.json().get("text","").strip()
            text = re.sub(r'\[.*?\]','',text).strip()
            print("✓")
            s.stt_src = "groq"
            return text
        else:
            print(f"✗ ({r.status_code})")
            return None
    except Exception as e:
        print(f"✗ ({e})")
        return None

def transcribe_local():
    try:
        print("📱 Local Whisper...", end=" ", flush=True)
        result = subprocess.run(
            [WHISPER_BIN,"-m",WHISPER_MDL,"-f",AUDIO_FIXED,
             "-nt","--no-prints",
             "-l","en",
             "--prompt","PhoneBot robot command:"],
            capture_output=True, text=True, timeout=30)
        text = re.sub(r'\[.*?\]','',result.stdout).strip()
        print("✓")
        s.stt_src = "local"
        return text
    except Exception as e:
        print(f"✗ ({e})")
        s.stt_src = "none"
        return ""

def transcribe():
    if s.internet:
        text = transcribe_groq()
        if text:
            print(f"  Heard: '{text}'")
            return text
        print("  Groq failed, trying local...")
    text = transcribe_local()
    if text:
        print(f"  Heard: '{text}'")
    return text or ""

# ================================================
#   VOICE INTERACTION
# ================================================
def voice_mode():
    global voice_active
    if voice_active: return          # block re-entry during recording
    voice_active = True
    button_triggered.clear()         # discard presses queued during nav sleep
    print("\n"+"="*40+"  🎤 VOICE")
    try:
        if s.sleeping: wake_up()
        s.last_act = time.time()
        bot("stop")
        upd({"status":"listening"})

        if not record():
            speak("Mic failed!", "curious"); return
        if not convert():
            speak("Audio error!", "curious"); return

        heard = transcribe()
        if not heard:
            speak("Didn't catch that!", "curious"); return

        low = heard.lower()

        # Special commands
        if any(w in low for w in ["sleep","goodnight"]):
            sleep_now(); return
        if any(w in low for w in ["wake up","hello","hi"]):
            wake_up(); return
        if any(w in low for w in ["status","how are you"]):
            speak(f"Using {s.ai_src} AI and {s.stt_src} speech recognition.",
                  "curious"); return
        if any(w in low for w in ["look around","what do you see","scan"]):
            speak("Let me look around!", "curious")
            bot("lookaround"); return

        # AI response
        left, right = get_sensors()
        set_mood("curious")
        response = ask(f"""{PERSONALITY}
User: "{heard}"
Sensors: L={left}cm R={right}cm
PhoneBot:""")

        cmd  = get_cmd(response)
        mood = "angry"   if left<SAFE_DIST or right<SAFE_DIST else \
               "happy"   if cmd in ["forward","backward"] else "curious"

        speak(response, mood)
        set_mood(mood)
        pan(90); bot(cmd)
        upd({
            "cmd":cmd,
            "heard":heard,
            "said":re.sub(r'\[.*?\]','',response).strip(),
            "status":"voice"
        })
        print("="*40)

    finally:
        voice_active = False
        button_triggered.clear()     # discard any presses that built up during recording

# ================================================
#   BACKGROUND MONITOR
# ================================================
def monitor():
    while True:
        try:
            session.get(f"http://{ESP32_IP}/",timeout=1.5)
            s.esp32 = True
        except: s.esp32 = False
        try:
            requests.get("https://www.google.com",timeout=3)
            s.internet = True
        except: s.internet = False
        try:
            requests.get(f"http://{LAPTOP_IP}:11434/api/tags",timeout=2)
            s.laptop_ai = True
        except: s.laptop_ai = False
        print(f"📡 ESP32:{'✓' if s.esp32 else '✗'} "
              f"Laptop:{'✓' if s.laptop_ai else '✗'} "
              f"Net:{'✓' if s.internet else '✗'} "
              f"AI:{s.ai_src} STT:{s.stt_src}")
        time.sleep(15)

# ================================================
#   STARTUP
# ================================================
print("\n"+"="*40)
print("  PHONEBOT v9 — Button Fixed")
print("="*40)
print(f"ESP32:  {ESP32_IP}")
print(f"Laptop: {LAPTOP_IP}")

# Max volume
subprocess.Popen(["termux-volume","music","15"])
subprocess.Popen(["termux-volume","call","15"])
subprocess.Popen(["termux-volume","alarm","15"])

# TTS warmup
subprocess.Popen(["termux-tts-speak","-r","1.0","-p","1.5","starting"])
time.sleep(2.5)

# Check connections
try:
    session.get(f"http://{ESP32_IP}/",timeout=3)
    s.esp32 = True; print(f"✓ ESP32")
except: print(f"✗ ESP32 not found")

try:
    requests.get(f"http://{LAPTOP_IP}:11434/api/tags",timeout=3)
    s.laptop_ai = True; print(f"✓ Laptop AI")
except: print(f"✗ Laptop AI")

try:
    requests.get("https://www.google.com",timeout=3)
    s.internet = True; print("✓ Internet → Groq AI + Groq Whisper")
except: print("✗ No internet → local STT + no Groq AI")

print(f"\nAI:  {'Laptop' if s.laptop_ai else ''}{'+ Groq' if s.internet else ''}")
print(f"STT: {'Groq Whisper (cloud)' if s.internet else 'Local whisper.cpp'}")
print("="*40)

# Start servers + threads
threading.Thread(
    target=lambda:HTTPServer(("0.0.0.0",8765),StatusH).serve_forever(),
    daemon=True).start()
threading.Thread(
    target=lambda:HTTPServer(("0.0.0.0",8766),VisionH).serve_forever(),
    daemon=True).start()
threading.Thread(target=monitor, daemon=True).start()
threading.Thread(target=button_watcher, daemon=True).start()
print("✓ Status :8765  Vision :8766  Button watcher: ON")

if s.esp32:
    set_mood("sleeping"); time.sleep(0.3)
    set_mood("curious");  time.sleep(0.2)
    set_mood("happy")
    bot("lookaround")
    speak("Yay I am alive! Ready to listen!", "happy")
    ant("wiggle=5")
else:
    speak("Cannot find my body!", "curious")

print("\n🤖 PhoneBot v9 running!\n")

# ================================================
#   MAIN LOOP
# ================================================
step = 0
while True:
    step += 1
    s.step = step
    upd()

    if not s.esp32:
        print("⏳ Waiting for ESP32...")
        time.sleep(2); continue

    # Button check — instant, uses event flag set by watcher thread
    if button_triggered.is_set():
        button_triggered.clear()
        if s.sleeping: wake_up()
        else: voice_mode()
        s.last_act = time.time()
        time.sleep(0.8)
        continue

    if time.time()-s.last_act > IDLE_TIMEOUT and not s.sleeping:
        sleep_now(); continue

    if s.sleeping:
        time.sleep(2); continue

    if s.vision:
        time.sleep(0.3); continue

    # Navigate
    print(f"[{step}]", end=" ")
    left, right = get_sensors()
    print(f"L:{left}cm R:{right}cm", end=" → ")

    if left < SAFE_DIST and right < SAFE_DIST:
        cmd = "backward"; set_mood("angry");   pan(90)
    elif left < SAFE_DIST:
        cmd = "right";    set_mood("angry");   pan(120)
    elif right < SAFE_DIST:
        cmd = "left";     set_mood("angry");   pan(60)
    elif left < SAFE_DIST*2:
        cmd = "forward";  set_mood("curious"); pan(120)
    elif right < SAFE_DIST*2:
        cmd = "forward";  set_mood("curious"); pan(60)
    else:
        cmd = "forward";  set_mood("happy");   pan(90)
        s.last_act = time.time()

    print(cmd)
    bot(cmd)
    upd({"cmd":cmd,"status":"navigating"})
    time.sleep(NAV_INTERVAL)
