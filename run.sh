#!/usr/bin/env bash
# Starts the backend (FastAPI) and frontend (Vite) together.
# Usage: ./run.sh   then open http://localhost:5173
set -e
cd "$(dirname "$0")"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

# --- backend ---
cd backend
if [ ! -d .venv ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install -q -r requirements.txt
fi
./.venv/bin/uvicorn main:app --host 127.0.0.1 --port "$BACKEND_PORT" --reload &
BACK=$!
cd ..

# --- frontend ---
cd frontend
[ -d node_modules ] || npm install
VITE_API_TARGET="http://127.0.0.1:$BACKEND_PORT" npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT" &
FRONT=$!
cd ..

echo ""
echo "  ▶ Open  http://127.0.0.1:$FRONTEND_PORT"
echo "  (backend on :$BACKEND_PORT)  — Ctrl-C to stop both"
trap "kill $BACK $FRONT 2>/dev/null" EXIT
wait
