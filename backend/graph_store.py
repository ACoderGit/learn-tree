"""The knowledge graph: persistence, the merge algorithm, and manual editing.

Merge is the heart of the app. Claude is shown the current node labels when it
extracts a source, so it can reuse an existing topic (structural merge) or flag
topics the source only *touches* (indirect reinforcement -> confidence bump).
Matching still falls back to fuzzy label comparison for safety.
"""
import json
import os
import re
import threading

import llm

DATA_PATH = os.environ.get("GRAPH_PATH",
                           os.path.join(os.path.dirname(__file__), "graph.json"))
SOURCE_CACHE_PATH = os.environ.get(
    "SOURCE_CACHE_PATH",
    os.path.join(os.path.dirname(__file__), "source_cache.json"),
)
DEMO_SOURCES = [
    {
        "url": "https://online.stanford.edu/courses/mse232-introduction-game-theory",
        "title": "Introduction to Game Theory",
        "provider": "demo",
        "nodes": [
            {"label": "Mathematics", "level": 0, "parent": None,
             "summary": "Formal reasoning and quantitative models"},
            {"label": "Game Theory", "level": 1, "parent": "Mathematics",
             "summary": "Strategic decision-making models"},
            {"label": "Strategic Reasoning", "level": 2, "parent": "Game Theory",
             "summary": "Reasoning about other agents"},
            {"label": "Nash Equilibrium", "level": 2, "parent": "Game Theory",
             "summary": "Stable strategic outcomes"},
        ],
        "reinforces": [],
    },
    {
        "url": "demo://react-state-management",
        "title": "React State Management",
        "provider": "demo",
        "nodes": [
            {"label": "Programming", "level": 0, "parent": None,
             "summary": "Building software systems"},
            {"label": "React", "level": 1, "parent": "Programming",
             "summary": "Component-based UI development"},
            {"label": "State Management", "level": 2, "parent": "React",
             "summary": "Coordinating changing interface data"},
        ],
        "reinforces": [],
    },
    {
        "url": "demo://gradient-descent",
        "title": "Gradient Descent Basics",
        "provider": "demo",
        "nodes": [
            {"label": "Mathematics", "level": 0, "parent": None,
             "summary": "Formal reasoning and quantitative models"},
            {"label": "Optimization", "level": 1, "parent": "Mathematics",
             "summary": "Finding better solutions"},
            {"label": "Gradient Descent", "level": 2, "parent": "Optimization",
             "summary": "Iterative loss minimization"},
        ],
        "reinforces": ["Mathematics"],
    },
    {
        "url": "https://www.youtube.com/watch?v=EbjXc2oIm0Y",
        "title": "IUPAC Organic Nomenclature",
        "provider": "demo",
        "nodes": [
            {"label": "Science", "level": 0, "parent": None,
             "summary": "Natural-world concepts and systems"},
            {"label": "IUPAC Organic Nomenclature", "level": 1, "parent": "Science",
             "summary": "Systematic naming of organic molecules"},
            {"label": "Alkanes", "level": 2, "parent": "IUPAC Organic Nomenclature",
             "summary": "Single-bond hydrocarbons use -ane"},
            {"label": "Alkenes", "level": 2, "parent": "IUPAC Organic Nomenclature",
             "summary": "Double-bond hydrocarbons use -ene"},
            {"label": "Alkynes", "level": 2, "parent": "IUPAC Organic Nomenclature",
             "summary": "Triple-bond hydrocarbons use -yne"},
            {"label": "Alcohols", "level": 2, "parent": "IUPAC Organic Nomenclature",
             "summary": "Hydroxyl groups use -ol"},
        ],
        "reinforces": ["Science"],
    },
    {
        "url": "demo://organic-functional-groups",
        "title": "Organic Functional Groups",
        "provider": "demo",
        "nodes": [
            {"label": "Science", "level": 0, "parent": None,
             "summary": "Natural-world concepts and systems"},
            {"label": "IUPAC Organic Nomenclature", "level": 1, "parent": "Science",
             "summary": "Systematic naming of organic molecules"},
            {"label": "Functional Group Priority", "level": 2,
             "parent": "IUPAC Organic Nomenclature",
             "summary": "Higher-priority groups determine suffixes"},
            {"label": "Alcohols", "level": 2, "parent": "IUPAC Organic Nomenclature",
             "summary": "Hydroxyl groups use -ol"},
        ],
        "reinforces": ["Science", "Alcohols"],
    },
    {
        "url": "demo://react-components",
        "title": "React Components",
        "provider": "demo",
        "nodes": [
            {"label": "Programming", "level": 0, "parent": None,
             "summary": "Building software systems"},
            {"label": "React", "level": 1, "parent": "Programming",
             "summary": "Component-based UI development"},
            {"label": "Components", "level": 2, "parent": "React",
             "summary": "Reusable interface building blocks"},
        ],
        "reinforces": ["Programming", "React"],
    },
    {
        "url": "demo://spanish-pronunciation-practice",
        "title": "Spanish Pronunciation Practice",
        "provider": "demo",
        "nodes": [
            {"label": "Languages", "level": 0, "parent": None,
             "summary": "Human language learning"},
            {"label": "Spanish Language Fundamentals", "level": 1,
             "parent": "Languages",
             "summary": "Core Spanish pronunciation and alphabet"},
            {"label": "Spanish Vowel System", "level": 2,
             "parent": "Spanish Language Fundamentals",
             "summary": "Vowels keep consistent sounds"},
        ],
        "reinforces": ["Languages", "Spanish Vowel System"],
    },
    {
        "url": "https://en.wikipedia.org/wiki/French_phonology",
        "title": "French Phonology",
        "provider": "demo",
        "nodes": [
            {"label": "Languages", "level": 0, "parent": None,
             "summary": "Human language learning"},
            {"label": "French Language Fundamentals", "level": 1,
             "parent": "Languages",
             "summary": "Core French sounds and speech patterns"},
            {"label": "French Vowel Sounds", "level": 2,
             "parent": "French Language Fundamentals",
             "summary": "Oral and nasal vowel contrasts"},
            {"label": "Nasal Vowels", "level": 2,
             "parent": "French Language Fundamentals",
             "summary": "Airflow through nose shapes meaning"},
            {"label": "French Liaison", "level": 2,
             "parent": "French Language Fundamentals",
             "summary": "Final consonants connect before vowels"},
        ],
        "reinforces": ["Languages"],
    },
    {
        "url": "https://en.wikipedia.org/wiki/Progressive_overload",
        "title": "Progressive Overload",
        "provider": "demo",
        "nodes": [
            {"label": "Fitness", "level": 0, "parent": None,
             "summary": "Training, health, and physical adaptation"},
            {"label": "Strength Training", "level": 1,
             "parent": "Fitness",
             "summary": "Training to build force output"},
            {"label": "Progressive Overload", "level": 2,
             "parent": "Strength Training",
             "summary": "Gradually increasing training stress"},
            {"label": "Training Volume", "level": 2,
             "parent": "Strength Training",
             "summary": "Sets, reps, and total workload"},
            {"label": "Recovery Management", "level": 2,
             "parent": "Strength Training",
             "summary": "Balancing stress with adaptation"},
        ],
        "reinforces": ["Fitness"],
    },
    {
        "url": "https://en.wikipedia.org/wiki/Newton%27s_laws_of_motion",
        "title": "Newton's Laws of Motion",
        "provider": "demo",
        "nodes": [
            {"label": "Science", "level": 0, "parent": None,
             "summary": "Natural-world concepts and systems"},
            {"label": "Classical Mechanics", "level": 1,
             "parent": "Science",
             "summary": "Motion, forces, and physical systems"},
            {"label": "Newton's Laws", "level": 2,
             "parent": "Classical Mechanics",
             "summary": "Rules connecting force and motion"},
            {"label": "Inertia", "level": 2,
             "parent": "Classical Mechanics",
             "summary": "Motion persists without net force"},
            {"label": "Force and Acceleration", "level": 2,
             "parent": "Classical Mechanics",
             "summary": "Net force changes motion"},
        ],
        "reinforces": ["Science"],
    },
]

