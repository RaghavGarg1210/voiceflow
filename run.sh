#!/bin/zsh
# Launch VoiceFlow from its virtualenv.
set -e
DIR="${0:A:h}"
if [ ! -d "$DIR/.venv" ]; then
  echo "First run: creating virtualenv and installing dependencies..."
  python3 -m venv "$DIR/.venv"
  "$DIR/.venv/bin/pip" install --upgrade pip -q
  "$DIR/.venv/bin/pip" install -r "$DIR/requirements.txt"
fi
exec "$DIR/.venv/bin/python" "$DIR/voiceflow.py" "$@"
