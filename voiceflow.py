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