DOMAIN_KEYWORDS = {
    "Science": [
        "science", "biology", "chemistry", "organic", "iupac", "alkane",
        "alkene", "alkyne", "alcohol", "physics", "molecule", "carbon",
        "cell", "genetics", "ecology", "astronomy", "mechanics", "newton",
        "force", "motion", "inertia",
    ],
    "Programming": [
        "programming", "software", "code", "python", "javascript", "react",
        "llm", "model training", "api", "backend", "frontend",
    ],
    "Mathematics": [
        "math", "mathematics", "calculus", "algebra", "probability",
        "statistics", "optimization", "game theory", "equilibrium",
        "vector", "vectors", "matrix", "matrices", "linear algebra",
        "coordinate", "geometry", "transformation", "transformations",
    ],
    "Languages": [
        "spanish", "french", "japanese", "language", "pronunciation",
        "vocabulary", "grammar", "alphabet",
    ],
    "Fitness": [
        "fitness", "workout", "strength", "cardio", "nutrition",
        "nutrient", "macronutrient", "protein", "carbohydrate", "digestion",
        "absorption", "hypertrophy", "mobility",
    ],
    "Entrepreneurship": [
        "entrepreneurship", "entrepreneur", "startup", "startups", "business",
        "business model", "company building", "venture", "fundraising",
        "sales", "marketing", "customer discovery", "product market fit",
        "product-market fit", "go to market", "go-to-market", "revenue",
        "pricing", "operations", "pitch", "investor", "founder",
    ],
}

