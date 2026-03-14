#!/usr/bin/env python3
"""
Run on a Raspberry Pi with a PIR connected to GPIO. When motion is detected,
POSTs to the local motion_server (run motion_server.py on the same Pi).
No ESP32 or laptop needed: Pi Zero 2 W + PIR on GPIO + speaker.

Wiring: PIR VCC → 3.3V, PIR OUT → GPIO 17 (or set PIR_PIN below), PIR GND → GND.

Usage:
  # Terminal 1: start the server
  python3 motion_server.py

  # Terminal 2: start the PIR watcher (needs GPIO access)
  python3 pi_pir_trigger.py

Or run both as systemd services.
"""
from __future__ import annotations

import time
import urllib.request

# PIR output pin (BCM numbering). GPIO 17 = pin 11 on 40-pin header.
PIR_PIN = 17
SERVER_URL = "http://127.0.0.1:5000/motion"
COOLDOWN_SEC = 4

def main() -> None:
    try:
        import RPi.GPIO as GPIO
    except ImportError:
        raise SystemExit("RPi.GPIO not found. Install: pip install RPi.GPIO (or use pip3)")

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(PIR_PIN, GPIO.IN)

    last = 0.0
    body = b'{"event":"motion","source":"pi_gpio","play_sound":true}'

    print(f"PIR on GPIO {PIR_PIN}, posting to {SERVER_URL} (cooldown {COOLDOWN_SEC}s)")
    print("Ctrl+C to stop.")

    while True:
        if GPIO.input(PIR_PIN):
            now = time.time()
            if now - last >= COOLDOWN_SEC:
                last = now
                try:
                    req = urllib.request.Request(
                        SERVER_URL,
                        data=body,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        code = resp.getcode()
                    print(f"Motion -> POST {SERVER_URL} -> {code}")
                except Exception as e:
                    print(f"Motion -> POST failed: {e}")
        time.sleep(0.1)


if __name__ == "__main__":
    main()
