#include <WiFi.h>
#include <WebServer.h>
#include <ESP32Servo.h>
#include <TFT_eSPI.h>
#include <math.h>

// ================================================
//   PHONEBOT ESP32 FIRMWARE v7
//   WALL-E STYLE FACE
//   - Cute rounded eyes with thick frames
//   - Expressive moving eyebrows
//   - Particle sparkles around eyes
//   - Animated dot-grid background
//   - Smooth gaze interpolation
//   - Mood burst animations
// ================================================

const char* ssid     = "wifi name";
const char* password = "wifi password";
WebServer server(80);

// ── Hardware pins ─────────────────────────────────
#define IN1 27
#define IN2 26
#define IN3 25
#define IN4 33
#define PAN_PIN  13
#define TILT_PIN 12
#define TRIG_L  5
#define ECHO_L 34
#define TRIG_R 19
#define ECHO_R 21
#define BTN_PIN 32

Servo panServo;
Servo tiltServo;
TFT_eSPI tft = TFT_eSPI();

// ── Screen ────────────────────────────────────────
#define SW 320
#define SH 240

// ── Eye geometry ──────────────────────────────────
#define EYE_R       52
#define EYE_RIM      7
#define IRIS_R      28
#define PUPIL_R     13
#define L_EX        98
#define R_EX       222
#define EY         125

// ── Eyebrow ───────────────────────────────────────
#define BROW_W      52
#define BROW_H       7
#define BROW_Y_OFF  68

// ── Particles ─────────────────────────────────────
#define MAX_PARTICLES 16
struct Particle {
  float x, y, vx, vy, life;
  uint16_t color;
  bool active;
};
Particle particles[MAX_PARTICLES];

// ── Mood definitions ──────────────────────────────
struct MoodDef {
  uint16_t bgColor;
  uint16_t rimColor;
  uint16_t irisColor;
  uint16_t irisInner;
  uint16_t shineColor;
  uint16_t browColor;
  uint16_t particleCol;
  int      browLift;
  int      browAngleL;
  int      browAngleR;
  float    irisScale;
};

MoodDef moods[] = {
  // bg      rim     iris    inner   shine   brow    particle  lift angL angR  scale
  { 0x0841, 0x4BDF, 0x075F, 0x03BF, 0xFFFF, 0x4BDF, 0x07FF,    0,   0,   0, 1.00 }, // 0 happy    cyan
  { 0x0020, 0x07E0, 0x03C0, 0x0200, 0xFFFF, 0x07E0, 0x07E0,    6,  -8,   8, 1.10 }, // 1 curious  green
  { 0x1800, 0xF800, 0xF000, 0x7800, 0xFFFF, 0xF800, 0xFC00,   -8,  16, -16, 0.85 }, // 2 angry    red
  { 0x1008, 0xF81F, 0xC00F, 0x6007, 0xFFFF, 0xF81F, 0xF81F,    8,  -4,   4, 1.20 }, // 3 listening pink
  { 0x0000, 0x2945, 0x1082, 0x0841, 0x4208, 0x2945, 0x2104,    2,   0,   0, 0.70 }, // 4 sleeping dim
};

// ── State ─────────────────────────────────────────
int   currentMood     = 0;
float gazeX = 0, gazeY = 0;
float gazeXS = 0, gazeYS = 0;   // smoothed
bool  blinking        = false;
unsigned long lastBlink    = 0;
unsigned long lastGaze     = 0;
unsigned long lastParticle = 0;
unsigned long lastBg       = 0;
int   blinkInterval   = 4000;
volatile bool buttonPressed = false;
float dotPhase = 0;

// ================================================
//   MOTOR / SERVO / SENSOR
// ================================================

long getDistance(int trig, int echo) {
  digitalWrite(trig,LOW); delayMicroseconds(2);
  digitalWrite(trig,HIGH); delayMicroseconds(10);
  digitalWrite(trig,LOW);
  long d = pulseIn(echo,HIGH,30000);
  return d==0 ? 999 : d*0.034/2;
}
void stopAll()    { digitalWrite(IN1,0);digitalWrite(IN2,0);digitalWrite(IN3,0);digitalWrite(IN4,0); }
void goForward()  { digitalWrite(IN1,1);digitalWrite(IN2,0);digitalWrite(IN3,1);digitalWrite(IN4,0); }
void goBackward() { digitalWrite(IN1,0);digitalWrite(IN2,1);digitalWrite(IN3,0);digitalWrite(IN4,1); }
void turnLeft()   { digitalWrite(IN1,0);digitalWrite(IN2,1);digitalWrite(IN3,1);digitalWrite(IN4,0); }
void turnRight()  { digitalWrite(IN1,1);digitalWrite(IN2,0);digitalWrite(IN3,0);digitalWrite(IN4,1); }
void movePan(int a)  { panServo.write(constrain(a,30,150)); }
void moveTilt(int a) { tiltServo.write(constrain(a,50,120)); }
void centerHead()    { movePan(90); moveTilt(90); }