ROOT_ALIASES = {
    "programming": "Coding",
    "software engineering": "Coding",
    "computer science": "Coding",
    "coding": "Coding",
    "mathematics": "Maths",
    "math": "Maths",
    "maths": "Maths",
    "fitness": "Gym",
    "gym": "Gym",
    "nutrition": "Gym",
    "nutrition science": "Gym",
    "health": "Gym",
    "exercise science": "Gym",
    "physical training": "Gym",
    "languages": "Languages",
    "langs": "Languages",
    "foreign languages": "Languages",
    "language learning": "Languages",
    "entrepreneurship": "Entrepreneurship",
    "entrepreneur": "Entrepreneurship",
    "business": "Entrepreneurship",
    "startup": "Entrepreneurship",
    "startups": "Entrepreneurship",
    "venture": "Entrepreneurship",
    "company building": "Entrepreneurship",
}

_lock = threading.Lock()
DEFAULT_PLANE = "Main"


def _slug(label: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return s or "node"


def _norm(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()


def _match(a: str, b: str) -> bool:
    """True if two labels name the same topic (tolerates a trailing plural 's')."""
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    return a == b or a + "s" == b or a == b + "s"


def _broad_domain_for(label: str) -> str | None:
    text = _norm(label)
    if text in ROOT_ALIASES:
        return ROOT_ALIASES[text]
    for domain, keywords in DOMAIN_KEYWORDS.items():
        if _match(label, domain):
            return ROOT_ALIASES.get(_norm(domain), domain)
        if any(k in text for k in keywords):
            return ROOT_ALIASES.get(_norm(domain), domain)
    return None


def _ensure_domain_node(nodes: list[dict], graph: dict, domain: str) -> None:
    if any(_match(n["label"], domain) for n in nodes):
        return
    if any(_match(n["label"], domain) for n in graph["nodes"]):
        return
    nodes.insert(0, {
        "label": domain,
        "level": 0,
        "parent": None,
        "summary": "Broad learning domain",
    })


def _existing_root_label(graph: dict, label: str) -> str | None:
    for node in graph["nodes"]:
        if node.get("level") == 0 and _match(node["label"], label):
            return node["label"]
    return None


def _coerce_broad_roots(nodes: list[dict], graph: dict) -> list[dict]:
    """Force extracted topics into the existing level-0 roots."""
    clean = [dict(n) for n in nodes]
    existing_roots = {
        _norm(n["label"]) for n in graph["nodes"]
        if n.get("level") == 0
    }
    broad_roots = [n["label"] for n in graph["nodes"] if n.get("level") == 0]
    root_by_norm = {_norm(n["label"]): n["label"] for n in graph["nodes"] if n.get("level") == 0}
    entrepreneurship_root = _existing_root_label(graph, "Entrepreneurship")
    needs_entrepreneurship = False
    for n in clean:
        n["level"] = max(0, min(2, int(n.get("level", 1))))
        parent = n.get("parent")
        if parent and _norm(parent) in ROOT_ALIASES:
            n["parent"] = ROOT_ALIASES[_norm(parent)]
            parent = n["parent"]
        if (
            n.get("level") != 0
            and parent
            and _match(parent, "Entrepreneurship")
            and not entrepreneurship_root
        ):
            entrepreneurship_root = "Entrepreneurship"
            needs_entrepreneurship = True

        alias_domain = ROOT_ALIASES.get(_norm(n["label"]))
        if (
            alias_domain
            and n.get("level") == 0
            and (_norm(alias_domain) in root_by_norm or alias_domain == "Entrepreneurship")
        ):
            if alias_domain == "Entrepreneurship" and not entrepreneurship_root:
                entrepreneurship_root = "Entrepreneurship"
                needs_entrepreneurship = True
            n["label"] = root_by_norm.get(_norm(alias_domain), alias_domain)
            n["level"] = 0
            n["parent"] = None
            continue

        if n.get("level") != 0:
            if not n.get("parent"):
                domain = _broad_domain_for(f"{n.get('label', '')} {n.get('summary', '')}")
                if domain == "Entrepreneurship" and not entrepreneurship_root:
                    entrepreneurship_root = "Entrepreneurship"
                    needs_entrepreneurship = True
                n["parent"] = root_by_norm.get(
                    _norm(domain),
                    entrepreneurship_root if domain == "Entrepreneurship" else broad_roots[0] if broad_roots else None,
                )
            continue

        domain = _broad_domain_for(n["label"])
        is_existing_root = _norm(n["label"]) in existing_roots
        has_existing_domain = domain and _norm(domain) in root_by_norm
        if is_existing_root:
            continue
        if domain == "Entrepreneurship":
            n["label"] = entrepreneurship_root or "Entrepreneurship"
            n["level"] = 0
            n["parent"] = None
            entrepreneurship_root = n["label"]
            needs_entrepreneurship = True
            continue

        n["level"] = 1
        if has_existing_domain:
            n["parent"] = root_by_norm[_norm(domain)]
        elif broad_roots:
            summary_domain = _broad_domain_for(n.get("summary", ""))
            summary_key = _norm(summary_domain) if summary_domain else ""
            if summary_domain == "Entrepreneurship" and not entrepreneurship_root:
                entrepreneurship_root = "Entrepreneurship"
                needs_entrepreneurship = True
            n["parent"] = root_by_norm.get(
                summary_key,
                entrepreneurship_root if summary_domain == "Entrepreneurship" else
                "Maths" if "Maths" in broad_roots else broad_roots[0],
            )
    if needs_entrepreneurship:
        _ensure_domain_node(clean, graph, "Entrepreneurship")
    return clean


def _next_seq(graph: dict) -> int:
    return max((n.get("seq", 0) for n in graph["nodes"]), default=0) + 1


def _eday(graph: dict) -> float:
    """Abstract demo day. It intentionally does not use wall-clock time."""
    return max(0, float(graph.get("timeOffsetDays", 0) or 0))


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
def _empty_graph() -> dict:
    return {"nodes": [], "links": [], "timeOffsetDays": 0}


def _normalise_graph(graph: dict) -> dict:
    graph.setdefault("nodes", [])
    graph.setdefault("links", [])
    graph.setdefault("timeOffsetDays", 0)
    for node in graph["nodes"]:
        node.setdefault("seenDay", 0)
    return graph


def _empty_store() -> dict:
    return {"activePlane": DEFAULT_PLANE, "planes": {DEFAULT_PLANE: _empty_graph()}}


def _read_store() -> dict:
    if not os.path.exists(DATA_PATH):
        return _empty_store()
    try:
        with open(DATA_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return _empty_store()

    if isinstance(data.get("planes"), dict):
        store = data
        if not store["planes"]:
            store["planes"][DEFAULT_PLANE] = _empty_graph()
        for graph in store["planes"].values():
            _normalise_graph(graph)
        active = store.get("activePlane")
        if active not in store["planes"]:
            store["activePlane"] = next(iter(store["planes"]))
        return store

    legacy = _normalise_graph(data if isinstance(data, dict) else _empty_graph())
    return {"activePlane": DEFAULT_PLANE, "planes": {DEFAULT_PLANE: legacy}}


def _write_store(store: dict) -> None:
    tmp = DATA_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_PATH)


def load() -> dict:
    store = _read_store()
    active = store["activePlane"]
    graph = dict(_normalise_graph(store["planes"][active]))
    graph["_plane"] = active
    return graph


def save(graph: dict) -> None:
    store = _read_store()
    plane = graph.get("_plane") or store.get("activePlane") or DEFAULT_PLANE
    clean = {k: v for k, v in graph.items() if k != "_plane"}
    store.setdefault("planes", {})
    store["planes"][plane] = _normalise_graph(clean)
    store["activePlane"] = plane
    _write_store(store)


def list_planes() -> dict:
    store = _read_store()
    planes = []
    for name, graph in store["planes"].items():
        planes.append({
            "name": name,
            "nodes": len(graph.get("nodes", [])),
            "sources": len({src for n in graph.get("nodes", []) for src in n.get("sources", [])}),
        })
    return {"active": store["activePlane"], "planes": planes}


def create_plane(name: str) -> dict:
    with _lock:
        store = _read_store()
        base = (name or "").strip()[:40] or "New Plane"
        name = base
        i = 2
        while name in store["planes"]:
            name = f"{base} {i}"
            i += 1
        store["planes"][name] = _empty_graph()
        store["activePlane"] = name
        _write_store(store)
        return load()


def switch_plane(name: str) -> dict:
    with _lock:
        store = _read_store()
        if name in store["planes"]:
            store["activePlane"] = name
            _write_store(store)
        return load()


def delete_plane(name: str) -> dict:
    with _lock:
        store = _read_store()
        if name in store["planes"] and len(store["planes"]) > 1:
            del store["planes"][name]
            if store.get("activePlane") == name:
                store["activePlane"] = next(iter(store["planes"]))
            _write_store(store)
        return load()


def load_source_cache() -> dict:
    if not os.path.exists(SOURCE_CACHE_PATH):
        cache = {item["url"]: item for item in DEMO_SOURCES}
        save_source_cache(cache)
        return cache
    try:
        with open(SOURCE_CACHE_PATH, encoding="utf-8") as f:
            cache = json.load(f)
        for item in DEMO_SOURCES:
            cache.setdefault(item["url"], item)
        return cache
    except (json.JSONDecodeError, OSError):
        return {item["url"]: item for item in DEMO_SOURCES}


def save_source_cache(cache: dict) -> None:
    tmp = SOURCE_CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SOURCE_CACHE_PATH)


def cached_source(url: str) -> dict | None:
    return load_source_cache().get(url)


def remember_source(url: str, title: str, nodes: list[dict],
                    reinforces: list[str], provider: str) -> None:
    cache = load_source_cache()
    cache[url] = {
        "url": url,
        "title": title,
        "nodes": nodes,
        "reinforces": reinforces or [],
        "provider": provider,
    }
    save_source_cache(cache)


def public(graph: dict) -> dict:
    """Strip internal fields and include time-derived review state."""
    day = _eday(graph)
    by_id = {n["id"]: n for n in graph["nodes"]}
    neighbors: dict[str, list[tuple[str, float]]] = {n["id"]: [] for n in graph["nodes"]}
    children: dict[str, list[str]] = {n["id"]: [] for n in graph["nodes"]}
    for link in graph["links"]:
        source = link.get("source")
        target = link.get("target")
        if source in by_id and target in by_id:
            children.setdefault(source, []).append(target)
            neighbors.setdefault(source, []).append((target, 0.28))
            neighbors.setdefault(target, []).append((source, 0.42))

    def own_evidence(node: dict) -> float:
        own_sources = len(node.get("sources", []))
        own_count = node.get("count", 0)
        return min(4.0, float(max(own_sources, own_count if own_sources else 0)))

    def evidence(node: dict) -> float:
        child_evidence = sum(own_evidence(by_id[cid]) * 0.2 for cid in children.get(node["id"], []))
        return min(4.0, own_evidence(node) + child_evidence)

    nodes = []
    for n in graph["nodes"]:
        item = {k: v for k, v in n.items() if k != "embedding"}
        age = max(0, day - float(item.get("seenDay", 0) or 0))
        own = evidence(n)
        borrowed = 0.0
        for neighbor_id, weight in neighbors.get(n["id"], []):
            borrowed += evidence(by_id[neighbor_id]) * weight
        visual = min(4.0, own + borrowed * (0.55 if own else 0.35))
        item["ageDays"] = round(age, 2)
        item["reviewDue"] = age >= 7 and not item.get("anchor")
        item["visualCount"] = round(visual, 2)
        item["confidencePercent"] = 0 if visual <= 0 else round((0.25 + (min(visual, 4) - 1) * 0.25) * 100)
        nodes.append(item)
    links = []
    for link in graph["links"]:
        item = dict(link)
        item.setdefault("kind", "detail")
        item.setdefault("strength", 3 if item["kind"] == "strong" else 1)
        links.append(item)
    planes = list_planes()
    return {"nodes": nodes, "links": links,
            "timeOffsetDays": graph.get("timeOffsetDays", 0),
            "dueReviews": due_reviews(graph),
            "plane": graph.get("_plane") or planes["active"],
            "planes": planes["planes"]}


def labels(graph: dict | None = None) -> list[str]:
    """All current node labels (for feeding Claude at extraction time)."""
    g = graph if graph is not None else load()
    return [n["label"] for n in g["nodes"]]


def hierarchy_context(graph: dict | None = None) -> list[str]:
    """Existing level-0/1/2 hierarchy for Claude placement decisions."""
    g = graph if graph is not None else load()
    children = {}
    for link in g["links"]:
        children.setdefault(link["source"], []).append(link["target"])
    by_id = {n["id"]: n for n in g["nodes"]}
    lines = []
    roots = sorted(
        [n for n in g["nodes"] if n.get("level") == 0],
        key=lambda n: n["label"].lower(),
    )
    for root in roots:
        lines.append(root["label"])
        child_nodes = [
            by_id[cid] for cid in children.get(root["id"], [])
            if cid in by_id and by_id[cid].get("level") == 1
        ]
        for child in sorted(child_nodes, key=lambda n: n["label"].lower()):
            lines.append(f"  - {child['label']}")
            grandchild_nodes = [
                by_id[cid] for cid in children.get(child["id"], [])
                if cid in by_id and by_id[cid].get("level") == 2
            ]
            for grandchild in sorted(grandchild_nodes, key=lambda n: n["label"].lower()):
                lines.append(f"    - {grandchild['label']}")
    return lines or labels(g)


def _unique_id(base: str, taken: set) -> str:
    if base not in taken:
        return base
    i = 2
    while f"{base}-{i}" in taken:
        i += 1
    return f"{base}-{i}"


def _add_link(graph: dict, source: str, target: str, seen: set, kind: str = "detail") -> None:
    if source == target:
        return
    key = tuple(sorted((source, target)))
    if key in seen:
        for link in graph["links"]:
            if {link["source"], link["target"]} == {source, target}:
                if kind == "strong" and link.get("kind") != "strong":
                    link["kind"] = "strong"
                    link["strength"] = 3
                else:
                    link["strength"] = min(link.get("strength", 1) + 1, 6)
                return
    seen.add(key)
    graph["links"].append({
        "source": source,
        "target": target,
        "kind": kind,
        "strength": 3 if kind == "strong" else 1,
    })


def _flatten_level2_parents(graph: dict) -> None:
    """The UI has three visual levels only; prevent level-2 nodes parenting children."""
    index = {n["id"]: n for n in graph["nodes"]}
    incoming = {}
    for link in graph["links"]:
        incoming.setdefault(link["target"], []).append(link["source"])

    rewired = []
    remove = set()
    for i, link in enumerate(graph["links"]):
        source = index.get(link["source"])
        target = index.get(link["target"])
        if not source or not target or source.get("level", 0) < 2:
            continue
        parent_id = next((pid for pid in incoming.get(source["id"], []) if pid in index), None)
        if not parent_id:
            continue
        target["level"] = 2
        target["anchor"] = False
        remove.add(i)
        rewired.append({
            "source": parent_id,
            "target": target["id"],
            "kind": "detail",
            "strength": max(1, link.get("strength", 1)),
        })

    if not remove:
        return
    graph["links"] = [link for i, link in enumerate(graph["links"]) if i not in remove]
    seen = {tuple(sorted((l["source"], l["target"]))) for l in graph["links"]}
    for link in rewired:
        _add_link(graph, link["source"], link["target"], seen, link.get("kind", "detail"))


# --------------------------------------------------------------------------- #
# Merge
# --------------------------------------------------------------------------- #
def _find_or_create(graph: dict, node: dict, url: str, index: dict) -> str:
    label = node["label"]
    slug = _slug(label)

    best_id = None
    for existing in graph["nodes"]:
        if existing["id"] == slug or _match(existing["label"], label):
            best_id = existing["id"]
            break

    if best_id:
        existing = index[best_id]
        existing["count"] = existing.get("count", 1) + 1
        existing["seenDay"] = _eday(graph)
        if url and url not in existing["sources"]:
            existing["sources"].append(url)
        if not existing.get("summary") and node.get("summary"):
            existing["summary"] = node["summary"]
        existing["level"] = min(existing.get("level", 2), node["level"])
        if existing["level"] == 0:
            existing["anchor"] = True
        return best_id

    new_id = _unique_id(slug, set(index))
    new_node = {
        "id": new_id,
        "label": label,
        "level": node["level"],
        "summary": node.get("summary", ""),
        "sources": [url] if url else [],
        "count": 1,
        "seq": _next_seq(graph),
        "seenDay": _eday(graph),
        "anchor": node["level"] == 0,
    }
    graph["nodes"].append(new_node)
    index[new_id] = new_node
    return new_id


def merge(new_nodes: list[dict], reinforces: list[str], url: str) -> dict:
    """Merge extracted main nodes + indirectly-reinforced labels into the graph."""
    with _lock:
        graph = load()
        new_nodes = _coerce_broad_roots(new_nodes, graph)
        index = {n["id"]: n for n in graph["nodes"]}
        link_seen = {tuple(sorted((l["source"], l["target"]))) for l in graph["links"]}

        ordered = sorted(new_nodes, key=lambda n: n["level"])
        label_to_id: dict[str, str] = {}
        for n in ordered:
            nid = _find_or_create(graph, n, url, index)
            label_to_id[n["label"].lower()] = nid

        for n in new_nodes:
            parent = n.get("parent")
            if not parent:
                continue
            pid = label_to_id.get(parent.lower())
            if not pid:
                match = next((x for x in graph["nodes"] if _match(x["label"], parent)), None)
                pid = match["id"] if match else None
            if pid:
                child_id = label_to_id[n["label"].lower()]
                parent_node = index.get(pid)
                child_node = index.get(child_id)
                strong = (
                    parent_node
                    and child_node
                    and parent_node.get("level", 2) <= 1
                    and child_node.get("level", 2) <= 1
                )
                _add_link(graph, pid, child_id, link_seen, "strong" if strong else "detail")

        # Indirect reinforcement: bump confidence on existing nodes the source
        # touches but isn't primarily about. Skip anything that's a main node.
        main_norms = {_norm(n["label"]) for n in new_nodes}
        for lbl in reinforces or []:
            if _norm(lbl) in main_norms:
                continue
            existing = next((x for x in graph["nodes"] if _match(x["label"], lbl)), None)
            if existing:
                existing["count"] = existing.get("count", 1) + 1
                existing["seenDay"] = _eday(graph)
                if url and url not in existing["sources"]:
                    existing["sources"].append(url)
                for main in new_nodes:
                    mid = label_to_id.get(main["label"].lower())
                    if mid and mid != existing["id"]:
                        _add_link(graph, mid, existing["id"], link_seen, "weak")

        _flatten_level2_parents(graph)
        save(graph)
        return graph


# --------------------------------------------------------------------------- #
# Manual editing / anchors / time
# --------------------------------------------------------------------------- #
def clear() -> dict:
    with _lock:
        empty = {"nodes": [], "links": [], "timeOffsetDays": 0}
        save(empty)
        return empty


def prune_empty_domains() -> dict:
    """Remove old auto-seeded level-0 domains that have no learned content."""
    with _lock:
        graph = load()
        linked = set()
        for link in graph["links"]:
            linked.add(link["source"])
            linked.add(link["target"])
        keep = []
        removed = set()
        for node in graph["nodes"]:
            empty_domain = (
                node.get("level") == 0
                and node.get("anchor")
                and not node.get("sources")
                and node["id"] not in linked
                and node.get("count", 1) <= 1
            )
            if empty_domain:
                removed.add(node["id"])
            else:
                keep.append(node)
        if removed:
            graph["nodes"] = keep
            graph["links"] = [
                l for l in graph["links"]
                if l["source"] not in removed and l["target"] not in removed
            ]
            save(graph)
        return graph


def load_demo_sources() -> dict:
    """Import saved demo source results without making any API calls."""
    graph = load()
    for item in DEMO_SOURCES:
        remember_source(
            item["url"],
            item["title"],
            item["nodes"],
            item.get("reinforces", []),
            item.get("provider", "demo"),
        )
        graph = merge(item["nodes"], item.get("reinforces", []), item["url"])
    return graph


def add_node(label: str, level: int = 0, parent_id: str | None = None,
             anchor: bool = False) -> dict:
    with _lock:
        graph = load()
        label = (label or "").strip()
        if not label:
            return graph
        index = {n["id"]: n for n in graph["nodes"]}
        nid = _unique_id(_slug(label), set(index))
        graph["nodes"].append({
            "id": nid, "label": label[:60],
            "level": max(0, min(2, int(level))), "anchor": bool(anchor),
            "summary": "", "sources": [], "count": 1,
            "seq": _next_seq(graph), "seenDay": _eday(graph),
        })
        if parent_id and parent_id in index:
            seen = {tuple(sorted((l["source"], l["target"]))) for l in graph["links"]}
            kind = "strong" if level <= 1 and index[parent_id].get("level", 2) <= 1 else "detail"
            _add_link(graph, parent_id, nid, seen, kind)
        _flatten_level2_parents(graph)
        save(graph)
        return graph


def rename_node(node_id: str, label: str) -> dict:
    with _lock:
        graph = load()
        label = (label or "").strip()
        if label:
            for n in graph["nodes"]:
                if n["id"] == node_id:
                    n["label"] = label[:60]
                    break
        save(graph)
        return graph


def delete_node(node_id: str) -> dict:
    with _lock:
        graph = load()
        graph["nodes"] = [n for n in graph["nodes"] if n["id"] != node_id]
        graph["links"] = [l for l in graph["links"]
                          if l["source"] != node_id and l["target"] != node_id]
        save(graph)
        return graph


def set_node_level(node_id: str, level: int) -> dict:
    """Promote/demote a node one level while keeping a valid directed tree."""
    with _lock:
        graph = load()
        index = {n["id"]: n for n in graph["nodes"]}
        node = index.get(node_id)
        if not node:
            return graph

        old_level = max(0, min(2, int(node.get("level", 1))))
        new_level = max(0, min(2, int(level)))
        if new_level == old_level:
            return graph

        parent_link = next((l for l in graph["links"] if l["target"] == node_id), None)
        parent_id = parent_link["source"] if parent_link else None
        grandparent_link = (
            next((l for l in graph["links"] if l["target"] == parent_id), None)
            if parent_id else None
        )
        grandparent_id = grandparent_link["source"] if grandparent_link else None

        graph["links"] = [l for l in graph["links"] if l["target"] != node_id]
        node["level"] = new_level
        node["anchor"] = new_level == 0

        seen = {tuple(sorted((l["source"], l["target"]))) for l in graph["links"]}
        if new_level == 0:
            pass
        elif new_level == 1:
            target_parent = grandparent_id or parent_id
            if target_parent and target_parent in index:
                index[target_parent]["level"] = 0
                index[target_parent]["anchor"] = True
                _add_link(graph, target_parent, node_id, seen, "strong")
        else:
            target_parent = parent_id
            if target_parent and target_parent in index:
                index[target_parent]["level"] = min(index[target_parent].get("level", 1), 1)
                index[target_parent]["anchor"] = index[target_parent].get("level") == 0
                _add_link(graph, target_parent, node_id, seen, "detail")

        _normalize_descendant_levels(graph, node_id)
        _flatten_level2_parents(graph)
        save(graph)
        return graph


def _normalize_descendant_levels(graph: dict, root_id: str) -> None:
    index = {n["id"]: n for n in graph["nodes"]}
    children: dict[str, list[str]] = {}
    for link in graph["links"]:
        children.setdefault(link["source"], []).append(link["target"])

    queue = [root_id]
    seen = set()
    while queue:
        parent_id = queue.pop(0)
        if parent_id in seen:
            continue
        seen.add(parent_id)
        parent = index.get(parent_id)
        if not parent:
            continue
        child_level = min(parent.get("level", 0) + 1, 2)
        for child_id in children.get(parent_id, []):
            child = index.get(child_id)
            if child:
                child["level"] = child_level
                child["anchor"] = child_level == 0
                queue.append(child_id)


def review_node(node_id: str) -> dict:
    """Mark a node reviewed on the current abstract demo day."""
    with _lock:
        graph = load()
        for n in graph["nodes"]:
            if n["id"] == node_id:
                n["seenDay"] = _eday(graph)
                break
        save(graph)
        return graph


def skip_time(days: float) -> dict:
    """Demo helper: advance the abstract clock so decay is visible immediately."""
    with _lock:
        graph = load()
        graph["timeOffsetDays"] = max(0, _eday(graph) + float(days or 0))
        save(graph)
        return graph


def set_time_offset(days: float) -> dict:
    """Set the abstract demo day exactly."""
    with _lock:
        graph = load()
        graph["timeOffsetDays"] = max(0, float(days or 0))
        save(graph)
        return graph


def due_reviews(graph: dict | None = None) -> list[dict]:
    """Nodes whose confidence is aging and should be reviewed soon."""
    g = graph if graph is not None else load()
    day = _eday(g)
    due = []
    for n in g["nodes"]:
        age = max(0, day - float(n.get("seenDay", 0) or 0))
        if age >= 7 and not n.get("anchor"):
            due.append({
                "id": n["id"],
                "label": n["label"],
                "ageDays": round(age, 1),
                "sources": len(n.get("sources", [])),
            })
    return sorted(due, key=lambda x: x["ageDays"], reverse=True)[:8]
