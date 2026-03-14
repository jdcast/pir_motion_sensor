from __future__ import annotations  # Python 3.7+ (for Pi Zero / older RPi OS)

from flask import Flask, request
import asyncio
import json
import logging
import os
import random
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger(__name__)
# Suppress noisy HTTP request/retry logs from OpenAI and httpx
for name in ("openai", "httpx", "httpcore"):
    logging.getLogger(name).setLevel(logging.WARNING)

app = Flask(__name__)
last = 0.0
COOLDOWN = 3

# Only one phrase plays at a time; consecutive calls wait for current playback to finish
_playback_lock = threading.Lock()

# Fallback when no LLM is available
TROOPER_PHRASES = [
    "Move along.",
    "Halt!",
    "Stop right there.",
    "Identify yourself.",
    "Nothing to see here.",
    "Move it!",
]

TROOPER_PROMPT = """You are a Star Wars storm trooper. A motion sensor just detected someone nearby. Reply with exactly one short line (under 12 words) that a storm trooper would say—authoritative, slightly funny, generally dark, foreful, a bit robotic. Output only that line, no quotes or explanation."""

# AI voice options (first available wins when key/setup present):
# - OpenAI TTS: set OPENAI_API_KEY — paid, very natural (voice "onyx" = deep male)
# - Edge TTS: no key — free Microsoft neural (ChristopherNeural = male)
EDGE_VOICE = "en-US-ChristopherNeural"  # or "en-US-GuyNeural", "en-GB-RyanNeural"
EDGE_RATE = "-8%"   # slightly slower for trooper
OPENAI_TTS_VOICE = "onyx"   # alloy, echo, onyx, fable, etc.; onyx = deep male
OPENAI_TTS_MODEL = "tts-1-hd"  # or "tts-1" (faster/cheaper)

# Fallback espeak: lower pitch, slower
ESPEAK_PITCH = 35
ESPEAK_SPEED = 115
ESPEAK_AMP = 95
SOX_BANDPASS = "400-2600"

# Silence at start so the first syllable isn't cut off (sound device / PulseAudio wake-up)
LEAD_SILENCE_SEC = 1.0

