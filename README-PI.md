# Pi-only setup (no laptop, no ESP32)

Run everything on a **Raspberry Pi Zero 2 W** (or any Pi with WiFi and GPIO):

- **PIR** → Pi GPIO  
- **motion_server.py** → plays trooper sounds / TTS  
- **pi_pir_trigger.py** → watches PIR, POSTs to the server on localhost  

**Hardware:** PIR **HC-SR501** (5 V VCC, 3.3 V logic output). Audio **Waveshare WM8960 Audio HAT** (I2S, 3.5 mm jack + speaker outs).

You only need: **Pi + PIR + power + audio out** (WM8960 HAT, HDMI, or USB sound card).

---

## Wiring (BCM)

| PIR (HC-SR501) | Pi Zero 2 W        |
|----------------|--------------------|
| VCC            | **5 V** (pin 2 or 4) |
| OUT            | **GPIO 17** (pin 11) |
| GND            | GND (pin 6, 9, 14, etc.) |

Change `PIR_PIN` in `pi_pir_trigger.py` if you use another GPIO.

---

## Setup on the Pi

```bash
# System packages (audio + GPIO)
sudo apt update
sudo apt install python3-venv python3-pip ffmpeg
# RPi.GPIO: use the venv (required for systemd). apt’s python3-rpi.gpio is system Python only.
# pip install -r requirements.txt already includes RPi.GPIO; or: source venv/bin/activate && pip install RPi.GPIO

# Project (recommended path for systemd; see “Git on the Pi” below)
cd /home/pi/pir_motion_sensor
git clone https://github.com/jdcast/pir_motion_sensor.git .   # first time only; or your fork URL
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Put your audio files in trooper_sounds/ (not in git; create the folder on the Pi)
```

---

## Git on the Pi: clone/pull vs copying files

**Prefer `git clone` / `git pull` on the Pi** into a fixed directory (e.g. `/home/pi/pir_motion_sensor`): one place for `motion_server.py`, `pi_pir_trigger.py`, `requirements.txt`, and the systemd units; updates are a `git pull` and restart. Copying single files into `~/Downloads` is fine for quick tests but paths drift and systemd is harder to keep consistent.

---

## Run (manual, two terminals)

**Terminal 1 – server (WM8960 example):**
```bash
cd /home/pi/pir_motion_sensor
source venv/bin/activate
export AUDIO_DEVICE=plughw:0,0
export TROOPER_SOUNDS_DIR=/home/pi/pir_motion_sensor/trooper_sounds
python3 motion_server.py
```

**Terminal 2 – PIR trigger** (`pi` must be in the **`gpio`** group, or use `sudo`):
```bash
cd /home/pi/pir_motion_sensor
source venv/bin/activate
python3 pi_pir_trigger.py
```

```bash
sudo usermod -aG gpio,audio pi   # then log out/in or reboot
```

Motion on the PIR → trigger POSTs to `http://127.0.0.1:5000/motion` with `play_sound: true` → server plays a random file from `trooper_sounds/` (or TTS if you don’t use `play_sound`).

---

## Run at boot (systemd)

Templates live in **`systemd/`** in this repo. They assume **`/home/pi/pir_motion_sensor`**, venv Python, `AUDIO_DEVICE=plughw:0,0`, and `TROOPER_SOUNDS_DIR` pointing at your sounds folder. **Edit the `.service` files** if you use another user, path, or device.

```bash
cd /home/pi/pir_motion_sensor
sudo cp systemd/pir-motion-server.service systemd/pir-motion-trigger.service /etc/systemd/system/
# Edit copies in /etc/systemd/system/ if needed, then:
sudo systemctl daemon-reload
sudo systemctl enable --now pir-motion-server.service
sudo systemctl enable --now pir-motion-trigger.service
```

See **`systemd/README.md`** for status, logs, and troubleshooting.

---

## Waveshare WM8960 Audio HAT (headphones/speaker on the HAT)

Per the [Waveshare WM8960 wiki](https://www.waveshare.com/wiki/WM8960_Audio_HAT): install the HAT driver, then do the following so **motion_server** can play through it.

### 1. Install HAT driver (if not done)

```bash
git clone https://github.com/waveshare/WM8960-Audio-HAT
cd WM8960-Audio-HAT
sudo chmod +x install.sh
sudo ./install.sh
sudo reboot
```

Check: `sudo dkms status` should list `wm8960-soundcard`. Check card: `aplay -l` should show `wm8960soundcard`.

### 2. Packages and permissions

```bash
# Required for aplay (server uses it when AUDIO_DEVICE is set)
sudo apt install alsa-utils ffmpeg

# So your user can use the sound card without sudo (wiki examples use sudo)
sudo usermod -aG audio $USER
# Log out and back in (or reboot) for the group to apply
```

### 3. If the 3.5 mm jack has no sound (from wiki)

```bash
sudo systemctl restart wm8960-soundcard.service
```

### 4. Volume

```bash
alsamixer
```

Press **F6**, choose **wm8960-soundcard**, raise **Headphone** (and **Speaker** if using the HAT’s speaker outs). Save with Esc.

### 5. Confirm playback as your user

```bash
# Use the card index from aplay -l (often 0, sometimes 1)
aplay -D hw:0,0 /usr/share/sounds/alsa/Front_Center.wav
```

If you get “Permission denied”, you’re not in the `audio` group yet (log out/in). If you hear nothing, try `hw:1,0` and/or restart the HAT service (step 3).

### 6. Run the server with the HAT as output

```bash
# Use the same device as in step 5 (hw:0,0 or hw:1,0; plughw: is safer for format conversion)
export AUDIO_DEVICE=plughw:0,0
python3 motion_server.py
```

Then trigger motion (e.g. `curl -X POST http://127.0.0.1:5000/motion -H "Content-Type: application/json" -d '{"play_sound":true}'`). If the server log shows **“ALSA playback failed”**, the message will include the reason (e.g. permission or wrong device).