void IRAM_ATTR onButtonPress() {
  static unsigned long last=0;
  unsigned long now=millis();
  if(now-last>300){ buttonPressed=true; last=now; }
}

// ================================================
//   PARTICLES
// ================================================

void spawnParticle(float cx, float cy, uint16_t col) {
  for (int i = 0; i < MAX_PARTICLES; i++) {
    if (!particles[i].active) {
      float angle = random(360) * 3.14159 / 180.0;
      float speed = 0.8 + random(100)/100.0 * 1.5;
      particles[i].x     = cx + cos(angle) * (EYE_R + 4);
      particles[i].y     = cy + sin(angle) * (EYE_R + 4);
      particles[i].vx    = cos(angle) * speed;
      particles[i].vy    = sin(angle) * speed - 0.5;
      particles[i].life  = 1.0;
      particles[i].color = col;
      particles[i].active = true;
      break;
    }
  }
}

void spawnBurst(float cx, float cy, uint16_t col, int count) {
  for (int i = 0; i < count; i++) spawnParticle(cx, cy, col);
}

void updateParticles() {
  for (int i = 0; i < MAX_PARTICLES; i++) {
    if (!particles[i].active) continue;
    tft.fillCircle((int)particles[i].x, (int)particles[i].y, 2, TFT_BLACK);
    particles[i].x   += particles[i].vx;
    particles[i].y   += particles[i].vy;
    particles[i].vy  += 0.07;
    particles[i].life -= 0.045;
    if (particles[i].life <= 0) { particles[i].active = false; continue; }
    uint16_t c = particles[i].life > 0.4 ? particles[i].color : 0x4208;
    tft.fillCircle((int)particles[i].x, (int)particles[i].y, 2, c);
  }
}

// ================================================
//   DOT GRID BACKGROUND
// ================================================

void updateDotGrid() {
  dotPhase += 0.09;
  MoodDef& mc = moods[currentMood];
  int spX = SW / 16, spY = SH / 12;
  for (int col = 0; col < 16; col++) {
    for (int row = 0; row < 12; row++) {
      int dx = col * spX + spX/2;
      int dy = row * spY + spY/2;
      float dL = sqrt((float)(dx-L_EX)*(dx-L_EX) + (float)(dy-EY)*(dy-EY));
      float dR = sqrt((float)(dx-R_EX)*(dx-R_EX) + (float)(dy-EY)*(dy-EY));
      if (dL < EYE_R + EYE_RIM + 12 || dR < EYE_R + EYE_RIM + 12) continue;
      float wave = sin(dotPhase + col * 0.45 + row * 0.55);
      tft.fillRect(dx, dy, 1, 1, wave > 0.25 ? mc.bgColor : TFT_BLACK);
    }
  }
}

// ================================================
//   EYEBROW
// ================================================

void drawBrow(int cx, int side, int mood, bool erase) {
  MoodDef& mc = moods[mood];
  int by = EY - BROW_Y_OFF + mc.browLift;
  int innerOff = (side == -1) ? mc.browAngleL : mc.browAngleR;
  int x1 = cx - BROW_W/2;
  int x2 = cx + BROW_W/2;
  int y1 = (side == -1) ? by + innerOff : by - innerOff;
  int y2 = (side == -1) ? by - innerOff : by + innerOff;
  uint16_t col = erase ? TFT_BLACK : mc.browColor;
  for (int t = 0; t < BROW_H; t++) {
    tft.drawLine(x1, y1+t, x2, y2+t, col);
  }
  tft.fillCircle(x1, y1 + BROW_H/2, BROW_H/2, col);
  tft.fillCircle(x2, y2 + BROW_H/2, BROW_H/2, col);
}

void drawBothBrows(int mood, bool erase=false) {
  drawBrow(L_EX, -1, mood, erase);
  drawBrow(R_EX,  1, mood, erase);
}

// ================================================
//   EYE DRAWING — WALL-E STYLE
// ================================================