# Folder of pre-recorded trooper sounds; play one when POST /motion has "play_sound": true or "play_sound": "file.wav"
# Override with env TROOPER_SOUNDS_DIR if the server is run from a different cwd (e.g. python3 ~/Downloads/motion_server.py)
TROOPER_SOUNDS_DIR = os.environ.get("TROOPER_SOUNDS_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "trooper_sounds")
TROOPER_SOUND_EXTENSIONS = (".mp3", ".wav", ".oga", ".flac", ".m4a")


def _safe_sound_path(filename: str) -> str | None:
    """Return path to a file in TROOPER_SOUNDS_DIR if filename is a safe basename, else None."""
    base = os.path.basename(filename)
    if not base or base != filename:
        return None
    path = os.path.join(TROOPER_SOUNDS_DIR, base)
    try:
        real_dir = os.path.realpath(TROOPER_SOUNDS_DIR)
        real_path = os.path.realpath(path)
        if os.path.commonpath((real_dir, real_path)) != real_dir:
            return None
        return path if os.path.isfile(path) else None
    except OSError:
        return None


def _list_trooper_sounds() -> list[str]:
    """Return list of full paths to audio files in TROOPER_SOUNDS_DIR."""
    if not os.path.isdir(TROOPER_SOUNDS_DIR):
        return []
    out = []
    for name in os.listdir(TROOPER_SOUNDS_DIR):
        if name.startswith("."):
            continue
        if any(name.lower().endswith(ext) for ext in TROOPER_SOUND_EXTENSIONS):
            out.append(os.path.join(TROOPER_SOUNDS_DIR, name))
    return out


def play_trooper_sound(choice: bool | str = True) -> bool:
    """Play a sound from trooper_sounds. choice=True = random file, choice='file.wav' = that file. Returns True if played."""
    with _playback_lock:
        if choice is True:
            files = _list_trooper_sounds()
            if not files:
                log.warning("play_sound=true but trooper_sounds is empty or missing (looked in %s). Set TROOPER_SOUNDS_DIR or run from project dir.", TROOPER_SOUNDS_DIR)
                return False
            path = random.choice(files)
            log.info("voice=trooper_sounds (random): %s", os.path.basename(path))
        else:
            path = _safe_sound_path(choice)
            if not path:
                log.warning("play_sound file not allowed or missing: %s", choice)
                return False
            log.info("voice=trooper_sounds: %s", os.path.basename(path))
        # Pre-recorded files: play as-is (no sox lead silence; avoids "open(): No such file or directory")
        _play_file_and_wait(path, lead_silence_sec=0)
        return True


def _ollama_generate(prompt: str, model: str = "llama3.2", timeout: float = 8.0) -> str | None:
    """Generate one short line via local Ollama. Returns None on failure."""
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=json.dumps({"model": model, "prompt": prompt, "stream": False}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out = json.loads(resp.read().decode())
        text = (out.get("response") or "").strip()
        # Take first line and trim length
        text = text.split("\n")[0].strip()
        text = re.sub(r"\s+", " ", text)[:120]
        return text if text else None
    except Exception:
        return None


def _openai_generate(prompt: str, timeout: float = 10.0) -> str | None:
    """Generate one short line via OpenAI API. Uses OPENAI_API_KEY env. Returns None on failure."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, max_retries=0)
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=40,
            timeout=timeout,
        )
        text = (r.choices[0].message.content or "").strip()
        text = text.split("\n")[0].strip()
        text = re.sub(r"\s+", " ", text)[:120]
        return text if text else None
    except Exception:
        return None


def generate_trooper_line() -> str:
    """Return one storm trooper line: Ollama first (local, no rate limits), then OpenAI, else fallback list."""
    text = _ollama_generate(TROOPER_PROMPT)
    if text:
        log.info("line_source=ollama")
        return text
    text = _openai_generate(TROOPER_PROMPT)
    if text:
        log.info("line_source=openai")
        return text
    log.info("line_source=fallback")
    return random.choice(TROOPER_PHRASES)


def _openai_tts_to_file(text: str, path: str) -> bool:
    """Generate speech with OpenAI TTS into path (mp3). Returns True on success."""
    if not os.environ.get("OPENAI_API_KEY"):
        return False
    try:
        from openai import OpenAI
        client = OpenAI(max_retries=0)
        with open(path, "wb") as f:
            response = client.audio.speech.create(
                model=OPENAI_TTS_MODEL,
                voice=OPENAI_TTS_VOICE,
                input=text,
            )
            f.write(response.content)
        return True
    except Exception:
        return False


def _play_and_wait(cmd, stdin=None, input_bytes=None):
    """Run a play command and block until it finishes (so we don't overlap phrases)."""
    if input_bytes is not None:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        proc.communicate(input=input_bytes)
    elif stdin is not None:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        proc.communicate(input=stdin)
    else:
        subprocess.run(cmd, check=True)


def _play_file_and_wait(path: str, lead_silence_sec: float = 0) -> bool:
    """Play an audio file and wait until done. Prepends lead_silence_sec of silence
    when possible (sox for .wav, ffmpeg for .mp3) so the first syllable isn't cut off.
    Set AUDIO_DEVICE (e.g. plughw:0,0) to force ALSA output (e.g. Pi WM8960 HAT)."""
    alsa_device = os.environ.get("AUDIO_DEVICE")
    aplay = shutil.which("aplay")
    ffmpeg = shutil.which("ffmpeg")
    if alsa_device and aplay and ffmpeg:
        try:
            path_lower = path.lower()
            # WM8960 and many HATs need specific format; normalize to 48kHz stereo S16 via ffmpeg
            proc = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-f", "s16le", "-ar", "48000", "-ac", "2", "-"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["aplay", "-q", "-D", alsa_device, "-f", "S16_LE", "-r", "48000", "-c", "2", "-"],
                input=proc.stdout,
                check=True,
            )
            return True
        except subprocess.CalledProcessError as e:
            err = (e.stderr.decode().strip() if e.stderr else None) or str(e)
            log.warning("ALSA playback failed (device=%s): %s", alsa_device, err)
        except FileNotFoundError:
            pass

    sox = shutil.which("sox")
    paplay = shutil.which("paplay")
    ffplay = shutil.which("ffplay")
    path_lower = path.lower()

    # MP3: use ffmpeg to prepend silence (sox often can't read mp3)
    if lead_silence_sec > 0 and ffmpeg and path_lower.endswith(".mp3"):
        try:
            fd, padded_path = tempfile.mkstemp(suffix=".mp3", prefix="trooper_pad_")
            os.close(fd)
            subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono:d={lead_silence_sec}",
                    "-i", path,
                    "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1[a]", "-map", "[a]",
                    padded_path,
                ],
                check=True,
                capture_output=True,
            )
            try:
                if ffplay:
                    subprocess.run(
                        [ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", padded_path],
                        check=True,
                    )
                elif paplay:
                    subprocess.run([paplay, padded_path], check=True)
                else:
                    raise FileNotFoundError
            finally:
                try:
                    os.unlink(padded_path)
                except OSError:
                    pass
            return True
        except (subprocess.CalledProcessError, OSError, FileNotFoundError):
            pass

    # WAV: use sox to prepend silence
    use_sox_pad = lead_silence_sec > 0 and sox and path_lower.endswith(".wav")
    if use_sox_pad:
        try:
            if paplay:
                result = subprocess.run(
                    ["sox", path, "-t", "wav", "-", "pad", str(lead_silence_sec), "0"],
                    check=True,
                    capture_output=True,
                )
                proc = subprocess.Popen(["paplay", "-"], stdin=subprocess.PIPE)
                proc.communicate(input=result.stdout)
                return True
            if ffplay:
                fd, padded_path = tempfile.mkstemp(suffix=".wav", prefix="trooper_pad_")
                os.close(fd)
                subprocess.run(
                    ["sox", path, padded_path, "pad", str(lead_silence_sec), "0"],
                    check=True,
                    capture_output=True,
                )
                try:
                    subprocess.run(
                        [ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", padded_path],
                        check=True,
                    )
                finally:
                    try:
                        os.unlink(padded_path)
                    except OSError:
                        pass
                return True
        except (subprocess.CalledProcessError, OSError):
            pass

    if ffplay:
        subprocess.run(
            [ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", path],
            check=True,
        )
        return True
    if paplay:
        subprocess.run([paplay, path], check=True)
        return True
    return False


def speak_trooper():
    """Speak an AI-generated storm trooper line. Voice: OpenAI TTS (if key set) else Edge TTS else espeak. Serialized so phrases never overlap."""
    text = generate_trooper_line()
    log.info("Trooper says: %s", text)
    with _playback_lock:
        # 1) OpenAI TTS (AI voice service; same OPENAI_API_KEY as line generation)
        fd, mp3_path = tempfile.mkstemp(suffix=".mp3", prefix="trooper_")
        os.close(fd)
        try:
            if _openai_tts_to_file(text, mp3_path):
                log.info("voice=openai_tts")
                try:
                    _play_file_and_wait(mp3_path, lead_silence_sec=LEAD_SILENCE_SEC)
                finally:
                    try:
                        os.unlink(mp3_path)
                    except OSError:
                        pass
                return
        finally:
            try:
                os.unlink(mp3_path)
            except OSError:
                pass

        # 2) Edge TTS (free Microsoft neural voice)
        try:
            import edge_tts
            fd2, mp3_path = tempfile.mkstemp(suffix=".mp3", prefix="trooper_")
            os.close(fd2)
            log.info("voice=edge_tts")
            async def _generate():
                communicate = edge_tts.Communicate(text, EDGE_VOICE, rate=EDGE_RATE)
                await communicate.save(mp3_path)
            asyncio.run(_generate())
            try:
                _play_file_and_wait(mp3_path, lead_silence_sec=LEAD_SILENCE_SEC)
            finally:
                try:
                    os.unlink(mp3_path)
                except OSError:
                    pass
            return
        except Exception:
            pass

        # 3) espeak + sox bandpass (helmet comm)
        espeak = shutil.which("espeak")
        sox = shutil.which("sox")
        paplay = shutil.which("paplay")
        if espeak and sox and paplay:
            try:
                log.info("voice=espeak_sox")
                fd, wav_path = tempfile.mkstemp(suffix=".wav", prefix="trooper_")
                os.close(fd)
                subprocess.run(
                    [
                        "espeak", "-w", wav_path,
                        "-p", str(ESPEAK_PITCH), "-s", str(ESPEAK_SPEED), "-a", str(ESPEAK_AMP),
                        text,
                    ],
                    check=True,
                    capture_output=True,
                )
                filtered = subprocess.run(
                    [
                        "sox", wav_path, "-t", "wav", "-",
                        "pad", str(LEAD_SILENCE_SEC), "0",
                        "sinc", SOX_BANDPASS,
                    ],
                    check=True,
                    capture_output=True,
                )
                os.unlink(wav_path)
                _play_and_wait(["paplay", "-"], input_bytes=filtered.stdout)
                return
            except (subprocess.CalledProcessError, OSError):
                pass

        # 4) espeak only
        if espeak:
            log.info("voice=espeak")
            proc = subprocess.Popen([
                "espeak",
                "-p", str(ESPEAK_PITCH), "-s", str(ESPEAK_SPEED), "-a", str(ESPEAK_AMP),
                text,
            ])
            proc.wait()
            return

        # 5) spd-say
        spd = shutil.which("spd-say")
        if spd:
            log.info("voice=spd_say")
            proc = subprocess.Popen(["spd-say", "-r", "-25", "-p", "-15", text])
            proc.wait()
            return

        if paplay:
            log.info("voice=beep (no TTS)")
            _play_file_and_wait("/usr/share/sounds/freedesktop/stereo/complete.oga")
            return

    log.warning("voice=none (no TTS installed). Would say: %s", text)


@app.post("/motion")
def motion():
    global last
    body = request.get_json(silent=True) or {}
    now = time.time()
    if now - last < COOLDOWN:
        log.info("motion ignored (cooldown)")
        return {"ok": True, "ignored": "cooldown"}, 200
    last = now
    log.info("MOTION: %s", body)

    play_sound = body.get("play_sound")
    if play_sound is True:
        if play_trooper_sound(True):
            return {"ok": True}, 200
        # fall through to TTS if no files in trooper_sounds
    elif isinstance(play_sound, str) and play_sound:
        if play_trooper_sound(play_sound):
            return {"ok": True}, 200
        return {"ok": False, "error": "sound not found"}, 404

    speak_trooper()
    return {"ok": True}, 200


app.run(host="0.0.0.0", port=5000)