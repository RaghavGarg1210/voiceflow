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
    "trailing_space": True         # append a space so consecutive dictations flow together
}

STATE_ICONS = {
    "loading": "⏳",
    "idle": "🎤",
    "recording": "🔴",
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
            if key == "hotkey" and isinstance(value, dict):
                cfg["hotkey"].update(value)
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
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                device=self.device,
                callback=self._callback,
            )
            self._stream.start()

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

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._model = None
        self.ready = threading.Event()
        self.load_error = None

    def load_async(self):
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        try:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(
                self.cfg["model"],
                device="cpu",
                compute_type=self.cfg["compute_type"],
            )
        except Exception as e:  # surface load failures in the menu bar
            self.load_error = str(e)
        finally:
            self.ready.set()

    def transcribe(self, audio: np.ndarray) -> str:
        segments, _info = self._model.transcribe(
            audio,
            language=self.cfg["language"],
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
