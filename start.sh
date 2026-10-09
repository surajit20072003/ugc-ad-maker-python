#!/bin/bash
# ─── start.sh ─────────────────────────────────────────────────────────────────
# Run UGC Ad Maker with the correct Python (pyenv 3.11)
# Usage: ./start.sh [port]
# Default port: 8000

PORT=${1:-8765}
PYTHON=~/.pyenv/versions/3.11.0/bin/python

echo "🎬 Starting UGC Ad Maker on port $PORT..."
echo "   Python: $PYTHON"
echo "   Open: http://localhost:$PORT"
echo ""

$PYTHON -m uvicorn main:app --host 0.0.0.0 --port "$PORT" --reload
