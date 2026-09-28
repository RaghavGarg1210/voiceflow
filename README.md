# VoiceFlow 🎤

Lightweight, private, push-to-talk dictation for macOS — a local Whisper Flow.

**Hold the right Option key → speak → release.** Your words are transcribed on-device and pasted straight into whatever app has focus (Slack, Gmail, Google Docs, your editor...).

- **On-device transcription.** Audio is captured in memory and transcribed with [faster-whisper](https://github.com/SYSTRAN/faster-whisper) on your Mac. VoiceFlow does not upload recordings to a transcription service. Model downloads require internet access; a newly selected model may need another download.
- **No bloat.** The entire UI is a single menu-bar icon: 🎤 idle · 🔴 recording · ✍️ transcribing.
- **Settings and history stay in `~/.voiceflow/`** — `config.json` and `history.jsonl`. Downloaded models use the Hugging Face cache separately.

---

## 1. Install

Requires macOS and Python 3.10+ (check with `python3 --version`; `brew install python` if needed).

```bash
git clone https://github.com/RaghavGarg1210/voiceflow.git
cd voiceflow
chmod +x run.sh
./run.sh --check
```

The first run creates a virtualenv, installs dependencies, and checks the configured hotkey names and dependency imports. You should see `OK — config valid, dependencies importable.` This check does not download a model, open the microphone, verify macOS permissions, or validate every configuration value.

If a previous installation was interrupted, repair the environment with:

```bash
.venv/bin/python -m pip install -r requirements.txt
./run.sh --check
```

Then start the app:

```bash
./run.sh
```

On first launch, faster-whisper downloads the `base.en` model (~140 MB) to `~/.cache/huggingface/`. The menu-bar icon shows ⏳ while loading, then 🎤 when ready. Once the selected models are cached, transcription runs locally; changing models may require another download.

## 2. Grant permissions (one-time)

macOS gates the three capabilities VoiceFlow needs. Permissions are granted to the **app that launched Python** — so if you run `./run.sh` from Terminal, grant them to **Terminal**; from iTerm2, grant to iTerm2; from the VS Code integrated terminal, grant to Visual Studio Code (Terminal is recommended for predictability).

Open **System Settings → Privacy & Security**, then:

1. **Microphone** — lets VoiceFlow hear you.
   The first time you start a recording, macOS shows a prompt: click **Allow**. If you missed it: Privacy & Security → **Microphone** → toggle on Terminal.

2. **Accessibility** — lets VoiceFlow paste text into other apps (it synthesizes the Cmd+V keystroke).
   Privacy & Security → **Accessibility** → click **+**, add **Terminal** (`/System/Applications/Utilities/Terminal.app`), toggle it on.

3. **Input Monitoring** — lets VoiceFlow see your global hotkey even when other apps have focus.
   Privacy & Security → **Input Monitoring** → click **+**, add **Terminal**, toggle it on.

**Restart VoiceFlow (and Terminal) after granting** — macOS applies these to newly launched processes only. If the hotkey does nothing, Input Monitoring is missing; if recording works but nothing gets pasted, Accessibility is missing.

## 3. Use it

1. Click into any text field (Slack message, Gmail compose, a Google Doc...).
2. **Hold the right Option (⌥) key** and speak naturally.
3. **Release.** After a beat (✍️ in the menu bar), the punctuated text appears at your cursor.

The menu-bar dropdown shows status, your last transcript, and shortcuts to open the history file and config.

### Hindi → English

**Hold the *left* Option (⌥) key**, speak in Hindi (mixing in English words is fine), release — the **English translation** is pasted at your cursor. The menu bar shows 🟠 while recording in this mode.

This uses Whisper's built-in translate task, so it stays 100% local. The first time you use it, the multilingual `small` model (~460 MB) is downloaded and loaded — that first dictation takes noticeably longer; later translations avoid that initial download, but processing time still depends on your Mac and recording length. Note that keeping both models loaded uses more RAM (~1 GB total).

Disable it or tweak the key/model via the `translate` block in the config (below).

## 4. Configure

Edit `~/.voiceflow/config.json` (menu bar → **Open Config**), then restart the app.

| Setting | Default | Notes |
|---|---|---|
| `hotkey.mode` | `"hold"` | `"hold"` = push-to-talk; `"double_tap"` = tap twice to start, twice to stop |
| `hotkey.key` | `"alt_r"` | Right Option. Try `"ctrl_l"`, `"cmd_r"`, `"f19"`, or any single character |
| `hotkey.double_tap_interval` | `0.4` | Max seconds between taps in double-tap mode |
| `model` | `"base.en"` | `tiny.en` (fastest) · `base.en` (balanced) · `small.en` / `distil-small.en` (most accurate for the size). Multilingual: drop the `.en` and set `language` |
| `language` | `"en"` | Whisper language code, e.g. `"hi"`, `"es"` |
| `input_device` | `null` | System default mic. Run `./run.sh --list-devices` and set the device index to pick another |
| `output_mode` | `"paste"` | `"paste"` (Cmd+V — fast, handles long text) or `"type"` (per-keystroke; use if an app blocks paste) |
| `restore_clipboard` | `true` | Puts your previous clipboard *text* back ~0.6 s after pasting (images/rich content aren't preserved) |
| `save_history` | `true` | Set `false` to stop saving new transcripts; existing history is kept |
| `translate.enabled` | `true` | Set `false` to turn off the Hindi → English hotkey entirely |
| `translate.key` | `"alt_l"` | Left Option. Uses the same `hotkey.mode` (hold / double-tap) as the main key |
| `translate.model` | `"small"` | Must be a multilingual model (no `.en` suffix). `"medium"` translates better but is slower and ~1.5 GB |
| `translate.language` | `"hi"` | Source language. Set another Whisper code (e.g. `"es"`) to translate a different language to English |

**Example — double-tap Left Control instead of holding Option:**

```json
{
  "hotkey": {
    "mode": "double_tap",
    "key": "ctrl_l",
    "double_tap_interval": 0.4
  }
}
```

The example is a complete JSON file. Merge its `hotkey` block into your existing settings to keep other custom values. Missing settings use the defaults.

### Privacy and history

Audio stays in memory. Transcripts are saved as **plain text** in `~/.voiceflow/history.jsonl` by default. Set `"save_history": false` and restart to stop saving future transcripts; existing history remains until you delete it. The menu still shows the last transcript during the session.

Paste mode puts text on the system clipboard, then restores the previous clipboard text when enabled. It does not preserve images or rich formatting. Clipboard managers and the destination app may retain or sync pasted text under their own settings.

## 5. Optional: start at login

```bash
cat > ~/Library/LaunchAgents/com.local.voiceflow.plist <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.local.voiceflow</string>
  <key>ProgramArguments</key>
  <array><string>/bin/zsh</string><string>REPLACE_WITH_PATH/run.sh</string></array>
  <key>RunAtLoad</key><true/>
</dict></plist>
EOF
```

Replace `REPLACE_WITH_PATH` with this folder's absolute path, then `launchctl load ~/Library/LaunchAgents/com.local.voiceflow.plist`. (You may need to grant the permissions above to `zsh`/`Python` when launched this way; running from Terminal is simpler.)

## Troubleshooting

| Symptom | Fix |
|---|---|
| Hotkey does nothing | Grant **Input Monitoring** to your terminal app, restart both |
| 🔴 appears but no text is pasted | Grant **Accessibility**, restart both |
| ⚠️ with "Mic error" | Grant **Microphone**; check System Settings → Sound → Input and `./run.sh --list-devices`. After reconnecting a mic, try the hotkey again; restart after changing permissions or config. |
| Transcription is slow | Switch `model` to `"tiny.en"`, or keep `compute_type: "int8"` |
| Wrong words / accents | Upgrade `model` to `"small.en"` (one-time ~460 MB download) |
| Paste blocked by an app | Set `output_mode` to `"type"` |

## Development

Run the focused recorder tests after installing dependencies:

```bash
.venv/bin/python -m unittest discover -v
```

These tests simulate audio streams and cover failed startup, retry, and normal recording cleanup. They do not access your microphone, listen for keys, or download models.

For a manual smoke test, run `./run.sh --check`, start `./run.sh`, and dictate a short sentence into a scratch text field. Check both Option keys if translation is enabled. Microphone permissions, model loading, and pasting into another app require this manual check.
