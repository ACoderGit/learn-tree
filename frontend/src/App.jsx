import { Component, useEffect, useMemo, useRef, useState } from "react";
import Graph from "./Graph.jsx";
import {
  addNode,
  addSource,
  clearGraph,
  createPlane,
  deletePlane,
  deleteNode,
  fetchGraph,
  fetchStatus,
  loadDemo,
  recommend,
  renameNode,
  reviewNode,
  selectPlane,
  setNodeLevel,
  setTime,
} from "./api.js";

const PROVIDER_LABEL = {
  anthropic: "Claude",
  openai: "OpenAI",
  heuristic: "Keyword mode",
  offline: "Backend offline",
  unknown: "…",
};

// Keeps a rare render error in the canvas from blanking the whole app.
class GraphBoundary extends Component {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidUpdate(prev) {
    if (prev.data !== this.props.data && this.state.failed) {
      this.setState({ failed: false });
    }
  }
  render() {
    if (this.state.failed) {
      return (
        <div className="empty">
          <p>Couldn't draw the graph.</p>
          <p className="hint">Add another source to redraw.</p>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  const [graph, setGraph] = useState({ nodes: [], links: [], dueReviews: [] });
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [provider, setProvider] = useState("unknown");
  const [selected, setSelected] = useState(null);
  const [renameValue, setRenameValue] = useState("");
  const [recs, setRecs] = useState(null);
  const [recLoading, setRecLoading] = useState(false);
  const [recError, setRecError] = useState("");
  const [recOptions, setRecOptions] = useState({
    mode: "niche_down",
    format: "mixed",
    timeBudget: "1-2 hours",
    interest: "",
  });
  const [focusIds, setFocusIds] = useState([]);
  const [activeTab, setActiveTab] = useState("review");
  const [timeDraft, setTimeDraft] = useState(null); // slider thumb while dragging
  const [visualOptions, setVisualOptions] = useState({
    labels: "balanced",
    aging: "cracks",
    texture: true,
  });
  const [search, setSearch] = useState("");
  const [centerNodeId, setCenterNodeId] = useState(null);
  const [showView, setShowView] = useState(true);
  const [showLegend, setShowLegend] = useState(true);

  const timeOffset = Math.round(graph.timeOffsetDays || 0);

  useEffect(() => {
    fetchGraph().then(setGraph).catch(() => {});
    fetchStatus().then((s) => setProvider(s.provider));
  }, []);

  // Escape closes the recommendation modal.
  useEffect(() => {
    if (!recs) return;
    const onKey = (e) => e.key === "Escape" && setRecs(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [recs]);

  const selectedNode = selected
    ? graph.nodes.find((n) => n.id === selected)
    : null;
  const childNodes = selectedNode ? childrenOf(graph, selectedNode.id) : [];
  const relatedSources = selectedNode ? sourcesFor(graph, selectedNode.id) : [];

  useEffect(() => {
    setRenameValue(selectedNode ? selectedNode.label : "");
  }, [selected]); // eslint-disable-line react-hooks/exhaustive-deps

  const sourceCount = useMemo(
    () => new Set(graph.nodes.flatMap((n) => n.sources || [])).size,
    [graph.nodes]
  );

  const searchMatches = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return [];
    return graph.nodes
      .filter((n) => n.label.toLowerCase().includes(q))
      .sort((a, b) => (a.level ?? 1) - (b.level ?? 1) || a.label.localeCompare(b.label))
      .slice(0, 8);
  }, [search, graph.nodes]);

  async function run(fn) {
    setError("");
    try {
      setGraph(await fn());
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleAdd(e) {
    e.preventDefault();
    if (!url.trim() || loading) return;
    setLoading(true);
    setError("");
    try {
      const res = await addSource(url);
      setGraph(res.graph);
      setProvider(res.provider);
      setUrl("");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function handleClear() {
    if (window.confirm("Clear the entire knowledge tree? This can't be undone.")) {
      setSelected(null);
      setFocusIds([]);
      run(() => clearGraph());
    }
  }

  function resetPlaneView() {
    setSelected(null);
    setFocusIds([]);
    setSearch("");
    setCenterNodeId(null);
    setRecs(null);
  }

  function handleSelectPlane(name) {
    if (!name || name === graph.plane) return;
    resetPlaneView();
    run(() => selectPlane(name));
  }

  function handleCreatePlane() {
    const name = window.prompt("New graph / plane name:");
    if (!name?.trim()) return;
    resetPlaneView();
    run(() => createPlane(name.trim()));
  }

  function handleDeletePlane() {
    if ((graph.planes || []).length <= 1) return;
    const name = graph.plane || "Main";
    if (!window.confirm(`Delete the "${name}" plane?`)) return;
    resetPlaneView();
    run(() => deletePlane(name));
  }

  function handleAddTopic() {
    const name = window.prompt("New domain / top-level topic:");
    if (name && name.trim()) run(() => addNode(name.trim(), 0, null));
  }

  function handleAddChild() {
    if (!selectedNode) return;
    const name = window.prompt(`Add a subtopic under "${selectedNode.label}":`);
    if (name && name.trim()) {
      const level = Math.min((selectedNode.level ?? 0) + 1, 2);
      run(() => addNode(name.trim(), level, selectedNode.id));
    }
  }

  function handleRename() {
    if (!selectedNode || !renameValue.trim()) return;
    if (renameValue.trim() === selectedNode.label) return;
    run(() => renameNode(selectedNode.id, renameValue.trim()));
  }

  function handleDelete() {
    if (!selectedNode) return;
    if (window.confirm(`Delete "${selectedNode.label}"?`)) {
      const id = selectedNode.id;
      setSelected(null);
      setFocusIds((ids) => ids.filter((x) => x !== id));
      run(() => deleteNode(id));
    }
  }

  function handleSetLevel(nextLevel) {
    if (!selectedNode) return;
    run(() => setNodeLevel(selectedNode.id, nextLevel));
  }

  function handleNodeClick(node) {
    setCenterNodeId(null);
    if (!node) {
      setSelected(null);
      return;
    }
    setSelected(node.id);
    setActiveTab("add");
  }

  function toggleFocus(id) {
    setFocusIds((ids) =>
      ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id].slice(-4)
    );
  }

  function updateRecOption(key, value) {
    setRecOptions((opts) => ({ ...opts, [key]: value }));
  }

  function updateVisualOption(key, value) {
    setVisualOptions((opts) => ({ ...opts, [key]: value }));
  }

  async function handleRecommend() {
    if (recLoading || graph.nodes.length === 0) return;
    setRecLoading(true);
    setRecError("");
    setRecs(null);
    try {
      setRecs(await recommend({ ...recOptions, nodeIds: focusIds }));
    } catch (err) {
      setRecError(err.message);
    } finally {
      setRecLoading(false);
    }
  }

  function handleLoadDemo() {
    run(() => loadDemo());
  }

  // Persisted through the backend so review state survives a reload.
  function handleReview(id) {
    if (!id) return;
    run(() => reviewNode(id));
  }

  async function handleExploreSelected() {
    if (!selectedNode) return;
    const nextFocus = focusIds.includes(selectedNode.id)
      ? focusIds
      : [...focusIds, selectedNode.id].slice(-4);
    const nextOptions = {
      ...recOptions,
      mode: "niche_down",
      interest: recOptions.interest || `I want to learn more about ${selectedNode.label}.`,
    };
    setFocusIds(nextFocus);
    setRecOptions(nextOptions);
    setActiveTab("next");
    setRecLoading(true);
    setRecError("");
    setRecs(null);
    try {
      setRecs(await recommend({ ...nextOptions, nodeIds: nextFocus }));
    } catch (err) {
      setRecError(err.message);
    } finally {
      setRecLoading(false);
    }
  }

  // Time is persisted on the backend, which recomputes decay/review state.
  function commitTime(days) {
    const target = Math.max(0, Math.round(Number(days) || 0));
    setTimeDraft(null);
    run(() => setTime(target));
  }

  function goToNode(id) {
    setSelected(id);
    setActiveTab("add");
    setCenterNodeId(null);
    // Force the effect to re-run even when re-selecting the same node.
    requestAnimationFrame(() => setCenterNodeId(id));
    setSearch("");
  }

  function showHome() {
    setSelected(null);
    setActiveTab("add");
  }

  const tabs = [
    { key: "add", label: "Add" },
    { key: "next", label: "What's Next" },
    { key: "review", label: "Review" },
  ];

  return (
    <div className="app">
      <aside className="sidebar">
        <button className="brand brand-button" onClick={showHome}>
          <span className="logo">🌳</span>
          <div>
            <h1>Tree</h1>
            <p className="tagline">Everything you've learned, mapped.</p>
          </div>
        </button>

        <div className="plane-switcher">
          <label>
            Plane
            <select
              value={graph.plane || "Main"}
              onChange={(e) => handleSelectPlane(e.target.value)}
            >
              {(graph.planes?.length ? graph.planes : [{ name: graph.plane || "Main", nodes: graph.nodes.length }]).map((plane) => (
                <option key={plane.name} value={plane.name}>
                  {plane.name} ({plane.nodes})
                </option>
              ))}
            </select>
          </label>
          <button type="button" title="New plane" onClick={handleCreatePlane}>+</button>
          <button
            type="button"
            title="Delete current plane"
            onClick={handleDeletePlane}
            disabled={(graph.planes || []).length <= 1}
          >
            -
          </button>
        </div>

        <div className="tabs">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              className={activeTab === tab.key ? "active" : ""}
              onClick={() => setActiveTab(tab.key)}
            >
              {tab.label}
              {tab.key === "review" && graph.dueReviews?.length > 0 && (
                <span className="tab-badge">{graph.dueReviews.length}</span>
              )}
            </button>
          ))}
        </div>

        {activeTab === "add" && (
          <div className="tab-panel">
            {selectedNode ? (
              <NodeConsole
                node={selectedNode}
                renameValue={renameValue}
                setRenameValue={setRenameValue}
                onRename={handleRename}
                onBack={showHome}
                onAddChild={handleAddChild}
                onToggleFocus={() => toggleFocus(selectedNode.id)}
                focused={focusIds.includes(selectedNode.id)}
                onExplore={handleExploreSelected}
                onReview={() => handleReview(selectedNode.id)}
                onPromote={() => handleSetLevel((selectedNode.level ?? 1) - 1)}
                onDemote={() => handleSetLevel((selectedNode.level ?? 1) + 1)}
                onDelete={handleDelete}
                childNodes={childNodes}
                relatedSources={relatedSources}
                onSelectChild={(id) => setSelected(id)}
              />
            ) : (
              <>
                <form className="add-form" onSubmit={handleAdd}>
                  <textarea
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    placeholder="Paste an article, YouTube, or course URL...&#10;(one per line to batch)"
                    rows={3}
                    disabled={loading}
                  />
                  <button type="submit" disabled={loading || !url.trim()}>
                    {loading ? "Mapping…" : "Add to tree"}
                  </button>
                  {error && <p className="error">{error}</p>}
                  <p className="form-hint">
                    Each link is scraped, its key topics extracted, and merged into
                    the graph below.
                  </p>
                </form>
                <div className="sidebar-actions">
                  <button className="btn-sec" onClick={handleAddTopic}>+ Add topic</button>
                  <button className="btn-sec danger" onClick={handleClear} disabled={graph.nodes.length === 0}>
                    Clear all
                  </button>
                </div>
                <div className="stats">
                  <div className="stat">
                    <span className="num">{graph.nodes.length}</span>
                    <span className="label">topics</span>
                  </div>
                  <div className="stat">
                    <span className="num">{sourceCount}</span>
                    <span className="label">sources</span>
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {activeTab === "next" && (
          <div className="tab-panel">
            <section className="next-panel">
              <div className="panel-title">Recommendation setup</div>
              <select value={recOptions.mode} onChange={(e) => updateRecOption("mode", e.target.value)}>
                <option value="niche_down">Niche down on focus</option>
                <option value="connect_topics">Connect chosen topics</option>
                <option value="completely_new">Something completely new</option>
                <option value="review">Review what is fading</option>
              </select>
              <div className="split">
                <select value={recOptions.format} onChange={(e) => updateRecOption("format", e.target.value)}>
                  <option value="mixed">Mixed</option>
                  <option value="project">Project</option>
                  <option value="course">Course</option>
                  <option value="video">Video</option>
                </select>
                <select value={recOptions.timeBudget} onChange={(e) => updateRecOption("timeBudget", e.target.value)}>
                  <option value="15-30 minutes">15-30 min</option>
                  <option value="1-2 hours">1-2 hours</option>
                  <option value="one weekend">Weekend</option>
                  <option value="2-4 weeks">2-4 weeks</option>
                </select>
              </div>
              <div className="panel-title">Anything specific?</div>
              <textarea
                value={recOptions.interest}
                onChange={(e) => updateRecOption("interest", e.target.value)}
                placeholder="Describe the area, project, or skill you want recommendations for..."
                rows={2}
              />
              <div className="panel-title">
                Focus topics {focusIds.length > 0 && <span className="muted-count">({focusIds.length}/4)</span>}
              </div>
              <div className="focus-picker">
                {graph.nodes.filter((n) => !n.anchor).slice()
                  .sort((a, b) => (b.count || 1) - (a.count || 1)).slice(0, 12).map((n) => (
                    <button
                      type="button"
                      key={n.id}
                      className={focusIds.includes(n.id) ? "chip active" : "chip"}
                      onClick={() => toggleFocus(n.id)}
                    >
                      {n.label}
                    </button>
                  ))}
                {graph.nodes.length === 0 && (
                  <p className="form-hint">Add some topics first, then get tailored suggestions.</p>
                )}
              </div>
            </section>
            <button className="btn-next" onClick={handleRecommend} disabled={recLoading || graph.nodes.length === 0}>
              {recLoading ? "Thinking…" : "Get recommendations"}
            </button>
            {recError && <p className="error">{recError}</p>}
            {provider !== "anthropic" && graph.nodes.length > 0 && (
              <p className="form-hint">Recommendations need the Claude engine (set ANTHROPIC_API_KEY).</p>
            )}
          </div>
        )}

        {activeTab === "review" && (
          <div className="tab-panel">
            <section className="review-panel">
              <div className="panel-title">Due for review</div>
              {graph.dueReviews?.length > 0 ? (
                <div className="review-list">
                  {graph.dueReviews.map((n) => (
                    <div className="review-row" key={n.id}>
                      <button className="review-name" onClick={() => goToNode(n.id)}>
                        {n.label}
                        <span className="review-age">{Math.round(n.ageDays)}d</span>
                      </button>
                      <button
                        className="review-done"
                        title="Mark reviewed"
                        onClick={() => handleReview(n.id)}
                      >
                        ✓
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="form-hint">
                  Nothing fading right now. Topics you haven't revisited in a while
                  will surface here.
                </p>
              )}
            </section>

            <section className="time-machine">
              <div className="panel-title">Time machine</div>
              <p className="form-hint">
                Fast-forward to see how confidence fades without review.
              </p>
              <div className="time-value">+{timeDraft ?? timeOffset} days</div>
              <input
                type="range"
                min="0"
                max="120"
                value={timeDraft ?? timeOffset}
                onChange={(e) => setTimeDraft(Number(e.target.value))}
                onMouseUp={(e) => commitTime(e.target.value)}
                onTouchEnd={(e) => commitTime(e.target.value)}
                onKeyUp={(e) => commitTime(e.target.value)}
              />
              <div className="sidebar-actions">
                <button className="btn-sec" onClick={() => commitTime(timeOffset + 7)}>+7 days</button>
                <button className="btn-sec" onClick={() => commitTime(timeOffset + 30)}>+30 days</button>
                <button className="btn-sec" onClick={() => commitTime(0)} disabled={timeOffset === 0}>
                  Reset
                </button>
              </div>
            </section>

            {graph.nodes.length === 0 && (
              <button className="btn-sec" onClick={handleLoadDemo}>Load demo data</button>
            )}
          </div>
        )}

        <div className="provider">
          Engine: <strong>{PROVIDER_LABEL[provider] || provider}</strong>
        </div>
      </aside>

      <main className="stage">
        {graph.nodes.length === 0 ? (
          <div className="empty">
            <div className="empty-logo">🌳</div>
            <p>Your knowledge tree is empty.</p>
            <p className="hint">Paste a link on the left to plant the first branch — or explore a ready-made tree.</p>
            <button className="empty-cta" onClick={handleLoadDemo}>Load demo data</button>
          </div>
        ) : (
          <>
            <div className="graph-toolbar">
              <div className="search-box">
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search topics…"
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && searchMatches[0]) goToNode(searchMatches[0].id);
                    if (e.key === "Escape") setSearch("");
                  }}
                />
                {searchMatches.length > 0 && (
                  <div className="search-results">
                    {searchMatches.map((n) => (
                      <button key={n.id} onClick={() => goToNode(n.id)}>
                        <span>{n.label}</span>
                        <small>L{n.level ?? 1}</small>
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <div className="toolbar-buttons">
                <div className="toolbar-menu">
                  <button
                    className={`icon-btn ${showView ? "active" : ""}`}
                    title="View options"
                    onClick={() => { setShowView((v) => !v); setShowLegend(false); }}
                  >
                    ⚙
                  </button>
                  {showView && (
                    <div className="popover">
                      <label>
                        Labels
                        <select value={visualOptions.labels} onChange={(e) => updateVisualOption("labels", e.target.value)}>
                          <option value="balanced">Balanced</option>
                          <option value="dense">More names</option>
                        </select>
                      </label>
                      <label>
                        Aging
                        <select value={visualOptions.aging} onChange={(e) => updateVisualOption("aging", e.target.value)}>
                          <option value="cracks">Cracked</option>
                          <option value="grey">Grey only</option>
                          <option value="none">Off</option>
                        </select>
                      </label>
                      <label className="toggle-row">
                        Texture
                        <input
                          type="checkbox"
                          checked={visualOptions.texture}
                          onChange={(e) => updateVisualOption("texture", e.target.checked)}
                        />
                      </label>
                    </div>
                  )}
                </div>
                <button
                  className={`icon-btn ${showLegend ? "active" : ""}`}
                  title="Legend"
                  onClick={() => { setShowLegend((v) => !v); setShowView(false); }}
                >
                  ?
                </button>
              </div>
            </div>

            {showLegend && (
              <div className="legend">
                <div className="legend-title">Reading the map</div>
                <div className="legend-row"><span className="sw sw-size" /> Size = how central / reinforced a topic is</div>
                <div className="legend-row"><span className="sw sw-ramp" /> Color = confidence (few → many sources)</div>
                <div className="legend-row"><span className="sw sw-stale" /> Grey &amp; cracked = fading, due for review</div>
                <div className="legend-row"><span className="sw sw-ring" /> Ringed nodes = domains &amp; main topics</div>
              </div>
            )}

            <GraphBoundary data={graph}>
              <Graph
                data={graph}
                selectedId={selected}
                onNodeClick={handleNodeClick}
                visualOptions={visualOptions}
                centerNodeId={centerNodeId}
              />
            </GraphBoundary>
          </>
        )}

        {recs && (
          <div className="rec-overlay" onClick={() => setRecs(null)}>
            <div className="rec-card" onClick={(e) => e.stopPropagation()}>
              <button className="rec-close" onClick={() => setRecs(null)}>×</button>
              <h2>What's next?</h2>
              {recs.summary && <p className="rec-summary">{recs.summary}</p>}
              <div className="rec-list">
                {recs.recommendations.map((r, i) => (
                  <div className="rec-item" key={i}>
                    <span className={`rec-type ${r.type}`}>{r.type}</span>
                    <div className="rec-body">
                      <div className="rec-title">{r.title}</div>
                      {r.where && <div className="rec-where">{r.where}</div>}
                      {r.time && <div className="rec-time">{r.time}</div>}
                      <div className="rec-why">{r.why}</div>
                      <a
                        className="rec-search"
                        href={searchUrl(r)}
                        target="_blank"
                        rel="noreferrer"
                      >
                        🔍 {r.search}
                      </a>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

function hostname(u) {
  try {
    return new URL(u).hostname.replace(/^www\./, "");
  } catch {
    return u;
  }
}

function NodeConsole({
  node,
  renameValue,
  setRenameValue,
  onRename,
  onBack,
  onAddChild,
  onToggleFocus,
  focused,
  onExplore,
  onReview,
  onPromote,
  onDemote,
  onDelete,
  childNodes,
  relatedSources,
  onSelectChild,
}) {
  const sourceCount = node.sources?.length ?? node.count ?? 0;
  const confidence = node.confidencePercent ?? (sourceCount <= 0
    ? 0
    : Math.round((0.25 + (Math.min(sourceCount, 4) - 1) * 0.25) * 100));
  const stale = node.reviewDue || (node.ageDays ?? 0) >= 7;
  return (
    <div className="node-console">
      <button className="console-back" onClick={onBack}>← All topics</button>
      <div className="rename title-edit">
        <input
          value={renameValue}
          onChange={(e) => setRenameValue(e.target.value)}
          onBlur={onRename}
          onKeyDown={(e) => {
            if (e.key === "Enter") e.currentTarget.blur();
          }}
        />
      </div>
      {node.summary && <p className="summary">{node.summary}</p>}
      <div className="console-stats">
        <div>
          <span>{confidence}%</span>
          <small>confidence</small>
        </div>
        <div className={stale ? "stat-warn" : ""}>
          <span>{Math.round(node.ageDays || 0)}d</span>
          <small>since seen</small>
        </div>
        <div>
          <span>{relatedSources.length}</span>
          <small>sources</small>
        </div>
      </div>
      {stale && (
        <div className="stale-note">This topic is fading — mark it reviewed to refresh it.</div>
      )}
      {relatedSources.length > 0 && (
        <div className="source-list">
          <div className="panel-title">Sources</div>
          {relatedSources.map((s) => (
            <a key={s} href={s} target="_blank" rel="noreferrer">
              {hostname(s)}
            </a>
          ))}
        </div>
      )}
      {childNodes.length > 0 && (
        <div className="subtopics">
          <div className="panel-title">Subtopics</div>
          {childNodes.map((n) => (
            <button key={n.id} onClick={() => onSelectChild(n.id)}>
              {n.label}
            </button>
          ))}
        </div>
      )}
      <div className="console-actions">
        <button className="btn-sec" onClick={onAddChild}>+ Subtopic</button>
        <button className="btn-sec" onClick={onToggleFocus}>
          {focused ? "Unfocus" : "Focus"}
        </button>
        <button className="btn-sec" onClick={onExplore}>Explore</button>
        <button className="btn-sec" onClick={onReview}>Mark reviewed</button>
        <button className="btn-sec" onClick={onPromote} disabled={(node.level ?? 1) <= 0}>
          Promote
        </button>
        <button className="btn-sec" onClick={onDemote} disabled={(node.level ?? 1) >= 2}>
          Demote
        </button>
      </div>
      <button className="btn-sec danger full" onClick={onDelete}>Remove topic</button>
    </div>
  );
}

function linkId(value) {
  return typeof value === "object" ? value.id : value;
}

function childrenOf(graph, parentId) {
  const childIds = new Set(
    graph.links
      .filter((l) => linkId(l.source) === parentId)
      .map((l) => linkId(l.target))
  );
  return graph.nodes
    .filter((n) => childIds.has(n.id))
    .sort((a, b) => (a.level ?? 1) - (b.level ?? 1) || a.label.localeCompare(b.label));
}

function descendantIds(graph, rootId) {
  const ids = new Set([rootId]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const link of graph.links) {
      const source = linkId(link.source);
      const target = linkId(link.target);
      if (ids.has(source) && !ids.has(target)) {
        ids.add(target);
        changed = true;
      }
    }
  }
  return ids;
}

function sourcesFor(graph, rootId) {
  const ids = descendantIds(graph, rootId);
  return [
    ...new Set(
      graph.nodes
        .filter((n) => ids.has(n.id))
        .flatMap((n) => n.sources || [])
    ),
  ];
}

// Videos search YouTube; everything else goes to Google.
function searchUrl(r) {
  const q = encodeURIComponent(r.search || r.title);
  return r.type === "video"
    ? `https://www.youtube.com/results?search_query=${q}`
    : `https://www.google.com/search?q=${q}`;
}
