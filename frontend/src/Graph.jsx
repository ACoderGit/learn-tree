import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";

// HSL -> RGB (CSS spec algorithm) so the confidence ramp stays vivid across
// its whole range instead of muddying through the middle.
function hslToRgb(h, s, l) {
  h = (h / 360) % 1;
  const a = s * Math.min(l, 1 - l);
  const f = (n) => {
    const k = (n + h * 12) % 12;
    return Math.round(255 * (l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1))));
  };
  return [f(0), f(8), f(4)];
}

// Confidence ramp: orange -> dark green. Saturates at 4 direct sources.
function confidenceRGB(count) {
  const countValue = count || 0;
  const t = Math.min(countValue, 4) / 4;
  return hslToRgb(26 + (120 - 26) * t, 0.66 - t * 0.08, 0.43 - t * 0.11);
}

function colorConfidenceFor(node) {
  return node.sources?.length || node.count || node.visualCount || 0;
}

function drawWrappedLabel(ctx, text, x, y, maxWidth, lineHeight) {
  const words = String(text).split(/\s+/);
  const lines = [];
  let line = "";
  for (const word of words) {
    const next = line ? `${line} ${word}` : word;
    if (ctx.measureText(next).width > maxWidth && line) {
      lines.push(line);
      line = word;
    } else {
      line = next;
    }
  }
  if (line) lines.push(line);
  lines.slice(0, 3).forEach((l, i) => ctx.fillText(l, x, y + i * lineHeight));
}

function wrappedLines(ctx, text, maxWidth) {
  const words = String(text).split(/\s+/);
  const lines = [];
  let line = "";
  for (const word of words) {
    const next = line ? `${line} ${word}` : word;
    if (ctx.measureText(next).width > maxWidth && line) {
      lines.push(line);
      line = word;
    } else {
      line = next;
    }
  }
  if (line) lines.push(line);
  return lines;
}

function drawFittedCenteredLabel(ctx, text, x, y, maxWidth, maxHeight, baseSize, weight, minSize = 5) {
  let fontSize = baseSize;
  let lines = [];
  do {
    ctx.font = `${weight} ${fontSize}px Inter, system-ui, sans-serif`;
    lines = wrappedLines(ctx, text, maxWidth).slice(0, 3);
    const widest = Math.max(...lines.map((line) => ctx.measureText(line).width), 0);
    if (lines.length * fontSize * 1.12 <= maxHeight && widest <= maxWidth) break;
    fontSize -= 1;
  } while (fontSize > minSize);
  const lineHeight = fontSize * 1.12;
  const startY = y - ((lines.length - 1) * lineHeight) / 2;
  lines.forEach((line, i) => ctx.fillText(line, x, startY + i * lineHeight));
}

function drawFixedCenteredLabel(ctx, text, x, y, maxWidth, maxHeight, fontSize, weight) {
  ctx.font = `${weight} ${fontSize}px Inter, system-ui, sans-serif`;
  let lines = wrappedLines(ctx, text, maxWidth).slice(0, 3);
  let effectiveSize = fontSize;
  const widest = () => Math.max(...lines.map((line) => ctx.measureText(line).width), 0);
  while (
    effectiveSize > 8 &&
    (lines.length * effectiveSize * 1.12 > maxHeight || widest() > maxWidth)
  ) {
    effectiveSize -= 1;
    ctx.font = `${weight} ${effectiveSize}px Inter, system-ui, sans-serif`;
    lines = wrappedLines(ctx, text, maxWidth).slice(0, 3);
  }
  const lineHeight = effectiveSize * 1.12;
  const startY = y - ((lines.length - 1) * lineHeight) / 2;
  lines.forEach((line, i) => ctx.fillText(line, x, startY + i * lineHeight));
}

