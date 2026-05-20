import pygame
import requests
import time
import threading
import queue
import cv2
import numpy as np
import random

# ================================================
#   PHONEBOT GAMEPAD + VISION — Laptop Controller
#   YOLOv8 human detection via IP Webcam stream
#   Reacts to people: speech + mood + movement
# ================================================

ESP32_IP   = "10.217.99.125"   # ← ESP32 IP  (update each session)
PHONE_IP   = "192.168.10.105"   # ← Phone IP  (update each session)
BRAIN_IP   = PHONE_IP           # phone brain lives on same IP

# IP Webcam stream URL (default port 8080)
CAM_URL    = f"http://{PHONE_IP}:8080/video"

DEADZONE   = 0.15
SPEED_MS   = [250, 450, 700]
speed_idx  = 1
last_cmd   = ""
last_pan   = 90

# ================================================
#   VISION CONFIG
# ================================================
VISION_ENABLED      = True      # toggle with Y button
PERSON_COOLDOWN     = 6.0       # seconds between reactions to same person
CONFIDENCE_THRESH   = 0.50      # minimum YOLO confidence
FRAME_SKIP          = 2         # process every Nth frame (saves CPU)

# Person position zones (fraction of frame width)
# LEFT zone: person is to the left → bot turns left
# RIGHT zone: person is to the right → bot turns right
# CENTER zone: person is centered → bot moves forward
LEFT_ZONE  = 0.35
RIGHT_ZONE = 0.65

# Reaction messages — randomly picked
PERSON_GREETINGS = [
    "Oh hello there! I see you!",
    "Yay, a human! My favorite!",
    "Beep boop! I found a person!",
    "Hi there! Want to be friends?",
    "Ooh, I see you! Come closer!",
]

# ================================================
#   FAST COMMAND QUEUE
# ================================================
session = requests.Session()
cmd_q   = queue.Queue(maxsize=5)

def sender():
    prev = ""
    while True:
        try:
            cmd = cmd_q.get(timeout=0.05)
            if cmd != prev:
                try:
                    session.get(f"http://{ESP32_IP}/{cmd}", timeout=0.3)
                    prev = cmd
                except:
                    pass
        except queue.Empty:
            pass

threading.Thread(target=sender, daemon=True).start()

def bot(path):
    try:
        if cmd_q.full():
            cmd_q.get_nowait()
        cmd_q.put_nowait(path)
    except:
        pass

def bot_now(path):
    try:
        session.get(f"http://{ESP32_IP}/{path}", timeout=0.5)
    except:
        pass

def send_move(cmd):
    global last_cmd
    if cmd != last_cmd:
        bot(cmd)
        last_cmd = cmd
        if cmd != "stop":
            print(f"→ {cmd}")

def send_pan(angle):
    global last_pan
    angle = max(30, min(150, int(angle)))
    if abs(angle - last_pan) > 4:
        bot(f"pan?angle={angle}")
        last_pan = angle

def set_mood(m):
    bot_now(f"mood?m={m}")

def wiggle(n=3):
    bot_now(f"antenna?wiggle={n}")

def notify_brain(msg_dict):
    """Send vision event to phone brain (port 8766)"""
    try:
        requests.post(
            f"http://{BRAIN_IP}:8766",
            json=msg_dict,
            timeout=1.0
        )
    except:
        pass

# ================================================
#   YOLO SETUP
# ================================================
try:
    from ultralytics import YOLO
    yolo = YOLO("yolov8n.pt")   # auto-downloads if missing
    # Warm up model
    dummy = np.zeros((480, 640, 3), dtype=np.uint8)
    yolo(dummy, verbose=False)
    print("✓ YOLOv8 ready")
    YOLO_OK = True
except Exception as e:
    print(f"✗ YOLO failed: {e}")
    print("  pip install ultralytics")
    YOLO_OK = False

# ================================================
#   VISION THREAD
# ================================================
vision_active    = False   # True while reacting to a person
last_person_time = 0
frame_count      = 0
vision_status    = "off"   # for display

def get_person_zone(box, frame_w):
    """Return 'left', 'center', or 'right' based on box center X"""
    cx = (box[0] + box[2]) / 2.0 / frame_w
    if cx < LEFT_ZONE:
        return "left"
    elif cx > RIGHT_ZONE:
        return "right"
    else:
        return "center"

def get_pan_for_zone(zone):
    """Pan angle to look toward person"""
    return {"left": 55, "center": 90, "right": 125}.get(zone, 90)

