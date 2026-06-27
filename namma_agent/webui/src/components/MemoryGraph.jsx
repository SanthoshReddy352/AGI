import { useEffect, useMemo, useRef, useState } from "react";

// An Obsidian-style force-directed knowledge graph on <canvas> with a hand-rolled
// physics sim (no deps). Nodes repel, links pull, gravity centres. A floating
// control panel (Forces sliders + Groups legend) mirrors Obsidian's graph view.
// Interactions: hover-highlight neighbours, drag nodes, pan, wheel-zoom.

const PALETTE = [
  "#7cc4ff", "#c9a0ff", "#7ee787", "#ffa657", "#ff7b9c",
  "#79e0d8", "#f2cc60", "#a0b3ff", "#ff9bd2", "#9be37d",
];
function colorFor(type, cache) {
  if (!cache.map) { cache.map = {}; cache.i = 0; }
  if (!cache.map[type]) cache.map[type] = PALETTE[cache.i++ % PALETTE.length];
  return cache.map[type];
}

// slider (0..100) → physics value
const lin = (v, a, b) => a + (v / 100) * (b - a);

export default function MemoryGraph({ nodes = [], edges = [], dark = true, height = 560 }) {
  const wrapRef = useRef(null);
  const canvasRef = useRef(null);
  const sim = useRef({ nodes: [], edges: [], cam: { x: 0, y: 0, k: 1 }, alpha: 1 });
  const drag = useRef(null);
  const hover = useRef(null);
  const [hud, setHud] = useState(null);
  const [panel, setPanel] = useState(true);

  // Force controls (Obsidian-style)
  const [forces, setForces] = useState({ center: 40, repel: 55, link: 55, distance: 35 });
  const [showLabels, setShowLabels] = useState(true);
  const forcesRef = useRef(forces); forcesRef.current = forces;
  const labelsRef = useRef(showLabels); labelsRef.current = showLabels;

  // Groups = distinct node types, each with a colour + visibility toggle.
  const groups = useMemo(() => {
    const cache = {}; const seen = {};
    for (const n of nodes) {
      const t = n.type || "Entity";
      if (!seen[t]) seen[t] = { type: t, color: n.color || colorFor(t, cache), count: 0 };
      seen[t].count++;
    }
    return Object.values(seen).sort((a, b) => b.count - a.count);
  }, [nodes]);
  const [hidden, setHidden] = useState({});   // type -> true (hidden)
  const hiddenRef = useRef(hidden); hiddenRef.current = hidden;

  // (Re)build the simulation when data changes.
  useEffect(() => {
    const cache = {}; const deg = {};
    edges.forEach((e) => { deg[e.source] = (deg[e.source] || 0) + 1; deg[e.target] = (deg[e.target] || 0) + 1; });
    const R = 260;
    const simNodes = nodes.map((n, i) => {
      const a = (i / Math.max(1, nodes.length)) * Math.PI * 2;
      return {
        ...n, x: Math.cos(a) * R * (0.4 + Math.random() * 0.3), y: Math.sin(a) * R * (0.4 + Math.random() * 0.3),
        vx: 0, vy: 0, deg: deg[n.id] || 0, r: 4 + Math.sqrt(deg[n.id] || 0) * 2.6,
        col: n.color || colorFor(n.type || "Entity", cache), fixed: false,
      };
    });
    const byId = Object.fromEntries(simNodes.map((n) => [n.id, n]));
    const simEdges = edges.map((e) => ({ s: byId[e.source], t: byId[e.target] })).filter((e) => e.s && e.t);
    sim.current.nodes = simNodes; sim.current.edges = simEdges;
    sim.current.alpha = 1; sim.current.cam = { x: 0, y: 0, k: 1 };
  }, [nodes, edges]);

  useEffect(() => {
    const canvas = canvasRef.current, wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    const ctx = canvas.getContext("2d");
    let raf, W = 0, H = 0; const dpr = Math.max(1, window.devicePixelRatio || 1);
    const resize = () => {
      const r = wrap.getBoundingClientRect(); W = r.width; H = r.height;
      canvas.width = W * dpr; canvas.height = H * dpr; canvas.style.width = W + "px"; canvas.style.height = H + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize(); const ro = new ResizeObserver(resize); ro.observe(wrap);

    const isHidden = (n) => !!hiddenRef.current[n.type || "Entity"];
    const toWorld = (sx, sy) => { const { cam } = sim.current; return { x: (sx - W / 2) / cam.k - cam.x, y: (sy - H / 2) / cam.k - cam.y }; };
    const nodeAt = (sx, sy) => {
      const w = toWorld(sx, sy); let best = null, bd = 1e9;
      for (const n of sim.current.nodes) {
        if (isHidden(n)) continue;
        const dx = n.x - w.x, dy = n.y - w.y, d = dx * dx + dy * dy, rr = (n.r + 6) ** 2;
        if (d < rr && d < bd) { bd = d; best = n; }
      } return best;
    };

    const step = () => {
      const S = sim.current, ns = S.nodes; if (S.alpha <= 0.004) return;
      const f = forcesRef.current, k = S.alpha;
      const gravity = lin(f.center, 0.0006, 0.006), repel = lin(f.repel, 300, 3200);
      const spring = lin(f.link, 0.004, 0.06), rest = lin(f.distance, 30, 240);
      for (let i = 0; i < ns.length; i++) {
        const a = ns[i]; if (isHidden(a)) continue;
        for (let j = i + 1; j < ns.length; j++) {
          const b = ns[j]; if (isHidden(b)) continue;
          let dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy || 0.01;
          const force = (repel * k) / d2, d = Math.sqrt(d2), fx = (dx / d) * force, fy = (dy / d) * force;
          a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
        }
        a.vx += -a.x * gravity * k; a.vy += -a.y * gravity * k;
      }
      for (const e of S.edges) {
        if (isHidden(e.s) || isHidden(e.t)) continue;
        let dx = e.t.x - e.s.x, dy = e.t.y - e.s.y, d = Math.hypot(dx, dy) || 0.01;
        const force = (d - rest) * spring * k, fx = (dx / d) * force, fy = (dy / d) * force;
        if (!e.s.fixed) { e.s.vx += fx; e.s.vy += fy; }
        if (!e.t.fixed) { e.t.vx -= fx; e.t.vy -= fy; }
      }
      for (const n of ns) { if (n.fixed) { n.vx = n.vy = 0; continue; } n.vx *= 0.82; n.vy *= 0.82; n.x += n.vx; n.y += n.vy; }
      S.alpha *= 0.993;
    };

    const draw = () => {
      const S = sim.current, { cam } = S;
      ctx.fillStyle = dark ? "#070a10" : "#fbfcfe"; ctx.fillRect(0, 0, W, H);
      ctx.save(); ctx.translate(W / 2, H / 2); ctx.scale(cam.k, cam.k); ctx.translate(cam.x, cam.y);
      const hv = hover.current; const neigh = new Set();
      if (hv) { neigh.add(hv); for (const e of S.edges) { if (e.s.id === hv) neigh.add(e.t.id); if (e.t.id === hv) neigh.add(e.s.id); } }
      for (const e of S.edges) {
        if (isHidden(e.s) || isHidden(e.t)) continue;
        const on = !hv || (neigh.has(e.s.id) && neigh.has(e.t.id));
        ctx.strokeStyle = dark ? (on ? "rgba(148,163,184,0.45)" : "rgba(148,163,184,0.07)") : (on ? "rgba(100,116,139,0.4)" : "rgba(100,116,139,0.07)");
        ctx.lineWidth = on ? 1 : 0.5; ctx.beginPath(); ctx.moveTo(e.s.x, e.s.y); ctx.lineTo(e.t.x, e.t.y); ctx.stroke();
      }
      for (const n of S.nodes) {
        if (isHidden(n)) continue;
        const on = !hv || neigh.has(n.id);
        ctx.globalAlpha = on ? 1 : 0.15;
        ctx.shadowColor = n.col; ctx.shadowBlur = n.id === hv ? 24 : 9;
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2); ctx.fillStyle = n.col; ctx.fill(); ctx.shadowBlur = 0;
        ctx.lineWidth = 1.4; ctx.strokeStyle = dark ? "#070a10" : "#ffffff"; ctx.stroke();
        if (labelsRef.current && (cam.k > 1.15 || n.id === hv || neigh.has(n.id) || n.deg >= 5)) {
          const label = (n.label || "").slice(0, 26);
          if (label) {
            ctx.globalAlpha = on ? 0.95 : 0.2; ctx.font = "11px ui-sans-serif, system-ui";
            ctx.textAlign = "center"; ctx.textBaseline = "top"; ctx.fillStyle = dark ? "#c7d2e0" : "#334155";
            ctx.fillText(label, n.x, n.y + n.r + 3);
          }
        }
        ctx.globalAlpha = 1;
      }
      ctx.restore();
    };

    const loop = () => { step(); draw(); raf = requestAnimationFrame(loop); };
    loop();

    const pos = (ev) => { const r = canvas.getBoundingClientRect(); return [ev.clientX - r.left, ev.clientY - r.top]; };
    const onDown = (ev) => {
      const [sx, sy] = pos(ev); const n = nodeAt(sx, sy);
      if (n) { n.fixed = true; drag.current = { node: n }; sim.current.alpha = Math.max(sim.current.alpha, 0.4); }
      else { const c = sim.current.cam; drag.current = { pan: true, sx, sy, cx: c.x, cy: c.y }; }
    };
    const onMove = (ev) => {
      const [sx, sy] = pos(ev); const d = drag.current;
      if (d?.node) { const w = toWorld(sx, sy); d.node.x = w.x; d.node.y = w.y; sim.current.alpha = Math.max(sim.current.alpha, 0.3); }
      else if (d?.pan) { const { cam } = sim.current; cam.x = d.cx + (sx - d.sx) / cam.k; cam.y = d.cy + (sy - d.sy) / cam.k; }
      else { const n = nodeAt(sx, sy); hover.current = n ? n.id : null; setHud(n ? { label: n.label, type: n.type } : null); canvas.style.cursor = n ? "pointer" : "grab"; }
    };
    const onUp = () => { if (drag.current?.node) drag.current.node.fixed = false; drag.current = null; };
    const onWheel = (ev) => {
      ev.preventDefault(); const { cam } = sim.current; const [sx, sy] = pos(ev); const b = toWorld(sx, sy);
      cam.k = Math.min(4, Math.max(0.15, cam.k * (ev.deltaY < 0 ? 1.12 : 0.89))); const a = toWorld(sx, sy);
      cam.x += a.x - b.x; cam.y += a.y - b.y;
    };
    canvas.addEventListener("mousedown", onDown); window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp); canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      cancelAnimationFrame(raf); ro.disconnect(); canvas.removeEventListener("mousedown", onDown);
      window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp);
      canvas.removeEventListener("wheel", onWheel);
    };
  }, [dark]);

  const reheat = () => { sim.current.alpha = Math.max(sim.current.alpha, 0.5); };
  const setForce = (key, v) => { setForces((f) => ({ ...f, [key]: v })); reheat(); };
  const fit = () => { sim.current.cam = { x: 0, y: 0, k: 1 }; reheat(); };
  const zoom = (f) => { sim.current.cam.k = Math.min(4, Math.max(0.15, sim.current.cam.k * f)); };
  const toggleType = (t) => { setHidden((h) => ({ ...h, [t]: !h[t] })); reheat(); };

  // Theme-aware overlay surfaces (controls / HUD / panel) — adapt to the app theme.
  const ovBtn = dark
    ? "bg-black/40 border-white/10 text-white/80 hover:text-white"
    : "bg-white/70 border-line text-ink-soft hover:text-ink";
  const ovPanel = dark ? "bg-black/55 border-white/10 text-white/85" : "bg-white/85 border-line text-ink shadow-soft";
  const ovSub = dark ? "text-white/50" : "text-ink-faint";
  const ovDim = dark ? "text-white/40" : "text-ink-faint";
  const ovDiv = dark ? "border-white/10" : "border-line";
  const ovHover = dark ? "hover:bg-white/10" : "hover:bg-paper-sink";
  const ovLbl = dark ? "text-white/70" : "text-ink-soft";

  return (
    <div ref={wrapRef} className="relative rounded-2xl overflow-hidden border border-line dark:border-night-line" style={{ height }}>
      <canvas ref={canvasRef} className="block w-full h-full" />

      {nodes.length === 0 && (
        <div className="absolute inset-0 grid place-items-center text-[13px] text-ink-faint dark:text-night-faint">
          No memories yet — add something below, then refresh.
        </div>
      )}

      {/* zoom controls (bottom-left) */}
      <div className="absolute bottom-3 left-3 flex gap-1.5">
        {[["+", () => zoom(1.2)], ["−", () => zoom(0.83)], ["⤢", fit]].map(([t, fn]) => (
          <button key={t} onClick={fn}
                  className={`h-8 w-8 grid place-items-center rounded-lg backdrop-blur border text-[15px] ${ovBtn}`}>{t}</button>
        ))}
      </div>

      {/* hovered-node HUD (bottom-center) */}
      {hud?.label && (
        <div className={`absolute bottom-3 left-1/2 -translate-x-1/2 max-w-[50%] rounded-lg backdrop-blur border px-3 py-1.5 ${ovPanel}`}>
          <div className="text-[13px] font-medium truncate">{hud.label}</div>
          <div className={`text-[11px] ${ovSub}`}>{hud.type}</div>
        </div>
      )}

      {/* panel toggle */}
      <button onClick={() => setPanel((p) => !p)} title="Controls"
              className={`absolute top-3 right-3 h-8 w-8 grid place-items-center rounded-lg backdrop-blur border ${ovBtn}`}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M4 6h16M4 12h16M4 18h16" /></svg>
      </button>

      {/* Obsidian-style control panel */}
      {panel && (
        <div className={`absolute top-3 right-12 w-56 max-h-[calc(100%-24px)] overflow-y-auto rounded-xl backdrop-blur border p-3 text-[12px] space-y-3 ${ovPanel}`}>
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <span className={`uppercase tracking-wider text-[10.5px] ${ovSub}`}>Groups</span>
              <span className={`text-[10.5px] ${ovDim}`}>{groups.length}</span>
            </div>
            <div className="space-y-1">
              {groups.map((g) => (
                <button key={g.type} onClick={() => toggleType(g.type)}
                        className={`w-full flex items-center gap-2 px-1.5 py-1 rounded-md ${ovHover} ${hidden[g.type] ? "opacity-40" : ""}`}>
                  <span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ background: g.color }} />
                  <span className="truncate flex-1 text-left">{g.type}</span>
                  <span className={ovDim}>{g.count}</span>
                </button>
              ))}
              {groups.length === 0 && <div className={`px-1.5 ${ovDim}`}>No groups yet</div>}
            </div>
          </div>

          <div className={`border-t pt-2 ${ovDiv}`}>
            <div className={`uppercase tracking-wider text-[10.5px] mb-1.5 ${ovSub}`}>Display</div>
            <label className="flex items-center gap-2 px-1.5 cursor-pointer">
              <input type="checkbox" checked={showLabels} onChange={(e) => setShowLabels(e.target.checked)} />
              Labels
            </label>
          </div>

          <div className={`border-t pt-2 space-y-2.5 ${ovDiv}`}>
            <div className={`uppercase tracking-wider text-[10.5px] ${ovSub}`}>Forces</div>
            {[["Center force", "center"], ["Repel force", "repel"], ["Link force", "link"], ["Link distance", "distance"]].map(([label, key]) => (
              <div key={key}>
                <div className={`mb-0.5 ${ovLbl}`}>{label}</div>
                <input type="range" min="0" max="100" value={forces[key]}
                       onChange={(e) => setForce(key, +e.target.value)} className="w-full accent-brand" />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
