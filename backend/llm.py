"""Topic extraction and recommendations, with graceful provider fallback.

Provider is chosen automatically (override with LLM_PROVIDER env var):
  1. anthropic  — if ANTHROPIC_API_KEY is set
  2. openai     — if OPENAI_API_KEY is set
  3. heuristic  — always works, zero setup (keyword-based)
"""
import json
import os
import re
from collections import Counter

import requests

# Cost guardrails: enough room for a real video transcript while still capping spend.
MAX_CHARS = 20000         # roughly 5k input tokens, enough for most transcripts
MAX_OUTPUT_TOKENS = 2200  # room for structured nodes + reinforcements

PROMPT = """You are mapping a person's knowledge from something they just studied. \
Extract the actual concepts and skills this content TEACHES — the things the person \
now understands — as a small hierarchy of at most 14 main nodes.

The learner already has this level-0/level-1/level-2 tree. Your job is to \
insert this source into that structure, not invent a parallel taxonomy. Before \
creating any new parent, decide whether each concept fits an existing level-0, \
level-1, or level-2 node. Reuse an existing label when the source is mainly \
about it. If the source only touches an existing node, put that label in \
"reinforces" instead of adding it as a main node. This raises confidence without \
making the graph too noisy.

EXISTING NODES:
{existing}

{{"nodes": [
  {{"label": "Canonical Topic Name", "level": 1, "parent": "Existing Level 0 Label", "summary": "<=8 word takeaway"}}
], "reinforces": ["Existing Node Label"]}}

Rules:
- You are NOT allowed to create level-0 nodes except for exactly one case: \
if the source is clearly about entrepreneurship, startups, business models, \
sales, marketing, fundraising, product-market fit, or company building, and \
there is no existing "Entrepreneurship" level-0 node shown above, you may \
output {{"label": "Entrepreneurship", "level": 0, "parent": "", "summary": "Building and growing ventures"}}.
- If "Entrepreneurship" already exists, reuse that exact existing level-0 \
label and add new level-1/level-2 nodes under it. Do not create "Business", \
"Startups", "Venture", or similar as a separate level-0.
- Every main node must be placed under one of the existing level-0 nodes shown \
above, except for the allowed new "Entrepreneurship" case.
- level 0 = existing broad domains plus the allowed new "Entrepreneurship" \
domain only.
- level 1 = topic, level 2 = narrow subtopic or skill.
- Do not create level-0 nodes for course topics, chapters, techniques, tools, \
lesson subjects, subfields, or synonyms of existing domains. Those belong under \
an existing broad domain or should reinforce it.
- If nothing is a perfect fit, choose the least-wrong existing level-0 node.
- If an existing level-0 fits but no level-1 fits, create a level-1 under that \
existing level-0.
- Entrepreneurship, startups, business strategy, sales, marketing, fundraising, \
product-market fit, customer discovery, operations, and company-building \
topics belong under "Entrepreneurship" if that node exists. If it does not \
exist and the source is clearly in this area, create "Entrepreneurship" as \
the only new level-0.
- If an existing level-1 fits but no level-2 fits, create a level-2 under that \
existing level-1.
- If an existing level-2 already fits, reuse that exact label instead of making \
a synonym.
- Vectors, matrices, linear algebra, coordinate geometry, and transformations \
belong under "Maths" if that node exists.
- Nutrition, diet, macronutrients, health, exercise science, strength, and \
training topics belong under "Gym" if that node exists. Do not create \
"Nutrition Science" as a separate root or parallel branch.
- Chemistry, biology, physics, astronomy, medicine, and engineering science \
topics belong under "Science" if that node exists.
- If content is about learning a human language such as Spanish, French, or \
Japanese, it belongs under "Languages" if that node exists.
- Prefer linking new topics under an existing broad node where accurate. Use \
the exact existing parent label.
- Do NOT use the page or video title as a node. Infer the real subject domain instead \
(e.g. a video titled "Andrej's lecture 3" about backprop -> domain "Deep Learning").
- Do NOT use the URL as a node.
- Every node must be a genuine concept a learner would take away — never site \
boilerplate like "Privacy Policy", "Subscribe", "Comments", "Home", or a channel/author name.
- "parent" is the exact label of another existing node or a node you output. \
It must not be null.
- Use canonical topic names ("Gradient Descent", not "how gradients work") so the same \
concept from different sources collapses together.

TITLE: {title}

CONTENT:
{content}
"""

