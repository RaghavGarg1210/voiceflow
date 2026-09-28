#!/usr/bin/env python3
"""
VoiceFlow — lightweight, private, push-to-talk dictation for macOS.

Hold a hotkey, speak, release: the transcript is pasted into whatever app
has keyboard focus (Slack, Gmail, Google Docs, your editor, ...).

Everything runs locally: audio is captured in memory, transcribed on-device
with faster-whisper, and history/settings live in ~/.voiceflow. No network
calls except the one-time Whisper model download on first run.
"""

import argparse
import datetime as dt
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
import rumps
import sounddevice as sd
from pynput import keyboard

APP_NAME = "VoiceFlow"
APP_DIR = Path.home() / ".voiceflow"
CONFIG_PATH = APP_DIR / "config.json"
HISTORY_PATH = APP_DIR / "history.jsonl"

DEFAULT_CONFIG = {
    "hotkey": {
        "mode": "hold",            # "hold" = push-to-talk, "double_tap" = tap twice to toggle
        "key": "alt_r",            # right Option. Others: "alt_l", "ctrl_l", "cmd_r", "f19", or a single char
        "double_tap_interval": 0.4  # seconds between taps (double_tap mode only)
    },
    "model": "base.en",            # tiny.en | base.en | small.en | distil-small.en | large-v3 ...
    "language": "en",
    "compute_type": "int8",        # int8 is fast on Apple Silicon CPUs
    "input_device": None,          # null = system default mic; see --list-devices
    "sample_rate": 16000,
    "output_mode": "paste",        # "paste" = Cmd+V (fast, reliable) | "type" = simulate keystrokes
    "restore_clipboard": True,     # put the previous clipboard text back after pasting
    "clipboard_restore_delay": 0.6,
    "min_duration_sec": 0.3,       # ignore accidental taps shorter than this
    "save_history": True,          # append transcripts to ~/.voiceflow/history.jsonl
    "trailing_space": True,        # append a space so consecutive dictations flow together
    "translate": {
        "enabled": True,
        "key": "alt_l",            # left Option — speak Hindi, get English pasted
        "model": "small",          # must be multilingual (no .en); downloaded on first use
        "language": "hi"           # source language hint; mixed-in English words are fine
    }
}

STATE_ICONS = {
    "loading": "⏳",
    "idle": "🎤",
    "recording": "🔴",
    "recording_translate": "🟠",
    "transcribing": "✍️",
    "error": "⚠️",
}


# --------------------------------------------------------------------------- config

def load_config() -> dict:
    APP_DIR.mkdir(mode=0o700, exist_ok=True)
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    if CONFIG_PATH.exists():
        try:
            user = json.loads(CONFIG_PATH.read_text())
        except json.JSONDecodeError as e:
            sys.exit(f"[{APP_NAME}] {CONFIG_PATH} is not valid JSON: {e}")
        for key, value in user.items():
            if key in ("hotkey", "translate") and isinstance(value, dict):
                cfg[key].update(value)
            else:
                cfg[key] = value
    else:
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2) + "\n")
    return cfg


def parse_key(name: str):
    """Turn a config string like 'alt_r' or 'x' into a pynput key object."""
    name = name.strip()
    if len(name) == 1:
        return keyboard.KeyCode.from_char(name.lower())
    try:
        return keyboard.Key[name]
    except KeyError:
        valid = ", ".join(k.name for k in keyboard.Key)
        sys.exit(f"[{APP_NAME}] Unknown hotkey '{name}'. Use a single character or one of: {valid}")


# --------------------------------------------------------------------------- audio

class Recorder:
    """Captures mono float32 audio from the mic into memory (never touches disk)."""

    def __init__(self, sample_rate: int, device):
        self.sample_rate = sample_rate
        self.device = device
        self._frames = []
        self._stream = None
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            if self._stream is not None:
                return
            self._frames = []
            stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                device=self.device,
                callback=self._callback,
            )
            try:
                stream.start()
            except Exception:
                # A failed stream must not block the next recording attempt.
                try:
                    stream.close()
                except Exception:
                    pass  # keep the original microphone error
                self._frames = []
                raise
            self._stream = stream

    def _callback(self, indata, frames, time_info, status):
        self._frames.append(indata.copy())

    def stop(self) -> np.ndarray:
        with self._lock:
            if self._stream is None:
                return np.zeros(0, dtype=np.float32)
            self._stream.stop()
            self._stream.close()
            self._stream = None
            if not self._frames:
                return np.zeros(0, dtype=np.float32)
            audio = np.concatenate(self._frames)[:, 0]
            self._frames = []
            return audio


# --------------------------------------------------------------------------- transcription

