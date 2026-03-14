# ESP32 + PIR motion sensor → storm trooper voice

This sketch runs on an **ESP32** and sends an HTTP POST to your laptop when the PIR detects motion. The laptop runs `motion_server.py` and plays trooper sounds or TTS.

---

## Hardware

| Item | Notes |
|------|--------|
| **ESP32** dev board | Any ESP32 (DevKit, NodeMCU-32S, etc.) |
| **PIR motion sensor** | e.g. HC-SR501 (3-pin: VCC, OUT, GND) |
| **Jumper wires** | 3 wires to connect PIR to ESP32 |

### Wiring

| PIR (HC-SR501) | ESP32 |
|----------------|--------|
| VCC            | 3.3 V (or 5 V if your board has 5 V) |
| OUT            | **GPIO 13** (D13) |
| GND            | GND |

- If the sensor is noisy (false triggers), use `INPUT_PULLDOWN` in code or add a 10 kΩ pull-down on OUT.
- Adjust the small potentiometers on the PIR for sensitivity and trigger time if needed.

---

## Software

### 1. Arduino IDE or PlatformIO

- **Arduino IDE:** Install the [ESP32 board support](https://docs.espressif.com/projects/arduino-esp32/en/latest/installing.html) (Board Manager → “esp32 by Espressif”).
- **PlatformIO:** Create a project for board `esp32dev` (or your exact board).

No extra libraries: `WiFi` and `HTTPClient` are built into the ESP32 Arduino core.

### 2. What to edit in `esp32_pir.ino`

| Constant | What to set |
|----------|-------------|
| `WIFI_SSID` | Your Wi‑Fi network name |
| `WIFI_PASS` | Your Wi‑Fi password |
| `LAPTOP_IP` | Your laptop’s IP on the same Wi‑Fi (e.g. `10.0.0.238`) |
| `LAPTOP_PORT` | Server port (default `5000`) |
| `USE_TROOPER_SOUNDS` | `1` = server plays random file from `trooper_sounds/`, `0` = server uses TTS |

### 3. Finding your laptop IP

On the laptop that runs `motion_server.py`:

- **Linux:** `ip addr` or `hostname -I`
- **macOS:** `ipconfig getifaddr en0` (or your Wi‑Fi interface)
- **Windows:** `ipconfig` (use the IPv4 address of the Wi‑Fi adapter)

Use that IP for `LAPTOP_IP`. Laptop and ESP32 must be on the **same network**.

---

## Upload and run

1. Set **Board** to your ESP32 (e.g. “ESP32 Dev Module”).
2. Set **Port** to the USB port of the ESP32.
3. Edit `WIFI_SSID`, `WIFI_PASS`, and `LAPTOP_IP` (and optionally `LAPTOP_PORT`, `USE_TROOPER_SOUNDS`).
4. Upload the sketch.
5. Open **Serial Monitor** at **115200 baud** to see:
   - `WiFi connected, IP: ...`
   - `Ready for motion.`
   - `POST http://.../motion -> 200` on each trigger.

---

## Optional: change PIR pin or cooldown

- **PIR pin:** Change `PIR_PIN` (default **13**). Avoid pins that are used for flash/PSRAM on your board.
- **Cooldown:** `MIN_GAP_MS` (default **4000**) = minimum milliseconds between two POSTs. Increase to reduce triggers; the server also has a 3 s cooldown.