# JSON schema for Claude structured outputs — guarantees parseable, well-shaped output.
ANTHROPIC_SCHEMA = {
    "type": "object",
    "properties": {
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "level": {"type": "integer", "enum": [0, 1, 2]},
                    "parent": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "required": ["label", "level", "parent", "summary"],
                "additionalProperties": False,
            },
        },
        "reinforces": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["nodes", "reinforces"],
    "additionalProperties": False,
}


# --------------------------------------------------------------------------- #
# Provider selection
# --------------------------------------------------------------------------- #
def active_provider() -> str:
    forced = os.environ.get("LLM_PROVIDER")
    if forced:
        return forced
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return "heuristic"


# --------------------------------------------------------------------------- #
# JSON helpers
# --------------------------------------------------------------------------- #
def _parse_topic_response(raw: str) -> tuple[list[dict], list[str]] | None:
    """Pull the first JSON object out of a model response and validate shape."""
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    nodes = data.get("nodes")
    if not isinstance(nodes, list):
        return None
    clean = []
    for n in nodes:
        label = str(n.get("label", "")).strip()
        if not label:
            continue
        try:
            level = int(n.get("level", 1))
        except (TypeError, ValueError):
            level = 1
        parent = str(n.get("parent", "")).strip()
        clean.append({
            "label": label[:60],
            "level": max(0, min(2, level)),
            "parent": parent,
            "summary": str(n.get("summary", "")).strip()[:120],
        })
    reinforces = data.get("reinforces") or []
    reinforces = [str(x).strip()[:60] for x in reinforces if str(x).strip()]
    return (clean, reinforces[:12]) if clean else None


# --------------------------------------------------------------------------- #
# Providers
# --------------------------------------------------------------------------- #
def _prompt(text: str, title: str, current_labels: list[str] | None = None) -> str:
    existing = "\n".join(f"- {label}" for label in (current_labels or [])[:140])
    if not existing:
        existing = "- Coding\n- Maths\n- Science\n- Gym\n- Languages"
    return PROMPT.format(
        title=title[:120],
        content=text[:MAX_CHARS],
        existing=existing[:4000],
    )


def _via_anthropic(
    text: str,
    title: str,
    current_labels: list[str] | None = None,
) -> tuple[list[dict], list[str]] | None:
    """Extract topics via Claude using the official SDK + structured outputs."""
    try:
        import anthropic
    except ImportError:
        return None
    try:
        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
        resp = client.messages.create(
            # Cheapest current model — plenty for short topic extraction.
            model=os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5"),
            max_tokens=MAX_OUTPUT_TOKENS,  # hard per-request output cap
            output_config={"format": {"type": "json_schema", "schema": ANTHROPIC_SCHEMA}},
            messages=[{"role": "user", "content": _prompt(text, title, current_labels)}],
        )
        if resp.stop_reason == "refusal":
            return None
        out = next((b.text for b in resp.content if b.type == "text"), "")
        return _parse_topic_response(out)
    except Exception:
        return None


