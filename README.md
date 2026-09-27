# VoiceFlow 🎤

Lightweight, private, push-to-talk dictation for macOS — a local Whisper Flow.

**Hold the right Option key → speak → release.** Your words are transcribed on-device and pasted straight into whatever app has focus (Slack, Gmail, Google Docs, your editor...).

- **100% local.** Audio is captured in memory and transcribed with [faster-whisper](https://github.com/SYSTRAN/faster-whisper) on your Mac. Nothing is uploaded, ever. The only network access is a one-time model download on first launch.
- **No bloat.** The entire UI is a single menu-bar icon: 🎤 idle · 🔴 recording · ✍️ transcribing.
- **Everything stays in `~/.voiceflow/`** — settings (`config.json`) and transcript history (`history.jsonl`).

---

## 1. Install

Requires macOS and Python 3.10+ (check with `python3 --version`; `brew install python` if needed).

```bash
cd voiceflow
chmod +x run.sh
./run.sh --check
```

The first run creates a virtualenv, installs dependencies, and validates the setup. You should see `OK — config valid, dependencies importable.`

Then start the app:

```bash
./run.sh
```

On first launch, faster-whisper downloads the `base.en` model (~140 MB) to `~/.cache/huggingface/`. The menu-bar icon shows ⏳ while loading, then 🎤 when ready. Every launch after that is fully offline.

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
| `save_history` | `true` | Set `false` to keep no record at all |

**Example — double-tap Left Control instead of holding Option:**

```json
"hotkey": { "mode": "double_tap", "key": "ctrl_l", "double_tap_interval": 0.4 }
```

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
| ⚠️ with "Mic error" | Grant **Microphone**; check the mic works in System Settings → Sound → Input |
| Transcription is slow | Switch `model` to `"tiny.en"`, or keep `compute_type: "int8"` |
| Wrong words / accents | Upgrade `model` to `"small.en"` (one-time ~460 MB download) |
| Paste blocked by an app | Set `output_mode` to `"type"` |
