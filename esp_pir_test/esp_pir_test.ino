/*
 * ESP32 + PIR motion sensor → POSTs to laptop motion_server (trooper voice/sounds).
 * Needs: ESP32 board, PIR (e.g. HC-SR501) OUT → GPIO13, VCC, GND.
 * Set WIFI_SSID, WIFI_PASS, LAPTOP_IP (laptop IP on same WiFi). See README.md.
 */
#include <WiFi.h>
#include <HTTPClient.h>

const char* WIFI_SSID = "";
const char* WIFI_PASS = "";

const char* LAPTOP_IP = "10.0.0.165";  // <-- change this
const int   LAPTOP_PORT = 5000;

#define USE_TROOPER_SOUNDS 1  // 1 = play random from trooper_sounds/, 0 = TTS

static const int PIR_PIN = 13;           // D13 / GPIO13
static const unsigned long MIN_GAP_MS = 4000; // anti-spam cooldown

volatile bool motionFlag = false;
volatile unsigned long lastIsrMs = 0;

void IRAM_ATTR onPirRise() {
  unsigned long now = millis();
  if (now - lastIsrMs > MIN_GAP_MS) {
    lastIsrMs = now;
    motionFlag = true;
  }
}

void wifiConnect() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("WiFi connecting");
  while (WiFi.status() != WL_CONNECTED) {
    delay(250);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("WiFi connected, IP: ");
  Serial.println(WiFi.localIP());
}

void postMotion() {
  if (WiFi.status() != WL_CONNECTED) return;

  String url = String("http://") + LAPTOP_IP + ":" + String(LAPTOP_PORT) + "/motion";
  HTTPClient http;
  http.begin(url);
  http.addHeader("Content-Type", "application/json");

  String body = "{\"event\":\"motion\",\"esp_ms\":" + String(millis());
  if (USE_TROOPER_SOUNDS) body += ",\"play_sound\":true";
  body += "}";
  int code = http.POST(body);

  Serial.print("POST ");
  Serial.print(url);
  Serial.print(" -> ");
  Serial.println(code);

  http.end();
}

void setup() {
  Serial.begin(115200);

  pinMode(PIR_PIN, INPUT); // if noisy, try INPUT_PULLDOWN
  attachInterrupt(digitalPinToInterrupt(PIR_PIN), onPirRise, RISING);

  wifiConnect();
  Serial.println("Ready for motion.");
}

void loop() {
  if (motionFlag) {
    motionFlag = false;
    postMotion();
  }

  // keep WiFi alive
  if (WiFi.status() != WL_CONNECTED) {
    wifiConnect();
  }

  delay(20);
}
