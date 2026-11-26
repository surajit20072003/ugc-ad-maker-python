#!/bin/bash
# ─── start.sh ─────────────────────────────────────────────────────────────────
# Run UGC Ad Maker with the correct Python (pyenv 3.11)
# Usage: ./start.sh [port]
# Default port: 8765

PORT=${1:-8765}
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
# Use the project's virtual environment if there is one, else the pyenv Python of the original server, else python3
if   [ -x "$DIR/venv/bin/python" ];  then PYTHON="$DIR/venv/bin/python"
elif [ -x "$DIR/.venv/bin/python" ]; then PYTHON="$DIR/.venv/bin/python"
elif [ -x "$HOME/.pyenv/versions/3.11.0/bin/python" ]; then PYTHON="$HOME/.pyenv/versions/3.11.0/bin/python"
else PYTHON="$(command -v python3)"; fi

echo "🎬 Starting UGC Ad Maker on port $PORT..."
echo "   Python: $PYTHON"
echo "   Open: http://localhost:$PORT"
echo ""

$PYTHON -m uvicorn main:app --host 0.0.0.0 --port "$PORT" --reload
