# 🌳 Knowledge Tree

Paste links to articles, YouTube videos, and courses you've completed. Each
source is scraped, an LLM (or a built-in keyword fallback) extracts the key
topics, and they're **merged** into a living, force-directed graph of your
knowledge — reinforced topics glow brighter and grow larger over time.

Runs 100% locally. No accounts, no cloud required.

## Quick start

```bash
./run.sh
```

Then open **http://localhost:5173**. That's it — it works immediately in
"Keyword mode" with zero extra setup.

## Better topic extraction (optional)

The app auto-detects the best available engine, in this order:

| Engine | How to enable |
|--------|---------------|
| **Claude** (best) | `cp backend/.env.example backend/.env`, paste your `ANTHROPIC_API_KEY`, restart |
| **OpenAI**  | `export OPENAI_API_KEY=sk-...` before `./run.sh` |
| **Ollama** (fully local) | `ollama serve` + `ollama pull llama3.1:8b nomic-embed-text` |
| **Keyword mode** | nothing — always works |

Claude uses the official `anthropic` SDK with the `claude-opus-4-8` model and
structured JSON output. Set `ANTHROPIC_MODEL=claude-haiku-4-5` in `.env` for a
cheaper/faster option.

Ollama also enables **embedding-based merging** (semantically identical topics
from different sources collapse into one node). Without it, merging falls back
to name matching, which still works well.

The current engine is shown at the bottom of the sidebar.

## Architecture

```
frontend (Vite + React + react-force-graph-2d)  →  /api  →  backend (FastAPI)
                                                             ├─ extract.py    scrape URL → text
                                                             ├─ llm.py        text → topic hierarchy
                                                             └─ graph_store.py merge into graph.json
```

- Data lives in `backend/graph.json`. Delete it to start fresh.
- Two endpoints: `GET /api/graph`, `POST /api/add {url}`.

## Manual start (two terminals)

```bash
# terminal 1
cd backend && python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/uvicorn main:app --port 8000 --reload

# terminal 2
cd frontend && npm install && npm run dev
```