void drawEye(int cx, int cy, int mood, float gx, float gy, int lidClose) {
  MoodDef& mc = moods[mood];
  float iscale = mc.irisScale;
  int ir = (int)(IRIS_R * iscale);

  // Outer black clear
  tft.fillCircle(cx, cy, EYE_R + EYE_RIM + 3, TFT_BLACK);

  // Thick rim — signature Wall-E look
  tft.fillCircle(cx, cy, EYE_R + EYE_RIM, mc.rimColor);

  // White eyeball
  tft.fillCircle(cx, cy, EYE_R, TFT_WHITE);

  // Iris position with gaze
  int maxG = EYE_R - ir - 5;
  int ix = cx + constrain((int)(gx * maxG), -maxG, maxG);
  int iy = cy + constrain((int)(gy * maxG), -maxG, maxG);

  // Iris layers for depth
  tft.fillCircle(ix, iy, ir + 3, mc.irisInner);
  tft.fillCircle(ix, iy, ir,     mc.irisColor);
  tft.fillCircle(ix, iy, ir - 5, mc.irisInner);

  // Pupil — dilates when listening
  int pr = (mood == 3) ? (int)(PUPIL_R * 1.35) : PUPIL_R;
  tft.fillCircle(ix, iy, pr, TFT_BLACK);

  // Shine dots — Wall-E's cute sparkle
  tft.fillCircle(ix - ir*0.38, iy - ir*0.38, (int)(ir*0.26), mc.shineColor);
  tft.fillCircle(ix + ir*0.15, iy - ir*0.12, (int)(ir*0.12), 0xC618);

  // Sleeping eyelid from bottom
  if (mood == 4) {
    tft.fillRect(cx - EYE_R - 2, (int)(cy + EYE_R*0.08),
                 (EYE_R+2)*2, EYE_R + EYE_RIM + 4, TFT_BLACK);
  }

  // Angry diagonal cut
  if (mood == 2 && lidClose == 0) {
    int cut = (int)(EYE_R * 0.45);
    for (int px = cx - EYE_R; px <= cx + EYE_R; px++) {
      float progress = (float)(px - (cx - EYE_R)) / (EYE_R * 2);
      int cutY = (cx == L_EX)
        ? (cy - EYE_R) + (int)(progress * cut * 1.8)
        : (cy - EYE_R) + (int)((1.0-progress) * cut * 1.8);
      if (cutY > cy - EYE_R)
        tft.drawFastVLine(px, cy - EYE_R - EYE_RIM - 2,
                          cutY - (cy - EYE_R) + EYE_RIM + 2, TFT_BLACK);
    }
  }

  // Blink lid from top
  if (lidClose > 0) {
    tft.fillRect(cx - EYE_R - EYE_RIM - 2,
                 cy - EYE_R - EYE_RIM - 2,
                 (EYE_R + EYE_RIM + 2) * 2,
                 constrain(lidClose, 0, (EYE_R+EYE_RIM)*2+4),
                 TFT_BLACK);
  }

  // Rim highlight arc
  if (mood != 4 && lidClose < EYE_R) {
    for (int a = 205; a <= 335; a += 5) {
      float rad = a * 3.14159 / 180.0;
      tft.drawPixel(
        cx + (int)((EYE_R + EYE_RIM - 2) * cos(rad)),
        cy + (int)((EYE_R + EYE_RIM - 2) * sin(rad)),
        0xFFFF);
    }
  }
}

void drawFace() {
  int lid = blinking ? (EYE_R + EYE_RIM) * 2 : 0;
  drawEye(L_EX, EY, currentMood, gazeXS, gazeYS, lid);
  drawEye(R_EX, EY, currentMood, gazeXS, gazeYS, lid);
  if (!blinking) drawBothBrows(currentMood);
}

void eraseFace() {
  tft.fillCircle(L_EX, EY, EYE_R + EYE_RIM + 4, TFT_BLACK);
  tft.fillCircle(R_EX, EY, EYE_R + EYE_RIM + 4, TFT_BLACK);
  // Erase brow area
  tft.fillRect(L_EX - BROW_W/2 - 8, EY - BROW_Y_OFF - 12, BROW_W+16, BROW_H+20, TFT_BLACK);
  tft.fillRect(R_EX - BROW_W/2 - 8, EY - BROW_Y_OFF - 12, BROW_W+16, BROW_H+20, TFT_BLACK);
}

// ================================================
//   BLINK
// ================================================