def get_turn_for_zone(zone):
    """Movement command to approach person"""
    return {"left": "left", "center": "forward", "right": "right"}.get(zone, "stop")

def react_to_person(zone, confidence):
    """Called in its own thread — reacts to detected human"""
    global vision_active, last_person_time
    vision_active = True
    try:
        pan_angle = get_pan_for_zone(zone)
        turn_cmd  = get_turn_for_zone(zone)
        greeting  = random.choice(PERSON_GREETINGS)

        print(f"\n👤 PERSON DETECTED! zone={zone} conf={confidence:.0%}")
        print(f"   → pan:{pan_angle}° move:{turn_cmd} say:'{greeting}'")

        # 1. Look toward person + excited mood
        bot_now(f"pan?angle={pan_angle}")
        bot_now("mood?m=3")          # listening/excited (pink eyes)
        bot_now("antenna?wiggle=4")

        # 2. Notify phone brain (plays TTS + updates display)
        notify_brain({
            "mood":  3,
            "msg":   greeting,
            "cmd":   turn_cmd,
            "label": "person",
        })

        # 3. Move toward person for 0.8s
        time.sleep(0.3)              # let pan settle
        bot_now(turn_cmd)
        time.sleep(0.8)
        bot_now("stop")

        # 4. Back to happy
        time.sleep(0.5)
        bot_now("mood?m=0")
        bot_now("centerhead")

        last_person_time = time.time()

    finally:
        vision_active = False

def vision_loop():
    global frame_count, vision_status, VISION_ENABLED

    if not YOLO_OK:
        print("✗ Vision disabled — YOLO not loaded")
        return

    print(f"📷 Connecting to camera: {CAM_URL}")
    cap = None

    while True:
        if not VISION_ENABLED:
            vision_status = "off"
            if cap:
                cap.release()
                cap = None
            time.sleep(1)
            continue

        # Connect/reconnect camera
        if cap is None or not cap.isOpened():
            vision_status = "connecting..."
            print(f"📷 Opening stream: {CAM_URL}")
            cap = cv2.VideoCapture(CAM_URL)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # minimal latency
            if not cap.isOpened():
                vision_status = "no camera"
                print("✗ Cannot open camera stream")
                print(f"  Make sure IP Webcam is running on phone")
                print(f"  URL: {CAM_URL}")
                time.sleep(3)
                continue
            vision_status = "active"
            print("✓ Camera stream connected")

        ret, frame = cap.read()
        if not ret:
            vision_status = "reconnecting..."
            cap.release()
            cap = None
            time.sleep(1)
            continue

        frame_count += 1

        # Skip frames to save CPU
        if frame_count % FRAME_SKIP != 0:
            continue

        # Don't process if already reacting
        if vision_active:
            continue

        # Cooldown between reactions
        if time.time() - last_person_time < PERSON_COOLDOWN:
            continue

        frame_h, frame_w = frame.shape[:2]

        # Run YOLO (GPU accelerated on RTX 3050)
        results = yolo(frame, verbose=False, classes=[0])  # class 0 = person only

        best_box  = None
        best_conf = 0

        for r in results:
            for box in r.boxes:
                conf = float(box.conf[0])
                if conf > CONFIDENCE_THRESH and conf > best_conf:
                    best_conf = conf
                    best_box  = box.xyxy[0].tolist()

        if best_box:
            zone = get_person_zone(best_box, frame_w)
            threading.Thread(
                target=react_to_person,
                args=(zone, best_conf),
                daemon=True
            ).start()

    if cap:
        cap.release()

# ================================================
#   GAMEPAD SETUP
# ================================================
pygame.init()
pygame.joystick.init()

if pygame.joystick.get_count() == 0:
    print("✗ No controller found!")
    exit()

js = pygame.joystick.Joystick(0)
js.init()

print("\n" + "="*50)
print("  PHONEBOT GAMEPAD + VISION")
print("="*50)
print(f"Controller : {js.get_name()}")
print(f"ESP32      : {ESP32_IP}")
print(f"Phone      : {PHONE_IP}")
print(f"Camera     : {CAM_URL}")
print()
print("  Left stick    → Move")
print("  Right stick X → Pan head  (axis 3 XInput)")
print("  A (0)         → Voice mode")
print("  B (1)         → Look around")
print("  X (2)         → Happy mood")
print("  Y (3)         → Toggle vision ON/OFF")
print("  LB (4)        → Speed down")
print("  RB (5)        → Speed up")
print("  SELECT (6)    → Sleep")
print("  START  (7)    → Wake up")
print("  D-pad         → Precise move")
print("  Ctrl+C        → Quit")
print("="*50)

