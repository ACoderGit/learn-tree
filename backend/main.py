"""FastAPI app: two endpoints and static hosting of the built frontend."""
import os


def _load_dotenv() -> None:
    """Load backend/.env into the environment (KEY=value lines) if present.

    Keeps secrets like ANTHROPIC_API_KEY out of the shell history and code.
    Existing environment variables always win.
    """
    path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


_load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import extract as extractor
import graph_store
import llm

app = FastAPI(title="Knowledge Tree")

# Only the local dev frontend may call the API from a browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cap links processed per request so a fat-fingered paste can't run up spend.
MAX_URLS_PER_REQUEST = 20


class AddRequest(BaseModel):
    url: str


class RecommendRequest(BaseModel):
    mode: str = "niche_down"
    nodeIds: list[str] = []
    interest: str = ""
    format: str = "mixed"
    timeBudget: str = "1-2 hours"


class TimeSkipRequest(BaseModel):
    days: float = 7


class PlaneRequest(BaseModel):
    name: str


@app.get("/api/status")
def status():
    return {"provider": llm.active_provider()}


@app.get("/api/graph")
def get_graph():
    return graph_store.public(graph_store.prune_empty_domains())


@app.get("/api/planes")
def planes():
    return graph_store.list_planes()


@app.post("/api/plane/create")
def plane_create(req: PlaneRequest):
    return graph_store.public(graph_store.create_plane(req.name))


@app.post("/api/plane/select")
def plane_select(req: PlaneRequest):
    return graph_store.public(graph_store.switch_plane(req.name))


@app.post("/api/plane/delete")
def plane_delete(req: PlaneRequest):
    return graph_store.public(graph_store.delete_plane(req.name))


@app.post("/api/add")
def add(req: AddRequest):
    urls = [u.strip() for u in req.url.splitlines() if u.strip()]
    if not urls:
        return JSONResponse({"error": "No URL provided"}, status_code=400)
    if len(urls) > MAX_URLS_PER_REQUEST:
        return JSONResponse(
            {"error": f"Too many links at once (max {MAX_URLS_PER_REQUEST})."},
            status_code=400,
        )

    added, provider = [], "heuristic"
    for url in urls:
        cached = graph_store.cached_source(url)
        if cached and extractor.is_youtube_url(url) and cached.get("provider") != "demo":
            cached = None
        if cached:
            nodes = cached["nodes"]
            reinforces = cached.get("reinforces", [])
            provider = cached.get("provider", "cache")
            content = {"url": cached["url"], "title": cached.get("title", cached["url"])}
        else:
            content = extractor.extract(url)
            nodes, reinforces, provider = llm.extract_topics_with_context(
                content["text"],
                content["title"],
                graph_store.hierarchy_context(),
            )
            graph_store.remember_source(
                content["url"],
                content["title"],
                nodes,
                reinforces,
                provider,
            )
        graph = graph_store.merge(nodes, reinforces, content["url"])
        added.append({"url": content["url"], "title": content["title"],
                      "topics": len(nodes), "reinforced": len(reinforces)})

    return {
        "graph": graph_store.public(graph),
        "added": added,
        "provider": provider,
    }


class NodeAdd(BaseModel):
    label: str
    level: int = 0
    parentId: str | None = None


class NodeRename(BaseModel):
    id: str
    label: str


class NodeLevel(BaseModel):
    id: str
    level: int


class NodeId(BaseModel):
    id: str


@app.post("/api/clear")
def clear_graph():
    return graph_store.public(graph_store.clear())


@app.post("/api/demo/load")
def load_demo():
    try:
        return graph_store.public(graph_store.load_demo_sources())
    except Exception as exc:
        return JSONResponse(
            {"error": f"Could not load demo data: {type(exc).__name__}: {exc}"},
            status_code=500,
        )


@app.post("/api/node/add")
def node_add(req: NodeAdd):
    return graph_store.public(graph_store.add_node(req.label, req.level, req.parentId))


@app.post("/api/node/rename")
def node_rename(req: NodeRename):
    return graph_store.public(graph_store.rename_node(req.id, req.label))


@app.post("/api/node/delete")
def node_delete(req: NodeId):
    return graph_store.public(graph_store.delete_node(req.id))


@app.post("/api/node/level")
def node_level(req: NodeLevel):
    return graph_store.public(graph_store.set_node_level(req.id, req.level))


@app.post("/api/recommend")
def recommend(req: RecommendRequest):
    graph = graph_store.load()
    if not graph["nodes"]:
        return JSONResponse({"error": "Add some topics first."}, status_code=400)
    recs = llm.recommend(graph["nodes"], req.dict())
    if not recs:
        return JSONResponse(
            {"error": "Recommendations need the Claude engine (check your API key)."},
            status_code=400,
        )
    return recs


@app.post("/api/node/review")
def node_review(req: NodeId):
    return graph_store.public(graph_store.review_node(req.id))


@app.post("/api/time/skip")
def time_skip(req: TimeSkipRequest):
    return graph_store.public(graph_store.skip_time(req.days))


@app.post("/api/time/set")
def time_set(req: TimeSkipRequest):
    return graph_store.public(graph_store.set_time_offset(req.days))


# Serve the built frontend if it exists (production/single-command mode).
_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(_dist):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="static")