def _via_openai(
    text: str,
    title: str,
    current_labels: list[str] | None = None,
) -> tuple[list[dict], list[str]] | None:
    try:
        r = requests.post("https://api.openai.com/v1/chat/completions", timeout=60, headers={
            "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
            "content-type": "application/json",
        }, json={
            "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": _prompt(text, title, current_labels)}],
        })
        r.raise_for_status()
        return _parse_topic_response(r.json()["choices"][0]["message"]["content"])
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Heuristic fallback — zero dependencies, always available
# --------------------------------------------------------------------------- #
_STOP = set("""a an the and or but of to in on for with at by from as is are was were
be been being this that these those it its into about over under your you i we they he
she them his her their our my me not no so than then too very can will just how what why
when where which who whom while also more most some such only own same each other via
using use used uses new one two three
privacy policy cookie cookies terms service services sign subscribe subscribed newsletter
copyright rights reserved menu search home login log register account contact help support
share comment comments video views watch channel follow like button click read continue
source page url slug suggests introduction theory online
advertisement sponsored settings accept consent website page site""".split())

_PHRASE_HINTS = [
    (
        "game theory",
        "Mathematics",
        [
            ("Game Theory", "Strategic decision-making models"),
            ("Strategic Reasoning", "Reasoning about other agents"),
            ("Nash Equilibrium", "Stable strategic outcomes"),
        ],
    ),
]


def _heuristic(text: str, title: str) -> list[dict]:
    """Frequency-based topic guess so the app is useful with no LLM at all."""
    root = "General Learning"
    tl = f"{title} {text[:1200]}".lower()
    for phrase, domain, topics in _PHRASE_HINTS:
        if phrase in tl:
            return (
                [{"label": domain, "level": 0, "parent": None,
                  "summary": "Source added to knowledge base"}]
                + [
                    {"label": label, "level": 1, "parent": domain, "summary": summary}
                    for label, summary in topics
                ]
            )
    if any(w in tl for w in ["python", "javascript", "react", "programming", "code", "software"]):
        root = "Programming"
    elif any(w in tl for w in [
        "math", "algebra", "calculus", "matrix", "probability",
        "game theory", "equilibrium", "strategy", "strategic",
    ]):
        root = "Mathematics"
    elif any(w in tl for w in ["workout", "fitness", "strength", "cardio", "nutrition"]):
        root = "Fitness"
    elif any(w in tl for w in ["biology", "physics", "chemistry", "science"]):
        root = "Science"
    # Candidate topics: capitalized multi-word phrases + frequent salient words.
    phrases = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b", text)
    words = re.findall(r"\b[a-zA-Z][a-zA-Z\-]{3,}\b", text.lower())
    words = [w for w in words if w not in _STOP]

    counts = Counter(p.strip() for p in phrases if p.strip().lower() not in _STOP)
    counts.update(w.title() for w in words)

    picks, seen = [], {root.lower()}
    for label, _ in counts.most_common(30):
        key = label.lower()
        if key in seen or len(label) < 4:
            continue
        seen.add(key)
        picks.append(label)
        if len(picks) >= 6:
            break

    nodes = [{"label": root, "level": 0, "parent": None,
              "summary": "Source added to knowledge base"}]
    for p in picks:
        nodes.append({"label": p, "level": 1, "parent": root, "summary": ""})
    return nodes


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def extract_topics(text: str, title: str) -> tuple[list[dict], str]:
    """Return (nodes, reinforces, provider_used). Never raises; always returns >=1 node."""
    provider = active_provider()
    dispatch = {
        "anthropic": _via_anthropic,
        "openai": _via_openai,
    }
    if provider in dispatch and (text.strip() or title.strip()):
        result = dispatch[provider](text, title, current_labels=None)
        if result:
            nodes, reinforces = result
            return nodes, reinforces, provider
    # Fallback if the model failed or there was no text.
    return _heuristic(text, title), [], "heuristic"


def extract_topics_with_context(
    text: str,
    title: str,
    current_labels: list[str],
) -> tuple[list[dict], list[str], str]:
    """Context-aware topic extraction used by the API when merging sources."""
    provider = active_provider()
    dispatch = {
        "anthropic": _via_anthropic,
        "openai": _via_openai,
    }
    if provider in dispatch and (text.strip() or title.strip()):
        result = dispatch[provider](text, title, current_labels=current_labels)
        if result:
            nodes, reinforces = result
            return nodes, reinforces, provider
    return _heuristic(text, title), [], "heuristic"