class Transcriber:
    """Local Whisper via faster-whisper (CTranslate2). Loaded once, reused."""

    def __init__(self, model_name: str, compute_type: str):
        self.model_name = model_name
        self.compute_type = compute_type
        self._model = None
        self.ready = threading.Event()
        self.load_error = None
        self._load_started = False

    def load_async(self):
        if self._load_started:
            return
        self._load_started = True
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        try:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(
                self.model_name,
                device="cpu",
                compute_type=self.compute_type,
            )
        except Exception as e:  # surface load failures in the menu bar
            self.load_error = str(e)
        finally:
            self.ready.set()

    def transcribe(self, audio: np.ndarray, language: str, task: str = "transcribe") -> str:
        segments, _info = self._model.transcribe(
            audio,
            language=language,
            task=task,
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        return " ".join(seg.text.strip() for seg in segments)


def clean_text(text: str) -> str:
    """Whisper already punctuates; just normalize whitespace and casing."""
    text = " ".join(text.split()).strip()
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text


# --------------------------------------------------------------------------- output

def _pbcopy(data: bytes):
    subprocess.run(["pbcopy"], input=data, check=False)


def _pbpaste() -> bytes:
    return subprocess.run(["pbpaste"], capture_output=True, check=False).stdout


def insert_text(text: str, cfg: dict):
    """Deliver the transcript into the currently focused text field."""
    kb = keyboard.Controller()
    if cfg["output_mode"] == "type":
        kb.type(text)
        return
    previous = _pbpaste() if cfg["restore_clipboard"] else None
    _pbcopy(text.encode("utf-8"))
    time.sleep(0.05)  # let the pasteboard settle before the keystroke
    with kb.pressed(keyboard.Key.cmd):
        kb.press("v")
        kb.release("v")
    if previous is not None:
        time.sleep(cfg["clipboard_restore_delay"])
        _pbcopy(previous)


def save_history(text: str, mode: str = "dictate"):
    entry = {"ts": dt.datetime.now().isoformat(timespec="seconds"), "text": text}
    if mode != "dictate":
        entry["mode"] = mode
    with HISTORY_PATH.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- engine

class Engine:
    """Ties hotkey -> record -> transcribe -> paste together."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.recorder = Recorder(cfg["sample_rate"], cfg["input_device"])
        self.transcriber = Transcriber(cfg["model"], cfg["compute_type"])
        # Hindi -> English model is heavier; created here but only loaded on first use
        self.translator = (
            Transcriber(cfg["translate"]["model"], cfg["compute_type"])
            if cfg["translate"]["enabled"]
            else None
        )
        self.state = "loading"
        self.last_text = ""
        self._recording = False
        self._active_mode = "dictate"

    def start(self):
        self.transcriber.load_async()
        threading.Thread(target=self._mark_ready, daemon=True).start()
        self._start_hotkey_listener()

    def _mark_ready(self):
        self.transcriber.ready.wait()
        if self.transcriber.load_error:
            self.state = "error"
            self.last_text = f"Model failed to load: {self.transcriber.load_error}"
        elif self.state == "loading":
            self.state = "idle"

    # -- hotkey handling

    def _start_hotkey_listener(self):
        hk = self.cfg["hotkey"]
        self._keys = {"dictate": parse_key(hk["key"])}
        if self.translator is not None:
            self._keys["translate"] = parse_key(self.cfg["translate"]["key"])
        self._tap_interval = float(hk.get("double_tap_interval", 0.4))
        self._last_tap = {mode: 0.0 for mode in self._keys}
        if hk["mode"] == "double_tap":
            listener = keyboard.Listener(on_press=self._on_press_double_tap)
        else:
            listener = keyboard.Listener(
                on_press=self._on_press_hold, on_release=self._on_release_hold
            )
        listener.daemon = True
        listener.start()

    @staticmethod
    def _matches(key, target) -> bool:
        if key == target:
            return True
        # character keys arrive as KeyCode; compare canonical char
        return (
            isinstance(key, keyboard.KeyCode)
            and isinstance(target, keyboard.KeyCode)
            and key.char is not None
            and key.char.lower() == target.char
        )

    def _mode_for(self, key):
        for mode, target in self._keys.items():
            if self._matches(key, target):
                return mode
        return None

    def _on_press_hold(self, key):
        mode = self._mode_for(key)
        if mode is not None and not self._recording:
            self._begin(mode)

    def _on_release_hold(self, key):
        # only the key that started the recording may stop it
        if self._recording and self._mode_for(key) == self._active_mode:
            self._finish()

    def _on_press_double_tap(self, key):
        mode = self._mode_for(key)
        if mode is None:
            return
        if self._recording and mode != self._active_mode:
            return
        now = time.monotonic()
        if now - self._last_tap[mode] <= self._tap_interval:
            self._last_tap[mode] = 0.0
            if self._recording:
                self._finish()
            else:
                self._begin(mode)
        else:
            self._last_tap[mode] = now

    # -- record / process

    def _begin(self, mode: str):
        if self.state == "transcribing":
            return
        if mode == "translate":
            # lazy-load so the (large) multilingual model never delays startup;
            # kicking it off here lets loading overlap with the user speaking
            self.translator.load_async()
        try:
            self.recorder.start()
        except Exception as e:
            self.state = "error"
            self.last_text = f"Mic error: {e} (check Microphone permission)"
            return
        self._active_mode = mode
        self._recording = True
        self.state = "recording" if mode == "dictate" else "recording_translate"

    def _finish(self):
        self._recording = False
        audio = self.recorder.stop()
        self.state = "transcribing"
        threading.Thread(
            target=self._process, args=(audio, self._active_mode), daemon=True
        ).start()

    def _process(self, audio: np.ndarray, mode: str):
        try:
            duration = len(audio) / self.cfg["sample_rate"]
            if duration < self.cfg["min_duration_sec"] or np.abs(audio).max() < 1e-4:
                return  # accidental tap or silence
            if mode == "translate":
                transcriber = self.translator
                language, task = self.cfg["translate"]["language"], "translate"
                if not transcriber.ready.is_set():
                    self.last_text = "Loading translation model… (first use downloads it)"
            else:
                transcriber = self.transcriber
                language, task = self.cfg["language"], "transcribe"
            transcriber.ready.wait(timeout=600)
            if transcriber.load_error:
                self.state = "error"
                self.last_text = f"Model failed to load: {transcriber.load_error}"
                return
            if not transcriber.ready.is_set():
                return
            text = clean_text(transcriber.transcribe(audio, language, task))
            if not text:
                return
            if self.cfg["trailing_space"]:
                text += " "
            insert_text(text, self.cfg)
            self.last_text = text.strip()
            if self.cfg["save_history"]:
                save_history(text.strip(), mode)
        except Exception as e:
            self.state = "error"
            self.last_text = f"Error: {e}"
            return
        finally:
            if self.state != "error":
                self.state = "idle"


# --------------------------------------------------------------------------- menu bar UI

class VoiceFlowApp(rumps.App):
    def __init__(self, engine: Engine, cfg: dict):
        super().__init__(STATE_ICONS["loading"], quit_button="Quit VoiceFlow")
        self.engine = engine
        hk = cfg["hotkey"]
        trigger = (
            f"hold {hk['key']}" if hk["mode"] == "hold" else f"double-tap {hk['key']}"
        )
        self.status_item = rumps.MenuItem(f"Loading {cfg['model']} model…")
        self.last_item = rumps.MenuItem("Last: —")
        trigger_items = [rumps.MenuItem(f"Trigger: {trigger}")]
        if cfg["translate"]["enabled"]:
            tk = cfg["translate"]["key"]
            t_trigger = f"hold {tk}" if hk["mode"] == "hold" else f"double-tap {tk}"
            trigger_items.append(rumps.MenuItem(f"Hindi → English: {t_trigger}"))
        self.menu = [
            self.status_item,
            self.last_item,
            None,
            *trigger_items,
            rumps.MenuItem("Open History", callback=self._open_history),
            rumps.MenuItem("Open Config", callback=self._open_config),
            None,
        ]
        rumps.Timer(self._tick, 0.15).start()

    def _tick(self, _timer):
        state = self.engine.state
        self.title = STATE_ICONS.get(state, "🎤")
        labels = {
            "loading": "Loading model…",
            "idle": "Ready — press your hotkey to dictate",
            "recording": "Recording… (release / tap to stop)",
            "recording_translate": "Recording Hindi… (release / tap to stop)",
            "transcribing": "Transcribing…",
            "error": "Error — see below",
        }
        self.status_item.title = labels.get(state, state)
        if self.engine.last_text:
            preview = self.engine.last_text
            if len(preview) > 60:
                preview = preview[:57] + "…"
            self.last_item.title = f"Last: {preview}"

    def _open_history(self, _):
        HISTORY_PATH.touch(exist_ok=True)
        subprocess.run(["open", str(HISTORY_PATH)], check=False)

    def _open_config(self, _):
        subprocess.run(["open", str(CONFIG_PATH)], check=False)


# --------------------------------------------------------------------------- entry point

def main():
    parser = argparse.ArgumentParser(description="VoiceFlow — local push-to-talk dictation")
    parser.add_argument("--list-devices", action="store_true", help="list audio input devices and exit")
    parser.add_argument("--check", action="store_true", help="validate config and dependencies, then exit")
    args = parser.parse_args()

    if args.list_devices:
        print(sd.query_devices())
        return

    cfg = load_config()

    if args.check:
        parse_key(cfg["hotkey"]["key"])
        if cfg["translate"]["enabled"]:
            parse_key(cfg["translate"]["key"])
        import faster_whisper  # noqa: F401
        print(f"[{APP_NAME}] OK — config valid, dependencies importable.")
        print(f"  config:  {CONFIG_PATH}")
        print(f"  hotkey:  {cfg['hotkey']['mode']} {cfg['hotkey']['key']}")
        print(f"  model:   {cfg['model']} ({cfg['compute_type']})")
        if cfg["translate"]["enabled"]:
            print(
                f"  translate: {cfg['hotkey']['mode']} {cfg['translate']['key']} — "
                f"{cfg['translate']['language']} → en via {cfg['translate']['model']}"
            )
        return

    if sys.platform != "darwin":
        sys.exit(f"[{APP_NAME}] This build targets macOS (uses rumps + pbcopy + Cmd+V).")

    engine = Engine(cfg)
    engine.start()
    VoiceFlowApp(engine, cfg).run()


if __name__ == "__main__":
    main()
