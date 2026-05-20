# 🤖 Companion Robot

An AI-powered autonomous two-wheeled robot that uses a **Samsung smartphone as its brain** — no Raspberry Pi, no expensive hardware. Built for under ₹5000.

![Project Status](https://img.shields.io/badge/status-active-brightgreen)
![License](https://img.shields.io/badge/license-MIT-blue)
![Platform](https://img.shields.io/badge/platform-ESP32%20%7C%20Android-orange)

---

## 📸 Demo

![Companion Robot](demo%20image%201)
![Companion Robot](demo%20image%202.jpeg)
![Companion Robot](demo%20image%204.png)
![Companion Robot](demo%20image%203.jpeg
---

## ✨ Features

- **Local LLM** — Llama 3.1 via Ollama on laptop GPU, fully offline AI
- **Voice control** — Whisper speech recognition (cloud + local fallback)
- **Animated eyes** — ILI9341 TFT with 5 moods: happy, curious, angry, listening, sleeping
- **Obstacle avoidance** — dual HC-SR04 ultrasonic sensors with pan compensation
- **Human detection** — YOLOv8 on laptop GPU, reacts when it sees a person
- **Expressive antenna** — wiggles when talking, droops when sleeping
- **Gamepad control** — Cosmic Byte Blitz via laptop
- **Touch controller** — HTML joystick interface in phone browser
- **Display mode** — wheels locked for table demos, everything else alive

---

## 🔧 Hardware

| Component | Purpose |
|-----------|---------|
| Samsung S21 FE | AI brain — runs Python + Whisper in Termux |
| ESP32 DevKit v1 (30-pin) | Hardware controller |
| L298N Motor Driver | Controls 2 DC motors |
| 2× Rhino GB37 12V 110RPM | Drive wheels |
| MG996R Servo | Head pan (GPIO 13) |
| SG90 Servo | Antenna wiggle (GPIO 12) |
| 2× HC-SR04 | Obstacle detection |
| ILI9341 2.8" TFT | Animated robot eyes |
| Cosmic Byte Blitz Gamepad | Manual control |
| 2S LiPo 7.4V | Motors + pan servo |
| Power bank 5V | ESP32 + TFT + sensors |

---

## 📌 ESP32 Pin Map

```
GPIO 27 → L298N IN1          GPIO 5  → HC-SR04 Left TRIG
GPIO 26 → L298N IN2          GPIO 34 → HC-SR04 Left ECHO
GPIO 25 → L298N IN3          GPIO 22 → HC-SR04 Right TRIG
GPIO 33 → L298N IN4          GPIO 35 → HC-SR04 Right ECHO
GPIO 13 → MG996R Pan Servo   GPIO 32 → Push Button
GPIO 12 → SG90 Antenna       GPIO 15 → TFT CS
GPIO 23 → TFT MOSI           GPIO 18 → TFT SCK
GPIO 4  → TFT RST            GPIO 2  → TFT DC
```

---

## 🗂️ File Structure

```
companion-robot/
│
├── esp32/
│   └── phonebot_esp32.ino       # ESP32 firmware (Arduino)
│
├── phone/
│   └── robot_brain_v9.py        # Phone brain (Termux Python)
│
├── laptop/
│   ├── phonebot_laptop.py       # Gamepad + YOLOv8 vision
│   └── phonebot_vision.py       # Vision only (older)
│
├── web/
│   ├── phonebot_controller.html # Touch joystick controller
│   └── phonebot_display.html    # Chest status display
│
└── README.md
```

---

## 🚀 Setup

### Prerequisites

**Phone (Termux):**
```bash
pkg install python ffmpeg
pip install requests groq
```

**Laptop:**
```bash
pip install pygame requests ultralytics opencv-python
# Install Ollama: https://ollama.com
ollama pull llama3.1
```

**Arduino IDE** — install these libraries:
- `ESP32Servo`
- `TFT_eSPI`
- `WebServer` (built-in)

### TFT_eSPI User_Setup.h
```cpp
#define ILI9341_DRIVER
#define TFT_MOSI  23
#define TFT_SCLK  18
#define TFT_CS    15
#define TFT_DC     2
#define TFT_RST    4
#define TFT_MISO  -1
#define SPI_FREQUENCY 40000000
```

---

## ⚙️ Configuration

Edit the top of `robot_brain_v9.py` each session:

```python
ESP32_IP   = "X.X.X.X"      # check ESP32 Serial Monitor
LAPTOP_IP  = "X.X.X.X"      # run ipconfig on laptop
GROQ_KEY   = "your_key"      # from console.groq.com (free)
SAFE_DIST  = 40              # obstacle threshold in cm
```

For Ollama to work over WiFi:
```cmd
set OLLAMA_HOST=0.0.0.0:11434
ollama serve
```

---

## 🎮 Startup Checklist

```
1. Turn on phone hotspot (Galaxy S21 / your password)
2. Power ESP32 → note IP from Serial Monitor
3. Connect laptop to hotspot → run ipconfig → note IP
4. Start Ollama: set OLLAMA_HOST=0.0.0.0:11434 && ollama serve
5. Update IPs in robot_brain_v9.py and phonebot_laptop.py
6. Phone Termux:
      termux-wake-lock
      python ~/robot_brain_v9.py
7. Laptop:
      python phonebot_laptop.py
8. Optional touch controller → open in Chrome:
      file:///sdcard/phonebot_controller.html
```

---

## 🗣️ Voice Commands

| Say | Action |
|-----|--------|
| *"showcase"* / *"demo"* | Runs table demo routine |
| *"look around"* | Scans environment |
| *"sleep"* / *"goodnight"* | Sleep mode |
| *"wake up"* / *"hello"* | Wake animation |
| *"display mode"* | Lock wheels for table display |
| *"drive mode"* | Unlock wheels |
| *"status"* | Reports AI + STT source |
| Anything else | AI conversation via Llama 3.1 |

---

## 🎮 Gamepad Controls

| Button | Action |
|--------|--------|
| Left stick | Move |
| Right stick X | Pan head |
| A | Voice mode |
| B | Look around |
| X | Happy mood |
| Y | Toggle vision |
| LB / RB | Speed down / up |
| SELECT | Sleep |
| START | Wake up |

---

## 🌐 ESP32 HTTP API

```
GET /forward         GET /backward        GET /left
GET /right           GET /stop
GET /pan?angle=N     (30–150°)
GET /mood?m=N        (0=happy 1=curious 2=angry 3=listening 4=sleeping)
GET /sensors         returns {"left":N,"right":N,"pan":N}
GET /lookaround      7-angle environment scan
GET /button          returns {"pressed":true/false}
GET /antenna?wiggle=N
GET /displaymode?on=1   lock wheels for table demo
GET /displaymode?on=0   unlock wheels
```

---

## 💡 How It Works

```
[Person speaks] → Phone mic → Whisper STT
                                    ↓
                             Llama 3.1 (Ollama on laptop)
                                    ↓
                    Response → TTS (termux-tts-speak)
                             → ESP32 movement command
                             → Eye mood change

[Camera] → YOLOv8 (laptop) → person detected
                                    ↓
                    Reaction → TTS greeting
                             → Bot turns toward person
                             → Antenna wiggle
```

---

## 🛒 Parts List (India)

| Part | Approx Cost |
|------|-------------|
| ESP32 DevKit v1 | ₹350 |
| L298N Motor Driver | ₹120 |
| 2× Rhino GB37 Motors | ₹1200 |
| MG996R Servo | ₹200 |
| SG90 Servo | ₹80 |
| 2× HC-SR04 | ₹100 |
| ILI9341 TFT 2.8" | ₹350 |
| 2S LiPo Battery | ₹600 |
| Miscellaneous (wires, standoffs) | ₹300 |
| **Total** | **~₹3300** |

> Samsung S21 FE and laptop not included — reused existing hardware

---

## 📋 Known Issues

- HC-SR04 ECHO pins need `INPUT_PULLUP` (not `INPUT`)
- GPIO 19 conflicts with TFT MISO — Right TRIG moved to GPIO 22
- `termux-tts-speak` must use `Popen` not `run` to avoid timeout
- OTG serial not possible on unrooted Samsung S21 FE
- Ollama must have `OLLAMA_HOST=0.0.0.0:11434` to be reachable over WiFi

---

## 🙏 Acknowledgements

- [Ollama](https://ollama.com) — local LLM serving
- [Groq](https://groq.com) — cloud AI + Whisper fallback
- [Ultralytics YOLOv8](https://github.com/ultralytics/ultralytics) — human detection
- [TFT_eSPI](https://github.com/Bodmer/TFT_eSPI) — ESP32 display library
- [whisper.cpp](https://github.com/ggerganov/whisper.cpp) — local STT fallback

---

## 📄 License

MIT License — free to use, modify, and share.

---