# --------------------------------------------------------------------------- #
# "What's next?" recommendations
# --------------------------------------------------------------------------- #
REC_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["course", "video", "project"]},
                    "title": {"type": "string"},
                    "where": {"type": "string"},
                    "why": {"type": "string"},
                    "time": {"type": "string"},
                    "search": {"type": "string"},
                },
                "required": ["type", "title", "where", "why", "time", "search"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "recommendations"],
    "additionalProperties": False,
}

REC_PROMPT = """Below is a map of what a learner has studied so far \
(topics indented by level). Recommend what they should learn or build next.

USER REQUEST:
{interest_instruction}

Mode: {mode}
Preferred format: {format}
Available time: {time_budget}
Selected focus nodes: {focus}

Mode meanings:
- completely_new: suggest a new area they have not touched, but if the user \
described an area then recommendations MUST be inside or directly useful for \
that described area.
- niche_down: go deeper on the selected focus nodes.
- connect_topics: combine the selected nodes into a useful bridge.
- review: recommend what to revisit and how to test retention.

Priority rules:
- The USER REQUEST is the strongest instruction after safety and JSON format. \
Do not ignore it.
- If the user names a subject, skill, project idea, industry, or constraint, \
every recommendation should visibly relate to that description.
- If the user request conflicts with selected focus nodes, prioritize the user \
request and use focus nodes only as background.
- If there is no user request, infer from the map and selected focus nodes.

Give 4-5 concrete recommendations. Respect the preferred format when possible, \
but include variety if that would clearly help. Use real, well-known \
resources by name (e.g. "fast.ai Practical Deep Learning", "3Blue1Brown") — do \
NOT invent specific URLs. For each: a short "why" tied to their current \
knowledge, and a "search" query they can paste into Google/YouTube to find it. \
Also give a one-line "summary" that explicitly reflects the user request when \
one was provided.

WHAT THEY KNOW:
{knowledge}
"""


def recommend(nodes: list[dict], options: dict | None = None) -> dict | None:
    """Suggest next courses/videos/projects from the current knowledge tree.

    Requires the Claude engine (needs a capable model); returns None otherwise.
    """
    if not nodes or active_provider() != "anthropic":
        return None
    try:
        import anthropic
    except ImportError:
        return None

    options = options or {}
    selected = set(options.get("nodeIds") or [])
    ordered = sorted(nodes, key=lambda n: (n.get("level", 0), n["label"]))
    knowledge = "\n".join("  " * n.get("level", 0) + "- " + n["label"]
                          for n in ordered)[:4000]
    focus = ", ".join(n["label"] for n in ordered if n.get("id") in selected) or "None"
    interest = (options.get("interest") or "").strip()[:700]
    interest_instruction = (
        f'The learner explicitly asked: "{interest}"'
        if interest else
        "No explicit user request was provided."
    )
    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5"),
            max_tokens=1200,
            output_config={"format": {"type": "json_schema", "schema": REC_SCHEMA}},
            messages=[{"role": "user", "content": REC_PROMPT.format(
                knowledge=knowledge,
                focus=focus,
                mode=options.get("mode", "niche_down"),
                format=options.get("format", "mixed"),
                time_budget=options.get("timeBudget", "1-2 hours"),
                interest_instruction=interest_instruction,
            )}],
        )
        if resp.stop_reason == "refusal":
            return None
        out = next((b.text for b in resp.content if b.type == "text"), "")
        m = re.search(r"\{.*\}", out, re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
        recs = data.get("recommendations")
        if isinstance(recs, list) and recs:
            return {"summary": str(data.get("summary", "")), "recommendations": recs[:6]}
    except Exception:
        return None
    return None


def embed(label: str) -> list[float] | None:
    """No local embedding model is used; merge relies on model context + labels."""
    return None