void doBlink() {
  for (int l = 0; l <= (EYE_R+EYE_RIM)*2; l += 18) {
    tft.fillCircle(L_EX, EY, EYE_R+EYE_RIM+4, TFT_BLACK);
    tft.fillCircle(R_EX, EY, EYE_R+EYE_RIM+4, TFT_BLACK);
    drawEye(L_EX, EY, currentMood, gazeXS, gazeYS, l);
    drawEye(R_EX, EY, currentMood, gazeXS, gazeYS, l);
    delay(16);
  }
  delay(55);
  for (int l = (EYE_R+EYE_RIM)*2; l >= 0; l -= 18) {
    tft.fillCircle(L_EX, EY, EYE_R+EYE_RIM+4, TFT_BLACK);
    tft.fillCircle(R_EX, EY, EYE_R+EYE_RIM+4, TFT_BLACK);
    drawEye(L_EX, EY, currentMood, gazeXS, gazeYS, l);
    drawEye(R_EX, EY, currentMood, gazeXS, gazeYS, l);
    delay(13);
  }
  drawBothBrows(currentMood);
  if (random(5) == 0) { delay(90); doBlink(); }
}

// ================================================
//   MOOD
// ================================================

void setMood(int mood) {
  int prev = currentMood;
  currentMood = constrain(mood, 0, 4);
  switch(currentMood) {
    case 0: blinkInterval = 4000;  break;
    case 1: blinkInterval = 2000;  break;
    case 2: blinkInterval = 8000;  break;
    case 3: blinkInterval = 10000; break;
    case 4: blinkInterval = 500;   break;
  }
  eraseFace();
  tft.fillScreen(TFT_BLACK);
  if (mood != prev && mood != 4) {
    spawnBurst(L_EX, EY, moods[mood].particleCol, 7);
    spawnBurst(R_EX, EY, moods[mood].particleCol, 7);
  }
  drawFace();
}

// ================================================
//   MAIN ANIMATION
// ================================================

void updateFace() {
  unsigned long now = millis();

  // Smooth gaze
  float px = gazeXS, py = gazeYS;
  gazeXS += (gazeX - gazeXS) * 0.10;
  gazeYS += (gazeY - gazeYS) * 0.10;

  // Redraw iris if moved
  if (abs(gazeXS-px) > 0.008 || abs(gazeYS-py) > 0.008) {
    if (!blinking) {
      tft.fillCircle(L_EX, EY, EYE_R+1, TFT_WHITE);
      tft.fillCircle(R_EX, EY, EYE_R+1, TFT_WHITE);
      drawEye(L_EX, EY, currentMood, gazeXS, gazeYS, 0);
      drawEye(R_EX, EY, currentMood, gazeXS, gazeYS, 0);
    }
  }

  // Random gaze shift
  if (now - lastGaze > 900 + random(2200)) {
    lastGaze = now;
    if (currentMood != 4) {
      gazeX = (random(200)-100)/100.0 * 0.65;
      gazeY = (random(160)-80) /100.0 * 0.55;
    }
  }

  // Blink
  if (now - lastBlink > (unsigned long)(blinkInterval + random(2500))) {
    lastBlink = now;
    if (currentMood != 4) {
      doBlink();
    } else {
      // Sleeping flutter
      drawEye(L_EX, EY, currentMood, 0, 0, 4);
      drawEye(R_EX, EY, currentMood, 0, 0, 4);
      delay(70);
      drawEye(L_EX, EY, currentMood, 0, 0, 0);
      drawEye(R_EX, EY, currentMood, 0, 0, 0);
    }
  }

  // Particles — occasional sparkle around eyes
  if (now - lastParticle > 380 && currentMood != 4 && random(3)==0) {
    lastParticle = now;
    spawnParticle(L_EX, EY, moods[currentMood].particleCol);
    spawnParticle(R_EX, EY, moods[currentMood].particleCol);
  }
  updateParticles();

  // Background dot grid
  if (now - lastBg > 110) {
    lastBg = now;
    updateDotGrid();
  }
}

// ================================================
//   HTTP ROUTES
// ================================================