# Test ESP32
try:
    r = session.get(f"http://{ESP32_IP}/", timeout=2)
    print(f"\n✓ ESP32: {r.text.strip()}")
    set_mood(0)
    bot_now("lookaround")
    wiggle(4)
    print("🎮 Ready!\n")
except:
    print(f"\n✗ ESP32 not reachable at {ESP32_IP}")
    print("  Check IP and WiFi!\n")

# Start vision thread
if YOLO_OK:
    threading.Thread(target=vision_loop, daemon=True).start()
    print("✓ Vision thread started")

btn_prev = [False] * js.get_numbuttons()
clock    = pygame.time.Clock()

# ================================================
#   MAIN LOOP — 20Hz
# ================================================
try:
    while True:
        pygame.event.pump()

        def ax(n):
            v = js.get_axis(n) if n < js.get_numaxes() else 0
            return v if abs(v) > DEADZONE else 0

        lx = ax(0)
        ly = ax(1)
        rx = ax(3)   # XInput right stick X = axis 3

        # ── Movement ──────────────────────────
        # Don't override movement if vision is reacting
        if not vision_active:
            if abs(ly) > DEADZONE or abs(lx) > DEADZONE:
                if abs(ly) >= abs(lx):
                    send_move("forward" if ly < 0 else "backward")
                else:
                    send_move("left" if lx < 0 else "right")
            else:
                send_move("stop")

        # ── Pan head ──────────────────────────
        if abs(rx) > DEADZONE and not vision_active:
            send_pan(last_pan + rx * 3)

        # ── D-pad ─────────────────────────────
        if js.get_numhats() > 0:
            hx, hy = js.get_hat(0)
            ms = SPEED_MS[speed_idx]
            if hy == 1:
                bot_now("forward");  time.sleep(ms/1000); bot_now("stop"); last_cmd=""
            elif hy == -1:
                bot_now("backward"); time.sleep(ms/1000); bot_now("stop"); last_cmd=""
            elif hx == -1:
                bot_now("left");     time.sleep(ms/1000*0.7); bot_now("stop"); last_cmd=""
            elif hx == 1:
                bot_now("right");    time.sleep(ms/1000*0.7); bot_now("stop"); last_cmd=""

        # ── Buttons ───────────────────────────
        for i in range(js.get_numbuttons()):
            pressed = js.get_button(i)
            if pressed and not btn_prev[i]:

                if i == 0:    # A — voice
                    print("🎤 Voice!")
                    set_mood(3); wiggle(2)

                elif i == 1:  # B — look around
                    print("👀 Look around!")
                    bot_now("lookaround"); wiggle(4)

                elif i == 2:  # X — happy
                    print("😊 Happy!")
                    set_mood(0); wiggle(3)

                elif i == 3:  # Y — toggle vision
                    VISION_ENABLED = not VISION_ENABLED
                    state = "ON 👁️" if VISION_ENABLED else "OFF 🙈"
                    print(f"📷 Vision {state}")
                    wiggle(2)
                    set_mood(1 if VISION_ENABLED else 0)

                elif i == 4:  # LB — slower
                    speed_idx = max(0, speed_idx-1)
                    print(f"🐢 Speed {speed_idx+1}/3")

                elif i == 5:  # RB — faster
                    speed_idx = min(2, speed_idx+1)
                    print(f"🐇 Speed {speed_idx+1}/3")

                elif i == 6:  # SELECT — sleep
                    print("😴 Sleep!")
                    VISION_ENABLED = False
                    set_mood(4)
                    bot_now("stop")
                    bot_now("centerhead")
                    send_move("stop")

                elif i == 7:  # START — wake
                    print("⏰ Wake up!")
                    VISION_ENABLED = True
                    set_mood(0)
                    bot_now("lookaround")
                    wiggle(5)

                elif i in [8, 9, 10]:
                    print("🎯 Center!")
                    send_pan(90)
                    bot_now("centerhead")

                else:
                    print(f"Btn {i}")

            btn_prev[i] = pressed

        # ── Status line every 5s ───────────────
        if int(time.time()) % 5 == 0 and frame_count % 100 == 0:
            v_str = f"vision={vision_status} frames={frame_count}"
            print(f"📊 {v_str}  pan={last_pan}°  speed={speed_idx+1}/3")

        clock.tick(20)

except KeyboardInterrupt:
    pass

print("\nStopping...")
bot_now("stop")
bot_now("centerhead")
set_mood(4)
pygame.quit()
print("Goodbye! 🤖")
