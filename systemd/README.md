# systemd (start on boot)

Unit files expect the project at **`/home/pi/pir_motion_sensor`** with a venv and `trooper_sounds/` populated. Edit `User=`, paths, and `Environment=` lines if your layout differs (e.g. you still use `~/Downloads`).

1. Copy units and reload:

```bash
sudo cp systemd/pir-motion-server.service systemd/pir-motion-trigger.service /etc/systemd/system/
sudo systemctl daemon-reload
```

2. Enable and start:

```bash
sudo systemctl enable --now pir-motion-server.service
sudo systemctl enable --now pir-motion-trigger.service
```

3. Check status / logs:

```bash
systemctl status pir-motion-server.service pir-motion-trigger.service
journalctl -u pir-motion-server.service -u pir-motion-trigger.service -f
```

**User `pi` must be in `audio` and `gpio` groups** (log out/in or reboot after `usermod`):

```bash
sudo usermod -aG audio,gpio pi
```

If the WM8960 service exists, you can add `After=wm8960-soundcard.service` under `[Unit]` in `pir-motion-server.service` (see commented line in the file).
