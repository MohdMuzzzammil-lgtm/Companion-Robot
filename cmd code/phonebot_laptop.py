import pygame
import requests
import time
import threading
import queue

# ================================================
#   PHONEBOT GAMEPAD — Laptop Controller
#   Clean version — no camera, fast response
# ================================================

ESP32_IP   = "10.239.71.125"   # ← ESP32 IP
PHONE_IP   = "192.168.10.107"   # ← phone IP (for vision toggle)
DEADZONE   = 0.15
SPEED_MS   = [250, 450, 700]    # dpad movement durations
speed_idx  = 1
last_cmd   = ""
last_pan   = 90

# ================================================
#   FAST COMMAND QUEUE
#   Dedicated sender thread — no blocking!
# ================================================
session  = requests.Session()
cmd_q    = queue.Queue(maxsize=5)

def sender():
    """Dedicated thread — sends commands instantly"""
    prev = ""
    while True:
        try:
            cmd = cmd_q.get(timeout=0.05)
            if cmd != prev:
                try:
                    session.get(f"http://{ESP32_IP}/{cmd}",
                                timeout=0.3)
                    prev = cmd
                except:
                    pass
        except queue.Empty:
            pass

threading.Thread(target=sender, daemon=True).start()

def bot(path):
    """Queue command — never blocks main loop"""
    try:
        if cmd_q.full():
            cmd_q.get_nowait()  # drop oldest
        cmd_q.put_nowait(path)
    except:
        pass

def bot_now(path):
    """Send immediately — for one-shot button actions"""
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

# ================================================
#   GAMEPAD SETUP
# ================================================
pygame.init()
pygame.joystick.init()

if pygame.joystick.get_count() == 0:
    print("✗ No controller found!")
    print("  Plug in USB dongle and turn on controller")
    exit()

js = pygame.joystick.Joystick(0)
js.init()

print("\n" + "="*45)
print("  PHONEBOT GAMEPAD")
print("="*45)
print(f"Controller: {js.get_name()}")
print(f"ESP32:      {ESP32_IP}")
print()
print("  Left stick    → Move")
print("  Right stick X → Pan head")
print("  A (0)         → Voice mode")
print("  B (1)         → Look around")
print("  X (2)         → Happy mood")
print("  Y (3)         → Status")
print("  LB (4)        → Speed down")
print("  RB (5)        → Speed up")
print("  SELECT (6)    → Sleep")
print("  START  (7)    → Wake up")
print("  D-pad         → Precise move")
print("  Ctrl+C        → Quit")
print("="*45)

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

btn_prev = [False] * js.get_numbuttons()
clock    = pygame.time.Clock()

# ================================================
#   MAIN LOOP — clean 20Hz
# ================================================
try:
    while True:
        pygame.event.pump()

        # ── Axes with deadzone ─────────────────
        def ax(n):
            v = js.get_axis(n) if n < js.get_numaxes() else 0
            return v if abs(v) > DEADZONE else 0

        lx = ax(0)   # left stick X
        ly = ax(1)   # left stick Y
        rx = ax(2)   # right stick X

        # ── Movement ──────────────────────────
        if abs(ly) > DEADZONE or abs(lx) > DEADZONE:
            if abs(ly) >= abs(lx):
                send_move("forward" if ly < 0 else "backward")
            else:
                send_move("left" if lx < 0 else "right")
        else:
            send_move("stop")

        # ── Pan head ──────────────────────────
        if abs(rx) > DEADZONE:
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

                elif i == 3:  # Y — status
                    print(f"📊 Speed:{speed_idx+1}/3  Pan:{last_pan}°")
                    wiggle(2)

                elif i == 4:  # LB — slower
                    speed_idx = max(0, speed_idx-1)
                    print(f"🐢 Speed {speed_idx+1}/3")

                elif i == 5:  # RB — faster
                    speed_idx = min(2, speed_idx+1)
                    print(f"🐇 Speed {speed_idx+1}/3")

                elif i == 6:  # SELECT — sleep
                    print("😴 Sleep!")
                    set_mood(4)
                    bot_now("stop")
                    bot_now("centerhead")
                    send_move("stop")

                elif i == 7:  # START — wake
                    print("⏰ Wake up!")
                    set_mood(0)
                    bot_now("lookaround")
                    wiggle(5)

                elif i in [8,9,10]:
                    print("🎯 Center!")
                    send_pan(90)
                    bot_now("centerhead")

                else:
                    print(f"Btn {i}")

            btn_prev[i] = pressed

        clock.tick(20)  # 20Hz — clean and responsive

except KeyboardInterrupt:
    pass

print("\nStopping...")
bot_now("stop")
bot_now("centerhead")
set_mood(4)
pygame.quit()
print("Goodbye! 🤖")
