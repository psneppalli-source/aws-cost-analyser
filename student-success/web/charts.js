/* Minimal dependency-free SVG chart kit for the dashboard.
 * Every chart is redrawn from data on filter change and on resize, carries a
 * hover tooltip, and uses CSS custom properties for colour so it follows the
 * light/dark theme. */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const tt = () => document.getElementById("tt");

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  const tip = {
    show(evt, html) {
      const t = tt();
      t.innerHTML = html;
      t.classList.add("show");
      tip.move(evt);
    },
    move(evt) {
      const t = tt();
      const pad = 14;
      let x = evt.clientX + pad, y = evt.clientY + pad;
      const r = t.getBoundingClientRect();
      if (x + r.width > window.innerWidth - 8) x = evt.clientX - r.width - pad;
      if (y + r.height > window.innerHeight - 8) y = evt.clientY - r.height - pad;
      t.style.left = x + "px";
      t.style.top = y + "px";
    },
    hide() { tt().classList.remove("show"); },
  };

  function rows(title, pairs) {
    return `<div class="tt-title">${esc(title)}</div>` +
      pairs.map(([k, v]) => `<div class="row"><span>${esc(k)}</span><span>${esc(v)}</span></div>`).join("");
  }

  // SVG presentation attributes don't reliably accept var(); resolve tokens to colours.
  function resolve(v) {
    if (typeof v !== "string" || !v.startsWith("var(")) return v;
    const name = v.slice(4, -1).trim();
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || v;
  }

  function el(tag, attrs, parent) {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs) {
      if (attrs[k] === undefined || attrs[k] === null) continue;
      n.setAttribute(k, k === "style" ? attrs[k] : resolve(attrs[k]));
    }
    if (parent) parent.appendChild(n);
    return n;
  }

  function svgFor(container, height) {
    container.innerHTML = "";
    const w = Math.max(280, container.clientWidth || 600);
    const svg = el("svg", { viewBox: `0 0 ${w} ${height}`, width: w, height, role: "img" }, container);
    return { svg, w, h: height };
  }

  function text(parent, x, y, str, attrs = {}) {
    const t = el("text", { x, y, ...attrs }, parent);
    t.textContent = str;
    return t;
  }

  // Bar path with 4px rounding on the data end only (square at baseline).
  function barPath(x, y, w, h, dir) {
    const r = Math.min(4, (dir === "up" ? w : h) / 2, (dir === "up" ? h : w));
    if (r <= 0 || w <= 0 || h <= 0) return `M${x},${y}h${Math.max(0, w)}v${Math.max(0, h)}h${-Math.max(0, w)}z`;
    if (dir === "up") {
      return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
    }
    if (dir === "left") {
      return `M${x + w},${y}H${x + r}Q${x},${y} ${x},${y + r}V${y + h - r}Q${x},${y + h} ${x + r},${y + h}H${x + w}Z`;
    }
    // right
    return `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`;
  }

  function niceMax(v) {
    if (v <= 0) return 1;
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    const m = v / p;
    return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * p;
  }

  function legend(container, items) {
    if (!container) return;
    container.innerHTML = items.map((i) =>
      `<span><span class="${i.line ? "ln" : "sw"}" style="background:${i.color}"></span>${esc(i.label)}</span>`).join("");
  }

  /* ---------- Column chart (vertical bars) ---------- */
  function columns(container, items, opts = {}) {
    const H = opts.height || 220;
    const m = { t: 16, r: 8, b: 28, l: 34 };
    const { svg, w } = svgFor(container, H);
    const iw = w - m.l - m.r, ih = H - m.t - m.b;
    const maxV = opts.yMax || niceMax(Math.max(1, ...items.map((d) => d.v)));
    const g = el("g", { class: "grid" }, svg);
    const ticks = 4;
    for (let i = 0; i <= ticks; i++) {
      const v = (maxV / ticks) * i;
      const y = m.t + ih - (v / maxV) * ih;
      el("line", { x1: m.l, x2: m.l + iw, y1: y, y2: y }, g);
      text(svg, m.l - 6, y + 4, opts.yFmt ? opts.yFmt(v) : Math.round(v), { "text-anchor": "end" });
    }
    const band = iw / items.length;
    const bw = Math.min(opts.barMax || 24, band - 2);
    items.forEach((d, i) => {
      const x = m.l + i * band + (band - bw) / 2;
      const bh = (d.v / maxV) * ih;
      const p = el("path", { d: barPath(x, m.t + ih - bh, bw, bh, "up"), fill: d.color, class: "mark" }, svg);
      if (opts.valueLabels) {
        text(svg, x + bw / 2, m.t + ih - bh - 5, opts.yFmt ? opts.yFmt(d.v) : d.v, { "text-anchor": "middle", class: "t-ink2" });
      }
      const hit = el("rect", { x: m.l + i * band, y: m.t, width: band, height: ih, class: "hit" }, svg);
      hit.addEventListener("mousemove", (e) => tip.show(e, d.tip || rows(d.label, [["Value", d.v]])));
      hit.addEventListener("mouseleave", tip.hide);
      if (opts.onClick) hit.addEventListener("click", () => opts.onClick(d));
      if (opts.xLabelEvery ? i % opts.xLabelEvery === 0 : true) {
        text(svg, m.l + i * band + band / 2, H - 10, d.label, { "text-anchor": "middle" });
      }
      void p;
    });
    el("line", { x1: m.l, x2: m.l + iw, y1: m.t + ih, y2: m.t + ih, class: "axis" }, svg);
  }

  /* ---------- 100% stacked horizontal bars ---------- */
  function stacked(container, data, keys, opts = {}) {
    const rowH = 34;
    const m = { t: 6, r: 12, b: 20, l: opts.labelW || 64 };
    const H = m.t + m.b + data.length * rowH;
    const { svg, w } = svgFor(container, H);
    const iw = w - m.l - m.r;
    const g = el("g", { class: "grid" }, svg);
    [0, 25, 50, 75, 100].forEach((v) => {
      const x = m.l + (v / 100) * iw;
      el("line", { x1: x, x2: x, y1: m.t, y2: H - m.b }, g);
      text(svg, x, H - 4, v + "%", { "text-anchor": "middle" });
    });
    data.forEach((row, i) => {
      const total = keys.reduce((s, k) => s + (row.values[k.key] || 0), 0) || 1;
      const y = m.t + i * rowH + (rowH - 22) / 2;
      text(svg, m.l - 8, y + 15, row.label, { "text-anchor": "end", class: "t-ink2" });
      let x = m.l;
      keys.forEach((k, ki) => {
        const v = row.values[k.key] || 0;
        const bw = (v / total) * iw;
        if (bw <= 0) return;
        const gap = ki < keys.length - 1 ? 2 : 0;
        const isLast = keys.slice(ki + 1).every((kk) => !(row.values[kk.key] > 0));
        const d = isLast ? barPath(x, y, Math.max(0, bw), 22, "right") : `M${x},${y}h${Math.max(0, bw - gap)}v22h${-Math.max(0, bw - gap)}z`;
        el("path", { d, fill: k.color, class: "mark" }, svg);
        const pct = Math.round((v / total) * 100);
        if (bw > 34) {
          text(svg, x + (bw - gap) / 2, y + 15, pct + "%", { "text-anchor": "middle", fill: k.labelInk || "#fff", style: `fill:${k.labelInk || "#fff"};font-weight:600` });
        }
        const hit = el("rect", { x, y: y - 4, width: Math.max(bw, 4), height: 30, class: "hit" }, svg);
        hit.addEventListener("mousemove", (e) => tip.show(e, rows(`${row.label} · ${k.label}`, [["Students", v], ["Share", pct + "%"], ["Cohort", total]])));
        hit.addEventListener("mouseleave", tip.hide);
        if (opts.onClick) hit.addEventListener("click", () => opts.onClick(row, k));
        x += bw;
      });
    });
  }

  /* ---------- Multi-series line chart with crosshair ---------- */
  function lines(container, series, xLabels, opts = {}) {
    const H = opts.height || 230;
    const m = { t: 14, r: opts.endLabelW || 112, b: 28, l: 36 };
    const { svg, w } = svgFor(container, H);
    const iw = w - m.l - m.r, ih = H - m.t - m.b;
    const all = series.flatMap((s) => s.values).filter((v) => v != null);
    const yMin = opts.yMin ?? 0;
    const yMax = opts.yMax ?? niceMax(Math.max(...all, 1));
    const X = (i) => m.l + (xLabels.length === 1 ? iw / 2 : (i / (xLabels.length - 1)) * iw);
    const Y = (v) => m.t + ih - ((v - yMin) / (yMax - yMin)) * ih;
    const g = el("g", { class: "grid" }, svg);
    const ticks = opts.ticks || 4;
    for (let i = 0; i <= ticks; i++) {
      const v = yMin + ((yMax - yMin) / ticks) * i;
      el("line", { x1: m.l, x2: m.l + iw, y1: Y(v), y2: Y(v) }, g);
      text(svg, m.l - 6, Y(v) + 4, opts.yFmt ? opts.yFmt(v) : Math.round(v), { "text-anchor": "end" });
    }
    xLabels.forEach((lab, i) => {
      const last = i === xLabels.length - 1;
      // the last label only when it won't collide with the previous regular tick
      if (!opts.xEvery || i % opts.xEvery === 0 || (last && i % opts.xEvery > opts.xEvery / 2)) text(svg, X(i), H - 8, lab, { "text-anchor": last ? "end" : "middle" });
    });
    el("line", { x1: m.l, x2: m.l + iw, y1: m.t + ih, y2: m.t + ih, class: "axis" }, svg);
    if (opts.ref != null) {
      el("line", { x1: m.l, x2: m.l + iw, y1: Y(opts.ref), y2: Y(opts.ref), stroke: "var(--critical)", "stroke-width": 1, "stroke-dasharray": "0" , opacity: 0.7 }, svg);
      text(svg, m.l + 6, Y(opts.ref) + 14, opts.refLabel || "", { class: "t-ink2" });
    }
    const ends = [];
    series.forEach((s) => {
      const pts = s.values.map((v, i) => (v == null ? null : [X(i), Y(v)])).filter(Boolean);
      if (!pts.length) return;
      el("path", { d: "M" + pts.map((p) => p.join(",")).join("L"), fill: "none", stroke: s.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round", class: "mark" }, svg);
      const last = pts[pts.length - 1];
      el("circle", { cx: last[0], cy: last[1], r: 4, fill: s.color, stroke: "var(--surface)", "stroke-width": 2 }, svg);
      ends.push({ y: last[1], x: last[0], s });
    });
    // End labels only when they do not collide.
    ends.sort((a, b) => a.y - b.y);
    const ok = ends.every((e, i) => i === 0 || e.y - ends[i - 1].y > 13);
    if (ok) ends.forEach((e) => text(svg, e.x + 8, e.y + 4, e.s.short || e.s.name, { class: "t-ink2" }));

    const cross = el("line", { y1: m.t, y2: m.t + ih, stroke: "var(--axis)", "stroke-width": 1, visibility: "hidden" }, svg);
    const dots = series.map((s) => el("circle", { r: 4, fill: s.color, stroke: "var(--surface)", "stroke-width": 2, visibility: "hidden" }, svg));
    const hit = el("rect", { x: m.l, y: m.t, width: iw, height: ih, class: "hit" }, svg);
    hit.addEventListener("mousemove", (e) => {
      const r = svg.getBoundingClientRect();
      const sx = ((e.clientX - r.left) / r.width) * w;
      const i = Math.max(0, Math.min(xLabels.length - 1, Math.round(((sx - m.l) / iw) * (xLabels.length - 1))));
      cross.setAttribute("x1", X(i)); cross.setAttribute("x2", X(i)); cross.setAttribute("visibility", "visible");
      series.forEach((s, si) => {
        const v = s.values[i];
        if (v == null) { dots[si].setAttribute("visibility", "hidden"); return; }
        dots[si].setAttribute("cx", X(i)); dots[si].setAttribute("cy", Y(v)); dots[si].setAttribute("visibility", "visible");
      });
      const html = `<div class="tt-title">${esc(xLabels[i])}</div>` + series.map((s) =>
        `<div class="row"><span><span class="ln" style="display:inline-block;width:10px;height:2px;background:${s.color};vertical-align:3px;margin-right:5px"></span>${esc(s.name)}</span><span>${s.values[i] == null ? "–" : (opts.yFmt ? opts.yFmt(s.values[i]) : s.values[i].toFixed(1))}</span></div>`).join("");
      tip.show(e, html);
    });
    hit.addEventListener("mouseleave", () => {
      tip.hide(); cross.setAttribute("visibility", "hidden"); dots.forEach((d) => d.setAttribute("visibility", "hidden"));
    });
  }

  /* ---------- Scatter ---------- */
  function scatter(container, pts, opts = {}) {
    const H = opts.height || 320;
    const m = { t: 12, r: 12, b: 36, l: 40 };
    const { svg, w } = svgFor(container, H);
    const iw = w - m.l - m.r, ih = H - m.t - m.b;
    const X = (v) => m.l + (v / 100) * iw;
    const Y = (v) => m.t + ih - (v / 100) * ih;
    const g = el("g", { class: "grid" }, svg);
    [0, 25, 50, 75, 100].forEach((v) => {
      el("line", { x1: m.l, x2: m.l + iw, y1: Y(v), y2: Y(v) }, g);
      el("line", { x1: X(v), x2: X(v), y1: m.t, y2: m.t + ih }, g);
      text(svg, m.l - 6, Y(v) + 4, v, { "text-anchor": "end" });
      text(svg, X(v), m.t + ih + 14, v, { "text-anchor": "middle" });
    });
    text(svg, m.l + iw / 2, H - 4, opts.xLabel || "", { "text-anchor": "middle", class: "t-ink2" });
    const yl = text(svg, 0, 0, opts.yLabel || "", { "text-anchor": "middle", class: "t-ink2", transform: `translate(11 ${m.t + ih / 2}) rotate(-90)` });
    void yl;
    if (opts.quad) {
      const [qx, qy] = opts.quad;
      el("rect", { x: X(qx), y: Y(qy), width: X(100) - X(qx), height: Y(0) - Y(qy), fill: "var(--accent-wash)", opacity: 0.8 }, svg);
      text(svg, X(100) - 6, Y(0) - 6, opts.quadLabel || "", { "text-anchor": "end", class: "t-ink2", style: "font-weight:600" });
      el("line", { x1: X(qx), x2: X(qx), y1: m.t, y2: m.t + ih, stroke: "var(--axis)" }, svg);
      el("line", { x1: m.l, x2: m.l + iw, y1: Y(qy), y2: Y(qy), stroke: "var(--axis)" }, svg);
    }
    const layer = el("g", {}, svg);
    pts.forEach((p) => {
      const c = el("circle", { cx: X(p.x), cy: Y(p.y), r: 4, fill: p.color, stroke: "var(--surface)", "stroke-width": 1.5, class: "mark", style: "cursor:pointer" }, layer);
      c.addEventListener("mousemove", (e) => { c.setAttribute("r", 6); tip.show(e, p.tip); });
      c.addEventListener("mouseleave", () => { c.setAttribute("r", 4); tip.hide(); });
      if (opts.onClick) c.addEventListener("click", () => { tip.hide(); opts.onClick(p); });
    });
  }

  /* ---------- Heatmap ---------- */
  function heatmap(container, rowLabels, colLabels, values, opts = {}) {
    const cellH = 34;
    const m = { t: 34, r: 4, b: 4, l: opts.labelW || 70 };
    const H = m.t + m.b + rowLabels.length * cellH;
    const { svg, w } = svgFor(container, H);
    const cw = (w - m.l - m.r) / colLabels.length;
    const steps = ["--seq-0", "--seq-1", "--seq-2", "--seq-3", "--seq-4", "--seq-5", "--seq-6"];
    const lo = opts.min ?? 0, hi = opts.max ?? 100;
    colLabels.forEach((c, j) => {
      const words = c.split(" ");
      if (words.length > 1 && cw < 90) {
        text(svg, m.l + j * cw + cw / 2, 12, words[0], { "text-anchor": "middle", class: "t-ink2" });
        text(svg, m.l + j * cw + cw / 2, 25, words.slice(1).join(" "), { "text-anchor": "middle", class: "t-ink2" });
      } else {
        text(svg, m.l + j * cw + cw / 2, 22, c, { "text-anchor": "middle", class: "t-ink2" });
      }
    });
    rowLabels.forEach((r, i) => {
      text(svg, m.l - 8, m.t + i * cellH + cellH / 2 + 4, r, { "text-anchor": "end", class: "t-ink2" });
      colLabels.forEach((c, j) => {
        const v = values[i][j];
        const x = m.l + j * cw, y = m.t + i * cellH;
        if (v == null) {
          el("rect", { x: x + 1, y: y + 1, width: cw - 2, height: cellH - 2, rx: 4, fill: "var(--surface-2)" }, svg);
          text(svg, x + cw / 2, y + cellH / 2 + 4, "n/a", { "text-anchor": "middle" });
          return;
        }
        const t = Math.max(0, Math.min(0.999, (v - lo) / (hi - lo)));
        const si = Math.floor(t * steps.length);
        el("rect", { x: x + 1, y: y + 1, width: cw - 2, height: cellH - 2, rx: 4, fill: `var(${steps[si]})` }, svg);
        // Pick label ink by the cell's luminance (ramp runs light->dark in light mode, reversed in dark).
        const dark = document.documentElement.dataset.themeResolved === "dark";
        const ink = dark ? (si >= 5 ? "#0b0b0b" : "#f0efec") : (si >= 4 ? "#ffffff" : "#0b0b0b");
        text(svg, x + cw / 2, y + cellH / 2 + 4, Math.round(v), { "text-anchor": "middle", style: `fill:${ink};font-weight:600;font-size:12px` });
        const hit = el("rect", { x, y, width: cw, height: cellH, class: "hit" }, svg);
        hit.addEventListener("mousemove", (e) => tip.show(e, rows(`${r} · ${c}`, [["Average score", v.toFixed(1)], ...(opts.extra ? opts.extra(i, j) : [])])));
        hit.addEventListener("mouseleave", tip.hide);
      });
    });
  }

  /* ---------- Diverging horizontal bars (explanations) ---------- */
  function diverging(container, items, opts = {}) {
    const rowH = 26;
    const m = { t: 6, r: 44, b: 6, l: Math.min(opts.labelW || 210, (container.clientWidth || 600) * 0.45) };
    const H = m.t + m.b + items.length * rowH;
    const { svg, w } = svgFor(container, H);
    const iw = w - m.l - m.r;
    const maxAbs = Math.max(opts.minScale || 0.5, ...items.map((d) => Math.abs(d.v)));
    const cx = m.l + iw / 2;
    el("line", { x1: cx, x2: cx, y1: m.t, y2: H - m.b, class: "axis" }, svg);
    items.forEach((d, i) => {
      const y = m.t + i * rowH + 5;
      const bw = (Math.abs(d.v) / maxAbs) * (iw / 2 - 44); // leave room for the value label
      const pos = d.v >= 0;
      const color = pos ? opts.posColor : opts.negColor;
      const label = d.label.length > 34 ? d.label.slice(0, 33) + "…" : d.label;
      text(svg, m.l - 8, y + 12, label, { "text-anchor": "end", class: "t-ink2" });
      if (bw > 0.5) el("path", { d: barPath(pos ? cx : cx - bw, y, bw, 16, pos ? "right" : "left"), fill: color, class: "mark" }, svg);
      const vt = opts.fmt ? opts.fmt(d.v) : d.v.toFixed(1);
      text(svg, pos ? cx + bw + 4 : cx - bw - 4, y + 12, vt, { "text-anchor": pos ? "start" : "end", class: "t-ink" });
      const hit = el("rect", { x: 0, y: y - 4, width: w, height: rowH, class: "hit" }, svg);
      hit.addEventListener("mousemove", (e) => tip.show(e, d.tip || rows(d.label, [["Contribution", vt]])));
      hit.addEventListener("mouseleave", tip.hide);
    });
  }

  /* ---------- Sparkline ---------- */
  function spark(container, values, opts = {}) {
    const H = opts.height || 64;
    const m = { t: 8, r: 30, b: 16, l: 4 };
    const { svg, w } = svgFor(container, H);
    const iw = w - m.l - m.r, ih = H - m.t - m.b;
    const vals = values.map((v) => (v == null ? null : +v));
    const lo = opts.min ?? Math.min(...vals.filter((v) => v != null));
    const hi = opts.max ?? Math.max(...vals.filter((v) => v != null));
    const X = (i) => m.l + (vals.length === 1 ? iw / 2 : (i / (vals.length - 1)) * iw);
    const Y = (v) => m.t + ih - ((v - lo) / ((hi - lo) || 1)) * ih;
    if (opts.ref != null) el("line", { x1: m.l, x2: m.l + iw, y1: Y(opts.ref), y2: Y(opts.ref), stroke: "var(--critical)", opacity: 0.6 }, svg);
    el("path", { d: "M" + vals.map((v, i) => `${X(i)},${Y(v)}`).join("L"), fill: "none", stroke: opts.color || "var(--s1)", "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
    vals.forEach((v, i) => {
      const c = el("circle", { cx: X(i), cy: Y(v), r: i === vals.length - 1 ? 4 : 2.5, fill: opts.color || "var(--s1)", stroke: "var(--surface)", "stroke-width": 1.5 }, svg);
      const hit = el("rect", { x: X(i) - iw / vals.length / 2, y: 0, width: iw / vals.length, height: H, class: "hit" }, svg);
      hit.addEventListener("mousemove", (e) => tip.show(e, rows((opts.labels || [])[i] || `#${i + 1}`, [[opts.name || "Value", opts.fmt ? opts.fmt(v) : v]])));
      hit.addEventListener("mouseleave", tip.hide);
      void c;
    });
    const last = vals[vals.length - 1];
    text(svg, X(vals.length - 1) + 7, Y(last) + 4, opts.fmt ? opts.fmt(last) : last, { class: "t-ink" });
    if (opts.labels) {
      text(svg, X(0), H - 2, opts.labels[0], { "text-anchor": "start" });
      text(svg, X(vals.length - 1), H - 2, opts.labels[vals.length - 1], { "text-anchor": "end" });
    }
  }

  window.Charts = { tip, rows, esc, legend, columns, stacked, lines, scatter, heatmap, diverging, spark };
})();