export default function Graph({ data, onNodeClick, selectedId, visualOptions, centerNodeId }) {
  const fgRef = useRef();
  const wrapRef = useRef();
  const [size, setSize] = useState({ width: 800, height: 600 });
  const options = {
    labels: "balanced",
    aging: "cracks",
    texture: true,
    ...(visualOptions || {}),
  };

  // react-force-graph mutates node objects, so hand it fresh copies.
  const graphData = useMemo(
    () => {
      const anchors = data.nodes
        .filter((n) => n.anchor || n.level === 0)
        .slice()
        .sort((a, b) => a.label.localeCompare(b.label));
      const anchorPos = {};
      const cols = Math.ceil(Math.sqrt(Math.max(anchors.length, 1) * 1.35));
      const rows = Math.ceil(Math.max(anchors.length, 1) / cols);
      const spreadX = Math.max(1050, size.width * 1.65);
      const spreadY = Math.max(780, size.height * 1.45);
      const cellW = cols > 1 ? spreadX / (cols - 1) : 0;
      const cellH = rows > 1 ? spreadY / (rows - 1) : 0;
      anchors.forEach((node, i) => {
        const row = Math.floor(i / cols);
        const col = i % cols;
        const stagger = row % 2 ? cellW * 0.16 : -cellW * 0.08;
        const jitterX = ((i * 37) % 23 - 11) * 1.8;
        const jitterY = ((i * 53) % 19 - 9) * 1.8;
        anchorPos[node.id] = {
          x: (cols === 1 ? 0 : -spreadX / 2 + col * cellW + stagger) + jitterX,
          y: (rows === 1 ? 0 : -spreadY / 2 + row * cellH) + jitterY,
        };
      });
      return {
        nodes: data.nodes.map((n) => ({
          ...n,
          ...(anchorPos[n.id] && n.x == null && n.y == null ? anchorPos[n.id] : {}),
        })),
        links: data.links.map((l) => ({ ...l })),
      };
    },
    [data, size.width, size.height]
  );

  const maxSeq = useMemo(
    () => Math.max(1, ...graphData.nodes.map((n) => n.seq || 0)),
    [graphData]
  );
  const childCounts = useMemo(() => {
    const counts = {};
    for (const link of graphData.links) {
      const source = typeof link.source === "object" ? link.source.id : link.source;
      counts[source] = (counts[source] || 0) + 1;
    }
    return counts;
  }, [graphData]);
  const nodeById = useMemo(
    () => Object.fromEntries(graphData.nodes.map((n) => [n.id, n])),
    [graphData]
  );
  const rootByNode = useMemo(() => {
    const parentByTarget = {};
    for (const link of graphData.links) {
      const source = typeof link.source === "object" ? link.source.id : link.source;
      const target = typeof link.target === "object" ? link.target.id : link.target;
      parentByTarget[target] = source;
    }
    const roots = {};
    for (const node of graphData.nodes) {
      let cur = node.id;
      const seen = new Set();
      while (parentByTarget[cur] && !seen.has(cur)) {
        seen.add(cur);
        cur = parentByTarget[cur];
      }
      roots[node.id] = nodeById[cur]?.anchor ? cur : node.id;
    }
    return roots;
  }, [graphData, nodeById]);
  const descendantsByNode = useMemo(() => {
    const children = {};
    for (const link of graphData.links) {
      const source = typeof link.source === "object" ? link.source.id : link.source;
      const target = typeof link.target === "object" ? link.target.id : link.target;
      if (!children[source]) children[source] = [];
      children[source].push(target);
    }
    const descendants = {};
    for (const node of graphData.nodes) {
      const ids = [];
      const queue = [...(children[node.id] || [])];
      const seen = new Set();
      while (queue.length) {
        const id = queue.shift();
        if (seen.has(id)) continue;
        seen.add(id);
        ids.push(id);
        queue.push(...(children[id] || []));
      }
      descendants[node.id] = ids;
    }
    return descendants;
  }, [graphData]);
  const childrenByNode = useMemo(() => {
    const children = {};
    for (const link of graphData.links) {
      const source = typeof link.source === "object" ? link.source.id : link.source;
      const target = typeof link.target === "object" ? link.target.id : link.target;
      if (!children[source]) children[source] = [];
      children[source].push(target);
    }
    return children;
  }, [graphData]);
  const linkedPairs = useMemo(() => {
    const pairs = new Set();
    for (const link of graphData.links) {
      const source = typeof link.source === "object" ? link.source.id : link.source;
      const target = typeof link.target === "object" ? link.target.id : link.target;
      pairs.add([source, target].sort().join("::"));
    }
    return pairs;
  }, [graphData]);

  // Size = importance. Broad/main topics (low level) are biggest; reinforced
  // topics grow; older topics (smaller seq) get a small bonus.
  const radiusFor = (node) => {
    const level = Math.min(node.level ?? 1, 2);
    const hasChildren = Boolean(childCounts[node.id]);
    const base = node.anchor ? 18 : level === 1 ? (hasChildren ? 16 : 13) : 7.2;
    const countBoost = Math.sqrt(node.count || 1) * (level === 2 ? 1.25 : 1.8);
    const ageBoost = (1 - (node.seq || maxSeq) / maxSeq) * 2;
    return base + countBoost + ageBoost;
  };
  const ringRadiusFor = (node) => {
    if (node.anchor) return Math.max(92, 70 + Math.sqrt(childCounts[node.id] || 1) * 16);
    if ((node.level ?? 2) === 1 && childCounts[node.id]) {
      return Math.max(30, 22 + Math.sqrt(childCounts[node.id]) * 7);
    }
    return radiusFor(node);
  };
  const resolveNode = (node) => typeof node === "object" ? node : nodeById[node];
  const visualImportance = (node) => {
    node = resolveNode(node);
    if (!node) return 0;
    return (node.anchor ? 3 : 0) + (node.level === 1 ? 2 : 0) + Math.min(node.visualCount ?? node.count ?? 1, 4);
  };
  const highLevelLink = (link) => {
    const source = resolveNode(link.source);
    const target = resolveNode(link.target);
    return Boolean(
      (source?.anchor && target?.level === 1) ||
      (target?.anchor && source?.level === 1)
    );
  };
  const smallestNodeLink = (link) => {
    const source = resolveNode(link.source);
    const target = resolveNode(link.target);
    return Boolean((source?.level ?? 0) >= 2 || (target?.level ?? 0) >= 2);
  };
  const importantLink = (link) =>
    !smallestNodeLink(link) && !highLevelLink(link) && visualImportance(link.source) >= 5 && visualImportance(link.target) >= 4;

  const linkWeight = (link) => {
    if (smallestNodeLink(link)) return 1.2;
    if (highLevelLink(link)) return 3.2;
    if (importantLink(link)) return 2.6;
    if (link.kind === "strong") return 2.1;
    if (link.kind === "weak") return 0.8;
    return 1.2;
  };

  // Tune the force simulation so the hierarchy reads as a tree.
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    fg.d3Force("charge").strength((n) => {
      if (n.anchor) return -285;
      if ((n.level ?? 2) === 1) return -160;
      return -62;
    }).distanceMax(620);
    fg.d3Force("center").strength(0.16);
    fg.d3Force("link")
      .distance((l) => {
        if (smallestNodeLink(l)) return 100;
        if (l.kind === "weak") return 375;
        if (highLevelLink(l)) return 330;
        const lvl = Math.min(l.source.level ?? 1, l.target.level ?? 1);
        if ((l.source.level ?? 1) >= 1 && (l.target.level ?? 1) >= 2) return 100;
        return importantLink(l) ? 320 : 208 + lvl * 34;
      })
      .strength((l) => {
        if (smallestNodeLink(l)) return 0.42;
        if (l.kind === "weak") return 0.08;
        if (highLevelLink(l)) return 0.42;
        if ((l.source.level ?? 1) >= 1 && (l.target.level ?? 1) >= 2) return 0.44;
        return importantLink(l) ? 0.24 : 0.28;
      });
    fg.d3ReheatSimulation();
    const settle = setTimeout(() => {
      fg.d3Force("center")?.strength(0.035);
      fg.d3ReheatSimulation();
    }, 2200);
    return () => clearTimeout(settle);
  }, [graphData, childCounts, nodeById]);

  const linkEnds = (link) => {
    const source = resolveNode(link.source);
    const target = resolveNode(link.target);
    if (!source || !target) return null;
    if (![source.x, source.y, target.x, target.y].every(Number.isFinite)) return null;
    return { source, target, ax: source.x, ay: source.y, bx: target.x, by: target.y };
  };

  const ccw = (a, b, c) => (c.y - a.y) * (b.x - a.x) > (b.y - a.y) * (c.x - a.x);
  const segmentsCross = (a, b) => {
    const p1 = { x: a.ax, y: a.ay };
    const p2 = { x: a.bx, y: a.by };
    const p3 = { x: b.ax, y: b.ay };
    const p4 = { x: b.bx, y: b.by };
    return ccw(p1, p3, p4) !== ccw(p2, p3, p4) && ccw(p1, p2, p3) !== ccw(p1, p2, p4);
  };

  const repelCrossingLinks = () => {
    const links = graphData.links;
    for (let i = 0; i < links.length; i += 1) {
      const a = linkEnds(links[i]);
      if (!a) continue;
      for (let j = i + 1; j < links.length; j += 1) {
        const b = linkEnds(links[j]);
        if (!b) continue;
        const shared =
          a.source.id === b.source.id ||
          a.source.id === b.target.id ||
          a.target.id === b.source.id ||
          a.target.id === b.target.id;
        if (shared || !segmentsCross(a, b)) continue;

        const weight = Math.min(7, linkWeight(links[i]) + linkWeight(links[j]));
        const dx = a.bx - a.ax;
        const dy = a.by - a.ay;
        const len = Math.sqrt(dx * dx + dy * dy) || 1;
        const nx = -dy / len;
        const ny = dx / len;
        const push = 0.18 * weight;
        for (const node of [a.source, a.target]) {
          if ((node.level ?? 2) === 0) continue;
          node.x += nx * push;
          node.y += ny * push;
        }
        for (const node of [b.source, b.target]) {
          if ((node.level ?? 2) === 0) continue;
          node.x -= nx * push;
          node.y -= ny * push;
        }
      }
    }
  };

  const treeBoundaryForces = () => {
    const groups = {};
    for (const node of graphData.nodes) {
      if (!Number.isFinite(node.x) || !Number.isFinite(node.y)) continue;
      const root = rootByNode[node.id];
      if (!groups[root]) groups[root] = [];
      groups[root].push(node);
    }

    const bounds = Object.entries(groups)
      .map(([root, nodes]) => {
        let minX = Infinity;
        let maxX = -Infinity;
        let minY = Infinity;
        let maxY = -Infinity;
        for (const node of nodes) {
          const r = node.anchor || ((node.level ?? 2) === 1 && childCounts[node.id])
            ? ringRadiusFor(node)
            : radiusFor(node);
          minX = Math.min(minX, node.x - r);
          maxX = Math.max(maxX, node.x + r);
          minY = Math.min(minY, node.y - r);
          maxY = Math.max(maxY, node.y + r);
        }
        const pad = 90;
        minX -= pad;
        maxX += pad;
        minY -= pad;
        maxY += pad;
        return {
          root,
          nodes,
          cx: (minX + maxX) / 2,
          cy: (minY + maxY) / 2,
          halfW: Math.max(120, (maxX - minX) / 2),
          halfH: Math.max(100, (maxY - minY) / 2),
        };
      })
      .filter((b) => b.nodes.length);

    const moveGroup = (group, dx, dy, scale = 1) => {
      for (const node of group.nodes) {
        const weight = node.id === group.root ? 0.38 : (node.level ?? 2) <= 1 ? 0.26 : 0.16;
        node.x += dx * weight * scale;
        node.y += dy * weight * scale;
      }
      group.cx += dx * 0.24 * scale;
      group.cy += dy * 0.24 * scale;
    };

    for (let i = 0; i < bounds.length; i += 1) {
      for (let j = i + 1; j < bounds.length; j += 1) {
        const a = bounds[i];
        const b = bounds[j];
        const dx = b.cx - a.cx || 1;
        const dy = b.cy - a.cy || 0;
        const overlapX = a.halfW + b.halfW - Math.abs(dx);
        const overlapY = a.halfH + b.halfH - Math.abs(dy);
        if (overlapX <= 0 || overlapY <= 0) continue;

        if (overlapX < overlapY) {
          const push = Math.min(8, overlapX * 0.018);
          const sx = Math.sign(dx) || 1;
          moveGroup(a, -sx * push, 0);
          moveGroup(b, sx * push, 0);
        } else {
          const push = Math.min(8, overlapY * 0.018);
          const sy = Math.sign(dy) || 1;
          moveGroup(a, 0, -sy * push);
          moveGroup(b, 0, sy * push);
        }
      }
    }

    for (const group of bounds) {
      const dx = -group.cx;
      const dy = -group.cy;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < 20) continue;
      const pull = Math.min(2.2, dist * 0.0018);
      moveGroup(group, (dx / dist) * pull, (dy / dist) * pull, 0.75);
    }
  };

  const separateOverlaps = () => {
    const nodes = graphData.nodes;
    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        const a = nodes[i];
        const b = nodes[j];
        if (![a.x, a.y, b.x, b.y].every(Number.isFinite)) continue;
        const crossDomain = rootByNode[a.id] !== rootByNode[b.id];
        const sameSmallBranch =
          rootByNode[a.id] === rootByNode[b.id] &&
          (a.level ?? 1) >= 2 &&
          (b.level ?? 1) >= 2;
        const linked = linkedPairs.has([a.id, b.id].sort().join("::"));
        const min = linked
          ? radiusFor(a) + radiusFor(b) + 10
          : ringRadiusFor(a) + ringRadiusFor(b) + (crossDomain ? 48 : sameSmallBranch ? 4 : 14);
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        let dist = Math.sqrt(dx * dx + dy * dy);
        if (!dist) {
          dx = 1;
          dy = 0;
          dist = 1;
        }
        if (dist < min) {
          const push = Math.min(linked ? 1.2 : 3.2, (min - dist) * (linked ? 0.08 : 0.2));
          const ux = dx / dist;
          const uy = dy / dist;
          a.x -= ux * push;
          a.y -= uy * push;
          b.x += ux * push;
          b.y += uy * push;
        }
      }
    }
    treeBoundaryForces();
    repelCrossingLinks();
  };

  const fitView = (duration = 650, padding = 130) => fgRef.current?.zoomToFit(duration, padding);
  useEffect(() => {
    if (graphData.nodes.length === 0) return;
    const t1 = setTimeout(() => fitView(250, 170), 140);
    return () => {
      clearTimeout(t1);
    };
  }, [graphData.nodes.length]);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const update = () =>
      setSize({ width: el.clientWidth, height: el.clientHeight });
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Pan/zoom to a node when the app asks to focus one (e.g. from search).
  useEffect(() => {
    if (!centerNodeId) return;
    const fg = fgRef.current;
    if (!fg) return;
    const focus = () => {
      const node = nodeById[centerNodeId];
      if (!node || !Number.isFinite(node.x) || !Number.isFinite(node.y)) return false;
      fg.centerAt(node.x, node.y, 700);
      fg.zoom(2.4, 700);
      return true;
    };
    if (focus()) return;
    // Node may not be positioned yet on first paint — retry briefly.
    const t = setTimeout(focus, 400);
    return () => clearTimeout(t);
  }, [centerNodeId, nodeById]);

  const drawReviewClouds = (ctx) => {
    if (options.aging === "none") return;
    const candidates = graphData.nodes.filter((node) => {
      const level = node.level ?? 2;
      return (node.anchor || level <= 1) && (descendantsByNode[node.id] || []).length >= 3;
    });

    for (const root of candidates) {
      const ids = [root.id, ...(descendantsByNode[root.id] || [])];
      const branch = ids.map((id) => nodeById[id]).filter(Boolean);
      const staleNodes = branch.filter((n) => !n.anchor && (n.reviewDue || (n.ageDays ?? 0) >= 7));
      if (staleNodes.length < 2 || staleNodes.length / Math.max(1, branch.length - 1) < 0.45) continue;
      const positioned = staleNodes.filter((n) => Number.isFinite(n.x) && Number.isFinite(n.y));
      if (positioned.length < 3) continue;

      let minX = Infinity;
      let maxX = -Infinity;
      let minY = Infinity;
      let maxY = -Infinity;
      for (const node of positioned) {
        const r = node.anchor || ((node.level ?? 2) === 1 && childCounts[node.id])
          ? ringRadiusFor(node)
          : radiusFor(node);
        minX = Math.min(minX, node.x - r);
        maxX = Math.max(maxX, node.x + r);
        minY = Math.min(minY, node.y - r);
        maxY = Math.max(maxY, node.y + r);
      }

      const cx = (minX + maxX) / 2;
      const cy = (minY + maxY) / 2;
      const rx = Math.max(150, (maxX - minX) / 2 + 138);
      const ry = Math.max(120, (maxY - minY) / 2 + 112);
      const cloudR = Math.max(rx, ry);
      const grad = ctx.createRadialGradient(cx, cy, cloudR * 0.12, cx, cy, cloudR);
      grad.addColorStop(0, "rgba(235, 240, 248, 0.015)");
      grad.addColorStop(0.34, "rgba(226, 231, 239, 0.06)");
      grad.addColorStop(0.68, "rgba(174, 183, 196, 0.13)");
      grad.addColorStop(1, "rgba(148, 156, 170, 0)");

      ctx.save();
      ctx.beginPath();
      ctx.ellipse(cx, cy, rx, ry, 0, 0, 2 * Math.PI);
      ctx.fillStyle = grad;
      ctx.fill();
      ctx.globalAlpha = 0.42;
      ctx.beginPath();
      ctx.ellipse(cx - rx * 0.16, cy + ry * 0.08, rx * 0.72, ry * 0.56, -0.18, 0, 2 * Math.PI);
      ctx.fill();
      ctx.beginPath();
      ctx.ellipse(cx + rx * 0.18, cy - ry * 0.1, rx * 0.58, ry * 0.48, 0.22, 0, 2 * Math.PI);
      ctx.fill();
      ctx.restore();
    }
  };

  const drawNode = (node, ctx, globalScale) => {
    if (!Number.isFinite(node.x) || !Number.isFinite(node.y)) return;
    if (!Number.isFinite(globalScale) || globalScale <= 0) globalScale = 1;

    const r = radiusFor(node);
    if (!Number.isFinite(r) || r <= 0) return;
    const [cr, cg, cb] = confidenceRGB(colorConfidenceFor(node));
    const selected = node.id === selectedId;
    const stale = node.reviewDue || (node.ageDays ?? 0) >= 14;
    const ageFade = Math.max(0.45, 1 - Math.min(node.ageDays || 0, 45) / 90);
    const aged = options.aging !== "none" && stale;
    const borderOnly = node.anchor || ((node.level ?? 2) === 1 && childCounts[node.id]);

    if (borderOnly) {
      const ringR = ringRadiusFor(node);
      ctx.beginPath();
      ctx.arc(node.x, node.y, ringR, 0, 2 * Math.PI);
      ctx.lineWidth = (selected ? 3 : node.anchor ? 2.3 : 1.8) / globalScale;
      ctx.strokeStyle = selected
        ? "#ffffff"
        : `rgba(${cr},${cg},${cb},${node.anchor ? 0.88 : 0.7})`;
      ctx.stroke();

      if (node.label) {
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillStyle = "rgba(233,238,247,0.92)";
        const baseSize = node.anchor ? ringR * 0.28 : ringR * 0.32;
        drawFittedCenteredLabel(
          ctx,
          node.label,
          node.x,
          node.y,
          ringR * 1.42,
          ringR * 1.08,
          Math.min(34 / globalScale, Math.max(15 / globalScale, baseSize)),
          node.anchor ? 760 : 680,
          8
        );
      }
      return;
    }

    ctx.beginPath();
    ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
    ctx.fillStyle = aged
      ? `rgba(105,114,128,${0.86 * ageFade})`
      : `rgba(${cr},${cg},${cb},${0.94 * ageFade})`;
    ctx.fill();

    ctx.lineWidth = (selected ? 2.2 : 1.1) / globalScale;
    ctx.strokeStyle = selected
      ? "#ffffff"
      : aged
        ? "rgba(190,198,210,0.74)"
        : `rgba(${cr},${cg},${cb},0.7)`;
    ctx.stroke();
    if (aged && options.aging === "cracks") {
      ctx.save();
      ctx.beginPath();
      ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
      ctx.clip();
      ctx.strokeStyle = "rgba(20,24,31,0.65)";
      ctx.lineWidth = 1.1 / globalScale;
      const cracks = [
        [[-0.45, -0.75], [-0.12, -0.18], [-0.32, 0.24]],
        [[0.18, -0.82], [0.06, -0.16], [0.44, 0.18]],
        [[-0.04, 0.02], [0.18, 0.44], [0.08, 0.78]],
      ];
      for (const crack of cracks) {
        ctx.beginPath();
        crack.forEach(([px, py], i) => {
          const xx = node.x + px * r;
          const yy = node.y + py * r;
          i ? ctx.lineTo(xx, yy) : ctx.moveTo(xx, yy);
        });
        ctx.stroke();
      }
      ctx.restore();
    }
    if (aged && !selected) {
      ctx.beginPath();
      ctx.arc(node.x, node.y, r + 4 / globalScale, 0, 2 * Math.PI);
      ctx.lineWidth = 1 / globalScale;
      ctx.strokeStyle = "rgba(190,198,210,0.28)";
      ctx.stroke();
    }

    const labelThreshold = options.labels === "dense" ? 0.45 : 0.68;
    const showLabel =
      (selected && (node.level ?? 1) < 2) ||
      ((node.level ?? 1) <= 1 && (node.visualCount ?? node.count ?? 1) >= 2 && globalScale > labelThreshold) ||
      (options.labels === "dense" && (node.visualCount ?? node.count ?? 1) >= 2 && globalScale > 0.75);
    if (showLabel && node.label) {
      const fontSize = Math.max((node.anchor ? 13 : 11) / globalScale, 5.5);
      ctx.font = `${node.anchor ? 700 : 500} ${fontSize}px Inter, system-ui, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillStyle = "rgba(233,238,247,0.92)";
      const maxWidth = Math.max(130 / globalScale, r * 8);
      drawWrappedLabel(ctx, node.label, node.x, node.y + r + 4 / globalScale, maxWidth, fontSize * 1.15);
    }
    if (selected && (node.level ?? 1) >= 2 && node.label) {
      const fontSize = Math.max(12 / globalScale, 7);
      ctx.font = `600 ${fontSize}px Inter, system-ui, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillStyle = "rgba(233,238,247,0.96)";
      drawWrappedLabel(ctx, node.label, node.x, node.y + r + 8 / globalScale, 150 / globalScale, fontSize * 1.15);
    }
  };

  const drawNodeSafe = (node, ctx, globalScale) => {
    try {
      drawNode(node, ctx, globalScale);
    } catch {
      if (!Number.isFinite(node.x) || !Number.isFinite(node.y)) return;
      const r = Math.max(6, Math.min(18, radiusFor(node) || 8));
      const [cr, cg, cb] = confidenceRGB(colorConfidenceFor(node));
      ctx.beginPath();
      ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
      ctx.fillStyle = `rgba(${cr},${cg},${cb},0.9)`;
      ctx.fill();
      ctx.lineWidth = 1.5 / Math.max(globalScale || 1, 0.1);
      ctx.strokeStyle = "rgba(238,243,248,0.75)";
      ctx.stroke();
    }
  };

  const edgeRadiusFor = (node) => {
    if (!node) return 0;
    if (node.anchor || ((node.level ?? 2) === 1 && childCounts[node.id])) {
      return ringRadiusFor(node);
    }
    return radiusFor(node);
  };

  const drawLink = (link, ctx, globalScale) => {
    const source = typeof link.source === "object" ? link.source : graphData.nodes.find((n) => n.id === link.source);
    const target = typeof link.target === "object" ? link.target : graphData.nodes.find((n) => n.id === link.target);
    if (!source || !target) return;
    if (![source.x, source.y, target.x, target.y].every(Number.isFinite)) return;

    const dx = target.x - source.x;
    const dy = target.y - source.y;
    const dist = Math.sqrt(dx * dx + dy * dy) || 1;
    const sourcePad = source.anchor ? 18 : (source.level ?? 2) <= 1 ? 12 : 7;
    const targetPad = target.anchor ? 22 : (target.level ?? 2) <= 1 ? 16 : 8;
    const sx = source.x + (dx / dist) * (edgeRadiusFor(source) + sourcePad);
    const sy = source.y + (dy / dist) * (edgeRadiusFor(source) + sourcePad);
    const tx = target.x - (dx / dist) * (edgeRadiusFor(target) + targetPad);
    const ty = target.y - (dy / dist) * (edgeRadiusFor(target) + targetPad);

    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.lineTo(tx, ty);
    const highLevel = highLevelLink(link);
    const smallest = smallestNodeLink(link);
    const important = importantLink(link);
    ctx.strokeStyle = smallest
      ? "rgba(150,162,174,0.28)"
      : highLevel
      ? "rgba(180,226,215,0.54)"
      : important
      ? "rgba(210,231,225,0.74)"
      : link.kind === "strong"
        ? "rgba(180,226,215,0.38)"
        : link.kind === "weak"
          ? "rgba(143,183,255,0.16)"
          : "rgba(140,153,168,0.22)";
    ctx.lineWidth = (smallest ? 1 : highLevel ? 2.1 : important ? 3 : link.kind === "strong" ? 2 : link.kind === "weak" ? 0.7 : 1) / globalScale;
    ctx.stroke();

    const arrow = Math.max(5 / globalScale, 3);
    const angle = Math.atan2(dy, dx);
    ctx.beginPath();
    ctx.moveTo(tx, ty);
    ctx.lineTo(tx - arrow * Math.cos(angle - 0.45), ty - arrow * Math.sin(angle - 0.45));
    ctx.lineTo(tx - arrow * Math.cos(angle + 0.45), ty - arrow * Math.sin(angle + 0.45));
    ctx.closePath();
    ctx.fillStyle = ctx.strokeStyle;
    ctx.fill();
  };

  const handleNodeDrag = (node, translate) => {
    const ids = node.anchor
      ? descendantsByNode[node.id]
      : (node.level ?? 2) === 1
        ? childrenByNode[node.id]
        : [];
    if (!translate || !ids?.length) return;
    const directChildren = new Set(childrenByNode[node.id] || []);
    for (const id of ids) {
      const child = nodeById[id];
      if (!child || !Number.isFinite(child.x) || !Number.isFinite(child.y)) continue;
      const scale = node.anchor
        ? (directChildren.has(id) ? 0.15 : 0.035)
        : (node.level ?? 2) === 1
          ? 0.08
          : 0;
      if (!scale) continue;
      child.x += translate.x * scale;
      child.y += translate.y * scale;
      if (Number.isFinite(child.fx)) child.fx += translate.x * scale;
      if (Number.isFinite(child.fy)) child.fy += translate.y * scale;
    }
  };

  const handleNodeDragEnd = (node) => {
    const ids = [
      node.id,
      ...(node.anchor
        ? descendantsByNode[node.id] || []
        : (node.level ?? 2) === 1
          ? childrenByNode[node.id] || []
          : []),
    ];
    for (const id of ids) {
      const n = nodeById[id];
      if (!n) continue;
      if (Number.isFinite(n.vx)) n.vx *= 0.2;
      if (Number.isFinite(n.vy)) n.vy *= 0.2;
    }
    fgRef.current?.d3AlphaTarget?.(0);
  };

  return (
    <div
      ref={wrapRef}
      className={`graph-canvas ${options.texture ? "textured" : ""}`}
    >
      <ForceGraph2D
        ref={fgRef}
        graphData={graphData}
        width={size.width}
        height={size.height}
        backgroundColor="rgba(0,0,0,0)"
        cooldownTime={3600}
        d3VelocityDecay={0.36}
        nodeRelSize={6}
        nodeCanvasObject={drawNodeSafe}
        nodePointerAreaPaint={(node, color, ctx) => {
          if (!Number.isFinite(node.x) || !Number.isFinite(node.y)) return;
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(
            node.x,
            node.y,
            (node.anchor || ((node.level ?? 2) === 1 && childCounts[node.id]))
              ? ringRadiusFor(node)
              : radiusFor(node) + ((node.level ?? 2) >= 2 ? 11 : 5),
            0,
            2 * Math.PI
          );
          ctx.fill();
        }}
        linkColor={(l) =>
          smallestNodeLink(l)
            ? "rgba(150,162,174,0.28)"
            : highLevelLink(l)
            ? "rgba(180,226,215,0.54)"
            : importantLink(l)
            ? "rgba(210,231,225,0.74)"
            : l.kind === "strong"
            ? "rgba(180,226,215,0.38)"
            : l.kind === "weak"
              ? "rgba(143,183,255,0.16)"
              : "rgba(140,153,168,0.22)"
        }
        linkWidth={(l) => smallestNodeLink(l) ? 1 : highLevelLink(l) ? 2.1 : importantLink(l) ? 3 : l.kind === "strong" ? 2 : l.kind === "weak" ? 0.7 : 1}
        linkCanvasObjectMode={() => "replace"}
        linkCanvasObject={drawLink}
        linkCurvature={0.12}
        linkDirectionalParticles={0}
        linkDirectionalParticleWidth={1.6}
        linkDirectionalParticleColor={() => "rgba(148,163,184,0.55)"}
        onRenderFramePre={drawReviewClouds}
        onEngineTick={separateOverlaps}
        onNodeDrag={handleNodeDrag}
        onNodeDragEnd={handleNodeDragEnd}
        onNodeClick={onNodeClick}
        onBackgroundClick={() => onNodeClick(null)}
      />
    </div>
  );
}