void setupRoutes() {
  server.on("/", [](){ server.send(200,"text/plain","PhoneBot V7!"); });
  server.on("/forward",  [](){ goForward();  server.send(200,"text/plain","ok"); delay(500); stopAll(); });
  server.on("/backward", [](){ goBackward(); server.send(200,"text/plain","ok"); delay(500); stopAll(); });
  server.on("/left",     [](){ turnLeft();   server.send(200,"text/plain","ok"); delay(350); stopAll(); });
  server.on("/right",    [](){ turnRight();  server.send(200,"text/plain","ok"); delay(350); stopAll(); });
  server.on("/stop",     [](){ stopAll();    server.send(200,"text/plain","ok"); });
  server.on("/pan",  [](){ if(server.hasArg("angle")) movePan(server.arg("angle").toInt());  server.send(200,"text/plain","ok"); });
  server.on("/tilt", [](){ if(server.hasArg("angle")) moveTilt(server.arg("angle").toInt()); server.send(200,"text/plain","ok"); });
  server.on("/centerhead", [](){ centerHead(); server.send(200,"text/plain","ok"); });
  server.on("/lookaround", [](){
    movePan(55); delay(400); movePan(125); delay(400);
    movePan(90); delay(200); moveTilt(70); delay(300); moveTilt(90);
    server.send(200,"text/plain","ok");
  });
  server.on("/sensors", [](){
    long dL=getDistance(TRIG_L,ECHO_L);
    long dR=getDistance(TRIG_R,ECHO_R);
    server.send(200,"application/json",
      "{\"left\":"+String(dL)+",\"right\":"+String(dR)+"}");
  });
  server.on("/button", [](){
    if(buttonPressed){ buttonPressed=false;
      server.send(200,"application/json","{\"pressed\":true}"); }
    else server.send(200,"application/json","{\"pressed\":false}");
  });
  server.on("/mood", [](){
    if(server.hasArg("m")) setMood(server.arg("m").toInt());
    server.send(200,"text/plain",String(currentMood));
  });
  server.on("/look", [](){
    if(server.hasArg("x")) gazeX = server.arg("x").toInt()/100.0;
    if(server.hasArg("y")) gazeY = server.arg("y").toInt()/100.0;
    server.send(200,"text/plain","ok");
  });
}

// ================================================
//   SETUP
// ================================================

void setup() {
  Serial.begin(115200);
  Serial.println("\n=== PhoneBot V7 Booting ===");

  pinMode(IN1,OUTPUT); pinMode(IN2,OUTPUT);
  pinMode(IN3,OUTPUT); pinMode(IN4,OUTPUT);
  stopAll();
  pinMode(TRIG_L,OUTPUT); pinMode(ECHO_L,INPUT);
  pinMode(TRIG_R,OUTPUT); pinMode(ECHO_R,INPUT);
  panServo.attach(PAN_PIN);
  tiltServo.attach(TILT_PIN);
  centerHead();
  pinMode(BTN_PIN,INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(BTN_PIN),onButtonPress,FALLING);

  tft.init();
  tft.setRotation(3);
  tft.fillScreen(TFT_BLACK);

  for (int i = 0; i < MAX_PARTICLES; i++) particles[i].active = false;

  // ── Boot animation ─────────────────────────────
  currentMood = 0;
  gazeX = gazeY = gazeXS = gazeYS = 0;

  // Eyes grow from center dot
  for (int r = 2; r <= EYE_R + EYE_RIM; r += 4) {
    tft.fillCircle(L_EX, EY, r, moods[0].rimColor);
    tft.fillCircle(R_EX, EY, r, moods[0].rimColor);
    delay(15);
  }
  delay(180);

  // Eyes open — lid rises
  for (int l = (EYE_R+EYE_RIM)*2; l >= 0; l -= 12) {
    tft.fillCircle(L_EX, EY, EYE_R+EYE_RIM+4, TFT_BLACK);
    tft.fillCircle(R_EX, EY, EYE_R+EYE_RIM+4, TFT_BLACK);
    drawEye(L_EX, EY, 0, 0, 0, l);
    drawEye(R_EX, EY, 0, 0, 0, l);
    delay(18);
  }
  drawBothBrows(0);

  // Particle burst on wake!
  spawnBurst(L_EX, EY, moods[0].particleCol, 10);
  spawnBurst(R_EX, EY, moods[0].particleCol, 10);
  for (int i = 0; i < 25; i++) { updateParticles(); delay(25); }

  // Curious look-around like Wall-E waking up
  gazeX=-0.8; delay(280);
  gazeX= 0.8; delay(280);
  gazeX=0; gazeY=-0.5; delay(200);
  gazeX=0; gazeY=0;

  // WiFi — blink while connecting
  WiFi.begin(ssid, password);
  Serial.print("Connecting");
  while (WiFi.status() != WL_CONNECTED) {
    delay(350); Serial.print(".");
    doBlink();
  }
  Serial.println("\n✓ http://" + WiFi.localIP().toString());

  // Happy burst on connected!
  spawnBurst(L_EX, EY, moods[0].particleCol, 12);
  spawnBurst(R_EX, EY, moods[0].particleCol, 12);

  setupRoutes();
  server.begin();
  Serial.println("=== PhoneBot V7 Ready! ===");
}

void loop() {
  server.handleClient();
  updateFace();
}
