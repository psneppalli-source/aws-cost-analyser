/* Smart Campus Analytics: single-page frontend. All data and every permission
 * decision come from the API; the UI only hides controls the API would refuse. */
(function () {
  const C = window.Charts;
  const esc = C.esc;
  const app = document.getElementById("app");
  const S = { me: null, period: null, owners: null };

  /* ------------------------------------------------------------------ utils */
  async function api(path, opts = {}) {
    const token = await Auth.token();
    if (!token) { renderLogin(); throw new Error("signed out"); }
    const headers = { Authorization: "Bearer " + token, ...(opts.headers || {}) };
    if (opts.json !== undefined) { headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(opts.json); }
    const r = await fetch(path, { method: opts.method || "GET", headers, body: opts.body });
    if (r.status === 401) { Auth.signOut(); throw new Error("Session expired"); }
    if (opts.raw) { if (!r.ok) throw new Error((await r.json()).error); return r; }
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || `Request failed (${r.status})`);
    return j;
  }
  function toast(msg) {
    const t = document.getElementById("toast");
    t.textContent = msg; t.classList.add("show");
    clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), 3200);
  }
  const fmt = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? "–" : typeof v === "number" ? v.toFixed(d) : esc(v));
  const nice = (v) => (v === null || v === undefined ? "–" : typeof v === "number" ? String(Number(v.toFixed(2))) : esc(v));
  const num = (v, d = 1) => (v === null || v === undefined ? "–" : (+v).toFixed(d));
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const date = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "–");
  const dt = (iso) => (iso ? new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "–");
  function lv(level) {
    const cls = { High: "high", Medium: "medium", Low: "low", "Insufficient data": "insufficient", "Not applicable": "na" }[level] || "na";
    return `<span class="lv ${cls}">${esc(level || "–")}</span>`;
  }
  const BAND_COLOR = { "Critical": "--critical", "Needs attention": "--serious", "On track": "--neutral-band", "Thriving": "--good" };
  const LEVEL_KEYS = [
    { key: "High", label: "High", color: "--critical", labelInk: "#ffffff" },
    { key: "Medium", label: "Medium", color: "--warning", labelInk: "#0b0b0b" },
    { key: "Low", label: "Low", color: "--good", labelInk: "#0b0b0b" },
    { key: "Insufficient data", label: "Insufficient data", color: "--axis", labelInk: "#0b0b0b" },
  ];
  function hashParts() {
    const h = location.hash.replace(/^#\/?/, "");
    const [path, q] = h.split("?");
    return { parts: path.split("/").filter(Boolean), q: Object.fromEntries(new URLSearchParams(q || "")) };
  }
  function go(path, q) {
    const qs = q && Object.keys(q).length ? "?" + new URLSearchParams(Object.entries(q).filter(([, v]) => v !== "" && v != null)).toString() : "";
    location.hash = "#/" + path + qs;
  }
  function qs(obj) { return new URLSearchParams(Object.entries(obj).filter(([, v]) => v !== "" && v != null)).toString(); }

  /* ------------------------------------------------------------------ login */
  function renderLogin(err) {
    const cognito = Auth.mode === "cognito";
    app.innerHTML = `<main class="login" id="main"><div class="card form">
      <div><h1>Smart Campus Analytics</h1><p class="muted" style="margin:0">Student Success Platform</p></div>
      ${err ? `<p class="err" role="alert">${esc(err)}</p>` : ""}
      ${cognito ? `<p class="ink2" style="margin:0">Sign in with your college account. Multi-factor authentication is supported.</p>
        <button class="btn primary" id="signin" type="button">Sign in</button>`
      : `<form class="form" id="lf">
        <label class="f">Username<input id="u" autocomplete="username" required></label>
        <label class="f">Password<input id="p" type="password" autocomplete="current-password" required></label>
        <button class="btn primary" type="submit">Sign in</button>
        <p class="demo-users">Local demo accounts (password <code>Demo@2026</code>): <code>admin</code>, <code>hod.cse</code>,
          <code>mentor.cse1</code>, <code>placement</code>, <code>23civil006</code> (student).</p></form>`}
      <p class="hint" style="margin:0">All student records in this deployment are synthetic.</p></div></main>`;
    if (cognito) document.getElementById("signin").onclick = () => Auth.startCognito();
    else document.getElementById("lf").onsubmit = async (e) => {
      e.preventDefault();
      try { await Auth.localLogin(document.getElementById("u").value, document.getElementById("p").value); boot(); }
      catch (x) { renderLogin(x.message); }
    };
  }

  /* ------------------------------------------------------------------ shell */
  function nav() {
    const p = S.me.permissions, role = S.me.user.role;
    const items = role === "student" ? [["me", "My progress"]] : [
      ["dashboard", "Dashboard"], ["students", "Students"], ["interventions", "Interventions"], ["segments", "Segments"],
      ...(p.upload ? [["uploads", "Data uploads"]] : []), ["scoring", "Scoring rules"],
      ...(p.audit ? [["audit", "Audit log"]] : []), ...(p.manage_users ? [["users", "Users"]] : []),
    ];
    const cur = hashParts().parts[0] || items[0][0];
    return items.map(([k, l]) => `<a href="#/${k}" ${cur === k || (cur === "student" && k === "students") ? 'aria-current="page"' : ""}>${l}</a>`).join("");
  }
  function shell(inner) {
    const m = S.me;
    app.innerHTML = `
      <header class="topbar"><div class="topbar-inner">
        <div class="brand">
          <div class="brand-mark" aria-hidden="true">S</div>
          <div><h1 style="font-size:16px">Smart Campus Analytics</h1>
            <div class="sub">Data updated ${esc(dt(m.data_updated_at))} · Scoring v${esc(m.scoring.version)}</div></div>
          <div class="spacer"></div>
          <label class="userchip">Review
            <select class="period-select" id="period">${m.periods.map((p) => `<option value="${p.id}" ${p.id === S.period ? "selected" : ""}>${esc(p.label)}</option>`).join("")}</select></label>
          <div class="userchip"><b>${esc(m.user.name)}</b><span class="role">${esc(m.user.role_label)}${m.user.dept ? " · " + esc(m.user.dept) : ""}</span>
            <button class="icon-btn" id="theme" type="button" aria-label="Toggle theme">◐</button>
            <button class="icon-btn" id="out" type="button">Sign out</button></div>
        </div>
        <nav class="nav" aria-label="Main">${nav()}</nav>
      </div></header>
      <main id="main" tabindex="-1">${inner}</main>`;
    document.getElementById("out").onclick = () => Auth.signOut();
    document.getElementById("theme").onclick = () => {
      const dark = (document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")) === "dark";
      document.documentElement.dataset.theme = dark ? "light" : "dark";
      document.documentElement.dataset.themeResolved = dark ? "light" : "dark";
      route();
    };
    document.getElementById("period").onchange = (e) => { S.period = e.target.value; route(); };
    return document.getElementById("main");
  }
  document.documentElement.dataset.themeResolved = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";

  /* ------------------------------------------------------------------ filters */
  function filterBar(q, opts = {}) {
    const f = S.me.filters;
    const sel = (id, label, options, all) => `<label>${label}<select id="f-${id}"><option value="">${all}</option>${options.map(([v, l]) =>
      `<option value="${esc(v)}" ${String(q[id] || "") === String(v) ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>`;
    const risks = [["academic:High", "Academic: High"], ["academic:Medium", "Academic: Medium"], ["academic:Insufficient data", "Academic: insufficient data"],
      ["placement:High", "Placement: High"], ["placement:Medium", "Placement: Medium"], ["placement:Insufficient data", "Placement: insufficient data"],
      ["any:High", "Any High risk"]];
    return `<div class="filters" style="padding:0 0 14px;max-width:none" role="search">
      ${f.departments.length > 1 ? sel("dept", "Department", f.departments.map((d) => [d, d]), "All") : ""}
      ${f.courses.length > 1 ? sel("course", "Course", f.courses.map((d) => [d, d]), "All") : ""}
      ${sel("year", "Year", [1, 2, 3, 4].map((y) => [y, `Year ${y}`]), "All")}
      ${sel("cohort", "Cohort", f.cohorts.map((c) => [c, `Admitted ${c}`]), "All")}
      ${sel("risk", "Risk level", risks, "Any")}
      ${opts.segment === false ? "" : sel("segment", "Segment", f.segments.map((s) => [s.id, s.label]), "All")}
      ${opts.search === false ? "" : `<label>Search<input type="search" id="f-q" value="${esc(q.q || "")}" placeholder="Name or roll no."></label>`}
      <button class="link-btn" type="button" id="f-reset">Reset</button></div>`;
  }
  function bindFilters(page, q) {
    const ids = ["dept", "course", "year", "cohort", "risk", "segment", "q"];
    const read = () => { const o = { ...q }; ids.forEach((i) => { const el = document.getElementById("f-" + i); if (el) o[i] = el.value; }); delete o.page; return o; };
    ids.forEach((i) => {
      const el = document.getElementById("f-" + i);
      if (!el) return;
      if (i === "q") { let t; el.oninput = () => { clearTimeout(t); t = setTimeout(() => go(page, read()), 350); }; }
      else el.onchange = () => go(page, read());
    });
    const r = document.getElementById("f-reset");
    if (r) r.onclick = () => go(page, {});
  }
  const filterQuery = (q) => ({ period: S.period, dept: q.dept, course: q.course, year: q.year, cohort: q.cohort, risk: q.risk, segment: q.segment, q: q.q });

  /* ------------------------------------------------------------------ dashboard */
  async function dashboard(q) {
    const main = shell(`<div class="page-head"><h1>Dashboard</h1><span class="sub">${esc(S.me.students_visible)} students in your scope · ${esc(S.me.user.role_label)} view</span></div>
      ${filterBar(q)}<div id="dash" class="stack"><div class="loading">Loading…</div></div>`);
    bindFilters("dashboard", q);
    const d = await api("/api/dashboard?" + qs(filterQuery(q)));
    const k = d.kpis;
    const pct = (n) => (k.students ? Math.round((100 * (n || 0)) / k.students) + "%" : "–");
    const link = (extra) => "#/students?" + qs({ ...filterQuery(q), ...extra, period: undefined });
    const fr = Object.entries(d.freshness).map(([c, f]) => `<div class="item ${f.stale ? "stale" : ""}"><b>${esc(f.label)}</b>
      ${f.updated_at ? `${esc(date(f.updated_at))} · ${esc(f.period)}${f.stale ? ' <span class="pill warn">stale</span>' : ""}` : '<span class="pill bad">not loaded</span>'}</div>`).join("");
    const el = document.getElementById("dash");
    el.innerHTML = `
      <div class="grid g-kpi">
        <div class="card kpi hero"><div class="label">Average Success Score</div><div class="value">${fmt(k.avg_score)}</div>
          <div class="note">${k.students} students · ${k.provisional} provisional${k.insufficient ? `, ${k.insufficient} withheld` : ""}</div>
          <div class="meter"><span style="width:${k.avg_score || 0}%"></span></div></div>
        <a class="card kpi clickable" href="${link({ risk: "academic:High" })}" style="text-decoration:none;color:inherit"><div class="label">High academic risk</div>
          <div class="value">${k.academic.High || 0}</div><div class="note">${pct(k.academic.High)} · ${k.academic["Insufficient data"] || 0} with insufficient data</div></a>
        <a class="card kpi clickable" href="${link({ risk: "placement:High" })}" style="text-decoration:none;color:inherit"><div class="label">High placement risk</div>
          <div class="value">${k.placement.High || 0}</div><div class="note">of ${Object.values(k.placement).reduce((a, b) => a + b, 0)} in placement years · ${k.placement["Insufficient data"] || 0} untested</div></a>
        <a class="card kpi clickable" href="#/students?${qs({ ...filterQuery(q), period: undefined, review: 1 })}" style="text-decoration:none;color:inherit"><div class="label">Need review</div>
          <div class="value">${k.needs_review}</div><div class="note">high risk without action, overdue, declining or missing data</div></a>
        <a class="card kpi clickable" href="#/interventions?overdue=1" style="text-decoration:none;color:inherit"><div class="label">Overdue actions</div>
          <div class="value ${k.overdue_actions ? "overdue" : ""}">${k.overdue_actions}</div><div class="note">of ${k.open_actions} open interventions</div></a>
      </div>
      <details class="box"><summary>Data freshness</summary><div class="fresh" style="margin-top:10px">${fr}</div></details>
      <div class="grid g-2">
        <div class="card"><div class="card-head"><h2>Success Score distribution</h2><span class="desc">Students per 5-point bucket. Click a bar to list them.</span></div>
          <div class="chart" id="ch-hist"></div><div class="legend" id="lg-hist"></div></div>
        <div class="card"><div class="card-head"><h2>Students needing review</h2><span class="desc">Highest priority first. Click a name to open the profile.</span></div>
          <div class="table-wrap" style="max-height:330px;overflow:auto"><table><thead><tr><th>Student</th><th>Score</th><th>Why</th></tr></thead><tbody>
          ${d.needs_review.slice(0, 25).map((n) => `<tr><td><a class="rowlink" href="#/student/${n.student_id}">${esc(n.name)}</a><div class="hint">${n.student_id} · ${esc(n.dept)} · Y${n.year}</div></td>
            <td class="num">${fmt(n.score)}</td><td>${n.reasons.map((r) => `<span class="pill ${/High|overdue/.test(r) ? "bad" : "warn"}">${esc(r)}</span>`).join("")}</td></tr>`).join("") || '<tr><td colspan="3" class="empty">Nobody needs review.</td></tr>'}
          </tbody></table></div></div>
      </div>
      <div class="grid g-2">
        <div class="card"><div class="card-head"><h2>Academic risk by department</h2><span class="desc">Click a segment to list those students.</span></div>
          <div class="chart" id="ch-acad"></div><div class="legend" id="lg-acad"></div></div>
        <div class="card"><div class="card-head"><h2>Placement risk by department</h2><span class="desc">Students in placement years only (B.Tech year 3+, MCA year 2).</span></div>
          <div class="chart" id="ch-place"></div><div class="legend" id="lg-place"></div></div>
      </div>
      <h2 class="section-title">Trends over time</h2>
      <div class="grid g-2">
        <div class="card"><div class="card-head"><h2>Average score by review</h2><span class="desc">Same filtered students in each review period.</span></div><div class="chart" id="ch-score"></div></div>
        <div class="card"><div class="card-head"><h2>High academic risk by review</h2><span class="desc">Share of students flagged High.</span></div><div class="chart" id="ch-hi"></div></div>
        <div class="card"><div class="card-head"><h2>Attendance by month</h2><span class="desc">Average attendance against the 75% exam-eligibility rule.</span></div><div class="chart" id="ch-att"></div></div>
        <div class="card"><div class="card-head"><h2>LMS logins per week</h2><span class="desc">Average per student, both terms.</span></div><div class="chart" id="ch-lms"></div></div>
        <div class="card"><div class="card-head"><h2>Participation by month</h2><span class="desc">Events, clubs, projects, hackathons and certifications logged.</span></div><div class="chart" id="ch-part"></div></div>
        <div class="card"><div class="card-head"><h2>Segments</h2><span class="desc">Click to see the group and its playbook.</span></div><div class="chart" id="ch-seg"></div></div>
      </div>`;
    // histogram
    const bins = [];
    const bandOf = (x) => d.bands.find((b) => x >= b.min).label;
    for (let x = 0; x < 100; x += 5) {
      const n = d.distribution.filter((v) => v >= x && v < x + 5).length;
      const b = bandOf(x);
      bins.push({ label: String(x), v: n, color: css(BAND_COLOR[b]), range: [x, x + 5], tip: C.rows(`Score ${x}–${x + 5}`, [["Students", n], ["Band", b]]) });
    }
    C.columns(document.getElementById("ch-hist"), bins, { height: 230, xLabelEvery: 2, onClick: (b) => b.v && (location.hash = link({ score_min: b.range[0], score_max: b.range[1] })) });
    C.legend(document.getElementById("lg-hist"), d.bands.slice().reverse().map((b, i, arr) => ({ label: `${b.label} ${i < arr.length - 1 ? b.min + "–" + arr[i + 1].min : "≥ " + b.min}`, color: css(BAND_COLOR[b.label]) })));
    for (const kind of ["academic", "placement"]) {
      const rows = d.risk_by_dept[kind].map((r) => ({ label: r.dept, values: r }));
      const el2 = document.getElementById(kind === "academic" ? "ch-acad" : "ch-place");
      if (!rows.length) { el2.innerHTML = '<div class="empty">No students in scope.</div>'; continue; }
      const keys = LEVEL_KEYS.map((x) => ({ ...x, color: css(x.color) }));
      C.stacked(el2, rows, keys, { labelW: 56, onClick: (row, key) => (location.hash = link({ dept: row.label, risk: `${kind}:${key.key}` })) });
      C.legend(document.getElementById(kind === "academic" ? "lg-acad" : "lg-place"), keys.map((x) => ({ label: x.label, color: x.color })));
    }
    const ts = d.trends.scores;
    C.columns(document.getElementById("ch-score"), ts.map((t) => ({ label: t.period, v: t.avg_score || 0, color: css("--s1"), tip: C.rows(t.label, [["Average score", fmt(t.avg_score)], ["Students", t.students]]) })), { height: 180, yMax: 100, valueLabels: true, barMax: 56 });
    C.columns(document.getElementById("ch-hi"), ts.map((t) => ({ label: t.period, v: t.academic_high_pct || 0, color: css("--critical"), tip: C.rows(t.label, [["High academic risk", fmt(t.academic_high_pct) + "%"]]) })), { height: 180, yFmt: (v) => Math.round(v) + "%", valueLabels: true, barMax: 56 });
    const att = d.trends.attendance;
    if (att.length) C.lines(document.getElementById("ch-att"), [{ name: "Average attendance", short: "Avg", color: css("--s1"), values: att.map((a) => a.avg) }],
      att.map((a) => new Date(a.month + "-01").toLocaleDateString(undefined, { month: "short", year: "2-digit" })), { yMin: 50, yMax: 100, ticks: 5, ref: 75, refLabel: "75% rule", yFmt: (v) => Math.round(v) + "%", endLabelW: 40 });
    const lms = d.trends.lms;
    if (lms.length) C.lines(document.getElementById("ch-lms"), [{ name: "Logins per week", short: "Avg", color: css("--s1"), values: lms.map((a) => a.avg) }],
      lms.map((a) => new Date(a.week).toLocaleDateString(undefined, { day: "numeric", month: "short" })), { yMin: 0, ticks: 5, xEvery: 4, yFmt: (v) => (+v).toFixed(0), endLabelW: 40 });
    const part = d.trends.participation;
    C.columns(document.getElementById("ch-part"), part.map((m) => {
      const tot = ["event", "club", "project", "hackathon", "certification"].reduce((a, t) => a + (m[t] || 0), 0);
      return { label: new Date(m.month + "-01").toLocaleDateString(undefined, { month: "short" }), v: tot, color: css("--s3"),
        tip: C.rows(m.month, [["Total", tot], ...["event", "club", "project", "hackathon", "certification"].map((t) => [t[0].toUpperCase() + t.slice(1) + "s", m[t] || 0])]) };
    }), { height: 200 });
    const segMax = Math.max(1, ...d.segments.map((x) => x.count));
    document.getElementById("ch-seg").innerHTML = `<div style="display:grid;gap:8px">${d.segments.filter((x) => x.count).map((x) =>
      `<a href="${link({ segment: x.id })}" style="display:grid;grid-template-columns:minmax(120px,240px) 1fr 40px;gap:10px;align-items:center;color:inherit;text-decoration:none;font-size:13px">
        <span>${esc(x.label)}</span><span style="height:14px;background:var(--surface-2);border-radius:0 4px 4px 0"><span style="display:block;height:100%;width:${(100 * x.count) / segMax}%;background:var(--s1);border-radius:0 4px 4px 0"></span></span>
        <b class="num" style="text-align:right">${x.count}</b></a>`).join("")}</div>`;
  }

  /* ------------------------------------------------------------------ students */
  async function students(q) {
    const page = +(q.page || 1);
    const main = shell(`<div class="page-head"><h1>Students</h1><span class="sub" id="cnt"></span></div>
      ${filterBar(q)}
      <div class="toolbar"><label class="row" style="font-size:13px"><input type="checkbox" id="rev" ${q.review === "1" ? "checked" : ""}> Needs review only</label>
        ${q.score_min ? `<span class="pill">Score ${esc(q.score_min)}–${esc(q.score_max)} <a href="#/students?${qs({ ...q, score_min: "", score_max: "" })}" aria-label="Clear score filter">✕</a></span>` : ""}
        <span class="spacer"></span><button class="btn" id="csv" type="button">Export CSV</button></div>
      <div class="table-wrap"><table><thead><tr id="hdr"></tr></thead><tbody id="rows"><tr><td class="loading">Loading…</td></tr></tbody></table></div>
      <div class="pager" id="pager"></div>`);
    bindFilters("students", q);
    document.getElementById("rev").onchange = (e) => go("students", { ...q, review: e.target.checked ? 1 : "", page: "" });
    const cols = [["name", "Student"], ["dept", "Dept"], ["year", "Yr"], ["score", "Success Score"], ["academic_points", "Academic risk"],
      ["placement_points", "Placement risk"], ["segment_label", "Segment"], ["top_gap", "Biggest gap"], ["mentor", "Mentor"]];
    const sort = q.sort || "academic_points", dir = q.dir || "desc";
    document.getElementById("hdr").innerHTML = cols.map(([k, l]) => `<th class="sortable" data-k="${k}" tabindex="0" aria-sort="${sort === k ? (dir === "desc" ? "descending" : "ascending") : "none"}">${l}${sort === k ? ` <span class="arrow">${dir === "desc" ? "▼" : "▲"}</span>` : ""}</th>`).join("");
    document.querySelectorAll("#hdr th").forEach((th) => {
      const f = () => go("students", { ...q, sort: th.dataset.k, dir: sort === th.dataset.k && dir === "desc" ? "asc" : "desc", page: "" });
      th.onclick = f; th.onkeydown = (e) => e.key === "Enter" && f();
    });
    const params = { ...filterQuery(q), sort, dir, page, size: 50, review: q.review, score_min: q.score_min, score_max: q.score_max };
    const d = await api("/api/students?" + qs(params));
    document.getElementById("cnt").textContent = `${d.total} students · ${S.me.periods.find((p) => p.id === d.period).label}`;
    document.getElementById("rows").innerHTML = d.rows.map((r) => `<tr>
      <td><a class="rowlink" href="#/student/${r.student_id}">${esc(r.name)}</a><div class="hint">${r.student_id} · ${esc(r.course)}</div></td>
      <td>${esc(r.dept)}</td><td class="num">${r.year}</td>
      <td><div class="score-cell"><b>${fmt(r.score)}</b><div class="bar"><span style="width:${r.score || 0}%;background:${css(BAND_COLOR[r.band] || "--axis")}"></span></div></div>
        <div class="hint">${esc(r.band)}${r.score_status === "provisional" ? ' · <span class="pill warn">provisional</span>' : ""}${r.score_change != null ? ` · ${r.score_change > 0 ? "▲" : r.score_change < 0 ? "▼" : ""}${Math.abs(r.score_change)}` : ""}</div></td>
      <td>${lv(r.academic)}</td><td>${lv(r.placement)}</td><td style="font-size:12.5px">${esc(r.segment_label)}</td>
      <td class="ink2" style="font-size:12.5px">${esc(r.top_gap || "–")}</td><td style="font-size:12.5px">${esc(r.mentor || "–")}</td></tr>`).join("")
      || `<tr><td colspan="9" class="empty">No students match these filters.</td></tr>`;
    const pages = Math.max(1, Math.ceil(d.total / d.size));
    document.getElementById("pager").innerHTML = `<span>Page ${page} of ${pages}</span>
      <button type="button" ${page <= 1 ? "disabled" : ""} id="pp">Previous</button><button type="button" ${page >= pages ? "disabled" : ""} id="pn">Next</button>`;
    document.getElementById("pp").onclick = () => go("students", { ...q, page: page - 1 });
    document.getElementById("pn").onclick = () => go("students", { ...q, page: page + 1 });
    document.getElementById("csv").onclick = async () => {
      const r = await api("/api/students?" + qs({ ...params, format: "csv" }), { raw: true });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(await r.blob());
      a.download = `students_${S.period}.csv`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    };
  }

  /* ------------------------------------------------------------------ profile */
  async function profile(sid) {
    const main = shell('<div class="loading">Loading profile…</div>');
    let d;
    try { d = await api(`/api/students/${sid}?period=${S.period}`); }
    catch (e) { main.innerHTML = `<div class="card empty">${esc(e.message)}</div>`; return; }
    const st = d.student, s = d.snapshot, sc = s.score, f = s.features;
    const isStudent = S.me.user.role === "student";
    const pillars = Object.fromEntries(S.me.pillars.map((p) => [p.key, p]));
    const levelText = S.me.risk_levels.filter((l) => l.min_points > 0).map((l) => `${l.name} at ${l.min_points}+`).join(", ");
    const statusPill = sc.status === "provisional" ? `<span class="pill warn" title="Data coverage ${Math.round(sc.coverage * 100)}%">Provisional</span>`
      : sc.status === "insufficient" ? '<span class="pill bad">Withheld: not enough data</span>' : "";
    const risk = (kind) => {
      const r = s.risk[kind];
      if (r.level === "Not applicable") return `<p class="muted">Placement risk starts in the placement years (B.Tech year 3, MCA year 2).</p>`;
      return `<div class="row" style="margin-bottom:8px">${lv(r.level)} <span class="hint">${r.points} risk points · ${esc(levelText)}</span></div>
        ${r.missing.length ? `<p class="err" style="margin:0 0 8px">Missing evidence: ${esc(r.missing.join(", "))}. ${r.level === "Insufficient data" ? "This is not the same as low risk." : ""}</p>` : ""}
        ${r.evidence.length ? `<ul class="evidence">${r.evidence.map((e) => `<li><div class="top"><span class="rule-id">${esc(e.rule)}</span><b>${esc(e.why)}</b><span class="pts">+${e.points}</span></div>
          <div>${esc(e.label)}: <b>${e.value === null ? "restricted" : typeof e.value === "boolean" ? (e.value ? "yes" : "no") : nice(e.value)}${esc(e.unit || "")}</b>
          <span class="hint">(rule: ${esc(e.op)} ${esc(Array.isArray(e.threshold) ? e.threshold.join("–") : String(e.threshold))})</span></div>
          ${e.source ? `<div class="src">Source: ${esc(e.source.file || "")} · ${esc(e.source.period || "")} · updated ${esc(date(e.source.updated))}${e.source.note ? " · " + esc(e.source.note) : ""}</div>` : ""}</li>`).join("")}</ul>`
        : '<p class="muted" style="margin:0">No risk rules triggered.</p>'}`;
    };
    const groups = Object.keys(pillars).map((pk) => {
      const inds = sc.indicators.filter((i) => i.pillar === pk);
      return `<tr><th colspan="4" style="background:var(--surface)">${esc(pillars[pk].label)} <span class="hint">${Math.round(pillars[pk].weight * 100)}% · pillar ${fmt(sc.pillars[pk])}</span></th></tr>` +
        inds.map((i) => `<tr><td>${esc(i.label)}</td><td class="num">${i.status === "used" ? nice(i.value) : `<span class="pill ${i.status === "missing" ? "warn" : ""}">${i.status === "missing" ? "missing" : "n/a for year"}</span>`}</td>
          <td class="num">${i.status === "used" ? fmt(i.indicator_score, 0) : "–"}</td>
          <td>${i.status === "used" ? `<div class="bar-cell"><div class="track" title="${i.points} of ${i.max_points} possible points"><span style="width:${(i.points / Math.max(...sc.indicators.filter((x) => x.max_points).map((x) => x.max_points))) * 100}%"></span><i style="left:0;width:${(i.max_points / Math.max(...sc.indicators.filter((x) => x.max_points).map((x) => x.max_points))) * 100}%"></i></div><span class="num" style="width:76px;text-align:right">${num(i.points, 2)} / ${num(i.max_points, 1)}</span></div>` : '<span class="hint">excluded</span>'}</td></tr>`).join("");
    }).join("");
    const can = S.me.permissions;
    main.innerHTML = `
      <div class="stack">
      <div class="card profile-head">
        <div class="who"><div class="hint"><a href="#/students">Students</a> / ${esc(st.student_id)}</div><h1>${esc(st.name)}</h1>
          <div class="meta-line">${esc(st.student_id)} · ${esc(st.dept)} · ${esc(st.course)} · Year ${st.year} · Admitted ${st.cohort} · Mentor: ${esc(st.mentor || "unassigned")}</div>
          <div class="row" style="margin-top:8px">${lv(s.risk.academic.level)}<span class="hint">academic</span> ${lv(s.risk.placement.level)}<span class="hint">placement</span>
            <span class="pill">${esc(s.segment.label)}</span> ${statusPill}</div></div>
        <div class="scorebox"><div class="v">${sc.score === null ? "–" : num(sc.score)}</div><div class="b">${esc(sc.band)} · Success Score</div>
          <div class="hint">Coverage ${Math.round(sc.coverage * 100)}% · v${esc(d.scoring.version)}</div></div>
      </div>
      <div class="grid g-2">
        <div class="card"><div class="card-head"><h2>Why this score</h2><span class="desc">Each indicator's points = its weight share × its 0–100 score. Points add up exactly to ${fmt(sc.score)}. Missing indicators are excluded and the remaining weights rescaled, never counted as zero.</span></div>
          <div class="table-wrap"><table><thead><tr><th>Indicator</th><th class="num">Value</th><th class="num">0–100</th><th>Points earned / possible</th></tr></thead><tbody>${groups}</tbody></table></div></div>
        <div class="stack">
          <div class="card"><div class="card-head"><h2>Academic risk</h2><span class="desc">Every rule that fired, with the value, threshold and source record.</span></div>${risk("academic")}</div>
          <div class="card"><div class="card-head"><h2>Placement risk</h2></div>${risk("placement")}</div>
        </div>
      </div>
      <div class="grid g-2">
        <div class="card"><div class="card-head"><h2>Progress across reviews</h2></div>
          <div class="table-wrap"><table><thead><tr><th>Review</th><th class="num">Score</th><th>Band</th><th>Academic</th><th>Placement</th></tr></thead><tbody>
          ${d.history.map((h) => `<tr><td>${esc(h.label)}</td><td class="num">${fmt(h.score)}${h.status === "provisional" ? " *" : ""}</td><td>${esc(h.band)}</td><td>${lv(h.academic)}</td><td>${lv(h.placement)}</td></tr>`).join("")}
          </tbody></table></div>${d.history.some((h) => h.status === "provisional") ? '<p class="hint">* provisional score (incomplete data)</p>' : ""}
          ${s.changes.score_change != null ? `<p class="ink2" style="margin:8px 0 0">Change since previous review: <b>${s.changes.score_change > 0 ? "+" : ""}${s.changes.score_change}</b> points.</p>` : ""}</div>
        <div class="card"><div class="card-head"><h2>Segment: ${esc(s.segment.label)}</h2><span class="desc">Why this student is in this group</span></div>
          <ul style="margin:0">${s.segment.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
          ${d.segment_def ? `<p class="ink2" style="font-size:13px"><b>Playbook.</b> ${esc(d.segment_def.playbook)} <span class="hint">Owner: ${esc(d.segment_def.owner)}</span></p>` : ""}</div>
      </div>
      ${isStudent ? "" : `<div class="card" id="actions-card"></div>`}
      <div class="card" id="int-card"></div>
      <div class="card"><div class="card-head"><h2>Unified record</h2><span class="desc">Assembled from every source for ${esc(S.me.periods.find((p) => p.id === d.period).label)}.</span></div>
        <div class="src-grid">
          ${src("Academic", [["CGPA", f.cgpa], ["Active backlogs", f.backlogs], ["SGPA trend", f.sgpa_trend], ["Internal marks avg", f.internal_pct != null ? f.internal_pct + "%" : null], ["Weakest subject", f.weakest_subject ? `${f.weakest_subject} (${f.weakest_subject_pct}%)` : null]])}
          ${src("Attendance", [["Overall", f.attendance_pct != null ? f.attendance_pct + "%" : null], ["Lowest subject", f.attendance_min_subject ? `${f.attendance_min_subject} (${f.attendance_min_subject_pct}%)` : null], ["Subjects under 75%", f.subjects_below_75], ["Change in term", f.attendance_trend != null ? f.attendance_trend + " pts" : null]])}
          ${src("LMS", [["Assignments submitted", f.lms_completion_pct != null ? f.lms_completion_pct + "%" : null], ["Logins / week", f.lms_logins_per_week], ["Quiz average", f.lms_quiz_avg], ["Last 4 vs first 4 weeks", f.lms_login_trend != null ? Math.round(f.lms_login_trend * 100) + "%" : null]])}
          ${src("Engagement (12 months)", [["Events", f.events], ["Clubs", f.clubs], ["Projects & hackathons", f.projects_hackathons], ["Certifications", f.certifications]])}
          ${src("Placement", s.placement_year ? [["Tests taken", f.placement_tests], ["Aptitude", f.aptitude_score], ["Coding", f.coding_score], ["Mock interview", f.mock_interview_rating != null ? f.mock_interview_rating + "/5" : null], ["Resume reviewed", f.resume_reviewed == null ? null : f.resume_reviewed ? "Yes" : "No"]] : [["Status", "Not yet in placement years"]])}
          ${src("Skills", [["Technical", f.technical], ["Communication", f.communication], ["Teamwork", f.teamwork], ["Problem solving", f.problem_solving]])}
          ${src("Feedback", [["Satisfaction", f.satisfaction != null ? f.satisfaction + "/5" : null], ...(f.stress !== null && f.stress !== undefined ? [["Stress", f.stress + "/5"]] : []), ["Faculty rating", f.faculty_rating != null ? f.faculty_rating + "/5" : null]])}
        </div>
        ${s.detail.faculty_remark ? `<p class="remark" style="margin-top:12px">Mentor remark: “${esc(s.detail.faculty_remark)}”${s.detail.concern_tags && s.detail.concern_tags.length ? ` <span class="pill bad">${esc(s.detail.concern_tags.join(", "))}</span>` : ""}</p>` : ""}
        <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr));margin-top:12px">
          <div><h3 style="font-size:13px">Attendance by month</h3><div class="chart" id="sp-att"></div></div>
          <div><h3 style="font-size:13px">LMS logins per week</h3><div class="chart" id="sp-lms"></div></div>
          <div><h3 style="font-size:13px">SGPA by semester</h3><div class="chart" id="sp-sgpa"></div></div>
        </div>
        ${s.detail.subjects ? `<details class="box" style="margin-top:12px"><summary>Subject-wise internals and attendance</summary><div class="table-wrap" style="margin-top:8px"><table><thead><tr><th>Subject</th><th class="num">Internals %</th></tr></thead><tbody>
          ${Object.entries(s.detail.subjects).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="num">${v}</td></tr>`).join("")}</tbody></table></div>
          ${s.detail.attendance_by_subject ? `<div class="table-wrap" style="margin-top:8px"><table><thead><tr><th>Subject</th><th class="num">Attendance %</th></tr></thead><tbody>${Object.entries(s.detail.attendance_by_subject).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="num ${v < 75 ? "overdue" : ""}">${v}</td></tr>`).join("")}</tbody></table></div>` : ""}</details>` : ""}
      </div>
      <div class="card"><div class="card-head"><h2>Data freshness and completeness</h2><span class="desc">Coverage ${Math.round(sc.coverage * 100)}% of expected indicators · scored ${esc(dt(d.scoring.computed_at))} with rules v${esc(d.scoring.version)}</span></div>
        <div class="cov" aria-label="Coverage"><span style="width:${sc.coverage * 100}%"></span></div>
        ${sc.missing.length ? `<p class="ink2" style="font-size:13px">Missing: ${esc(sc.missing.join(", "))}</p>` : '<p class="ok-text" style="font-size:13px">All expected indicators present.</p>'}
        <div class="fresh">${Object.entries(d.freshness).map(([k, v]) => `<div class="item ${v.stale || v.missing ? "stale" : ""}"><b>${esc(v.label)}</b>
          ${v.missing ? '<span class="pill warn">no records</span>' : `${esc(v.file || v.note || "")}<br>${v.period ? esc(v.period) + " · " : ""}updated ${esc(date(v.updated))}${v.stale ? ' <span class="pill warn">stale</span>' : ""}`}</div>`).join("")}</div></div>
      ${d.can.summary ? `<div class="card" id="sum-card"><div class="card-head"><h2>Draft summary</h2><span class="desc">Generated only from this student's records. Review and edit before saving; students never see drafts.</span></div>
        <button class="btn" type="button" id="gen">Draft a summary</button><div id="sum-area"></div>
        ${d.summaries.length ? `<h3 style="font-size:13px;margin-top:12px">Saved summaries</h3><ul class="notes">${d.summaries.map((x) => `<li>${esc(x.text)}<div class="when">${esc(x.approved_by)} · ${esc(dt(x.approved_at))}${x.edited ? " · edited" : ""}</div></li>`).join("")}</ul>` : ""}</div>` : ""}
      </div>`;
    const sp = s.series;
    if (sp.attendance && sp.attendance.length) C.spark(document.getElementById("sp-att"), sp.attendance.map((x) => x.pct), { min: 40, max: 100, ref: 75, labels: sp.attendance.map((x) => x.month), name: "Attendance", fmt: (v) => Math.round(v) + "%", color: css("--s1") });
    if (sp.lms && sp.lms.length) C.spark(document.getElementById("sp-lms"), sp.lms.map((x) => x.logins), { min: 0, max: Math.max(8, ...sp.lms.map((x) => x.logins)), labels: sp.lms.map((x) => x.week), name: "Logins", color: css("--s1") });
    if (sp.sgpa && sp.sgpa.length) C.spark(document.getElementById("sp-sgpa"), sp.sgpa.map((x) => x.sgpa), { min: 4, max: 10, labels: sp.sgpa.map((x) => x.term), name: "SGPA", fmt: (v) => (+v).toFixed(2), color: css("--s1") });
    if (!isStudent) renderActions(d);
    renderInterventions(document.getElementById("int-card"), d.interventions, { student: d, title: "Interventions for this student" });
    const gen = document.getElementById("gen");
    if (gen) gen.onclick = async () => {
      const r = await api(`/api/students/${sid}/summary-draft?period=${S.period}`);
      document.getElementById("sum-area").innerHTML = `<p class="hint">${esc(r.notice)}</p><textarea id="sum-text" rows="7" aria-label="Summary draft">${esc(r.draft)}</textarea>
        <div class="row" style="margin-top:8px"><button class="btn primary" type="button" id="sum-save">Approve and save</button><button class="btn" type="button" id="sum-x">Discard</button></div>`;
      document.getElementById("sum-x").onclick = () => (document.getElementById("sum-area").innerHTML = "");
      document.getElementById("sum-save").onclick = async () => {
        await api(`/api/students/${sid}/summary`, { method: "POST", json: { text: document.getElementById("sum-text").value, generated: r.draft } });
        toast("Summary saved"); profile(sid);
      };
    };
  }
  function src(title, pairs) {
    return `<div class="src"><h4>${esc(title)}</h4><dl class="kv">${pairs.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v === null || v === undefined ? '<span class="hint">no data</span>' : esc(typeof v === "number" ? +v.toFixed(2) : v)}</dd>`).join("")}</dl></div>`;
  }
  async function owners() {
    if (!S.owners) S.owners = await api("/api/owners");
    return S.owners;
  }
  function addDays(n) { const d = new Date(); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); }

  async function renderActions(d) {
    const el = document.getElementById("actions-card");
    const acts = d.snapshot.actions || [];
    el.innerHTML = `<div class="card-head"><h2>Suggested actions</h2><span class="desc">Linked to the risk rules above. Choose one to create a tracked intervention.</span></div>
      ${acts.length ? `<div class="table-wrap"><table><thead><tr><th>Action</th><th>For</th><th>Owner</th><th></th></tr></thead><tbody>
      ${acts.map((a, i) => `<tr><td><b>${esc(a.title)}</b><div class="hint">${esc(a.detail)}</div><div class="rule-id">${esc(a.rules.join(", "))}</div></td>
        <td>${esc(a.risk)}</td><td>${a.owner_role === "placement" ? "Placement Officer" : "Mentor"}</td>
        <td>${a.already_open ? '<span class="pill">already open</span>' : a.can_create ? `<button class="btn small" type="button" data-i="${i}">Create</button>` : '<span class="hint">not your action</span>'}</td></tr>`).join("")}
      </tbody></table></div>` : '<p class="muted">No risk rules triggered, so nothing is suggested.</p>'}
      ${d.can.create ? '<button class="link-btn" type="button" id="custom-act">+ Custom action</button>' : ""}
      <div id="act-form"></div>`;
    const open = async (a) => {
      const os = await owners();
      const def = a.owner_role === "placement" ? (S.me.user.role === "placement" ? S.me.user.username : "placement") : d.student.mentor_username;
      document.getElementById("act-form").innerHTML = `<form class="form card" style="margin-top:12px" id="af">
        <label class="f">Action<input id="af-title" required value="${esc(a.title || "")}"></label>
        <label class="f">Details<textarea id="af-detail" rows="2">${esc(a.detail || "")}</textarea></label>
        <div class="grid2"><label class="f">Owner<select id="af-owner">${os.map((o) => `<option value="${esc(o.username)}" ${o.username === def ? "selected" : ""}>${esc(o.name)} (${esc(o.role)})</option>`).join("")}</select></label>
          <label class="f">Due date<input type="date" id="af-due" required value="${addDays(a.due_days || 14)}"></label>
          <label class="f">Review date<input type="date" id="af-review" required value="${addDays(a.review_days || 30)}"></label></div>
        <label class="f">Note (optional)<textarea id="af-note" rows="2"></textarea></label>
        <div class="row"><button class="btn primary" type="submit">Create intervention</button><button class="btn" type="button" id="af-x">Cancel</button><span class="err" id="af-err"></span></div></form>`;
      document.getElementById("af-x").onclick = () => (document.getElementById("act-form").innerHTML = "");
      document.getElementById("af").onsubmit = async (e) => {
        e.preventDefault();
        try {
          await api("/api/interventions", { method: "POST", json: { student_id: d.student.student_id, action_id: a.action_id, risk: a.risk, rules: a.rules,
            owner_role: a.owner_role, title: document.getElementById("af-title").value, detail: document.getElementById("af-detail").value,
            owner: document.getElementById("af-owner").value, due_date: document.getElementById("af-due").value,
            review_date: document.getElementById("af-review").value, note: document.getElementById("af-note").value } });
          toast("Intervention created"); profile(d.student.student_id);
        } catch (x) { document.getElementById("af-err").textContent = x.message; }
      };
      document.getElementById("af-title").focus();
    };
    el.querySelectorAll("button[data-i]").forEach((b) => (b.onclick = () => open(acts[+b.dataset.i])));
    const c = document.getElementById("custom-act");
    if (c) c.onclick = () => open({ title: "", detail: "", owner_role: S.me.user.role === "placement" ? "placement" : "mentor", risk: "general", rules: [], due_days: 14, review_days: 30 });
  }

  /* ------------------------------------------------------------------ interventions */
  function renderInterventions(el, items, opts = {}) {
    const isStudent = S.me.user.role === "student";
    el.innerHTML = `<div class="card-head"><h2>${esc(opts.title || "Interventions")}</h2>${opts.desc ? `<span class="desc">${esc(opts.desc)}</span>` : ""}</div>
      ${items.length ? `<div class="table-wrap"><table><thead><tr>${opts.student ? "" : "<th>Student</th>"}<th>Action</th><th>Owner</th><th>Due</th><th>Review</th><th>Status</th>${isStudent ? "" : "<th>Progress</th>"}</tr></thead><tbody>
      ${items.map((i, n) => `<tr class="${i.overdue ? "hl" : ""}">
        ${opts.student ? "" : `<td><a class="rowlink" href="#/student/${i.student_id}">${esc(i.student_name)}</a><div class="hint">${i.student_id} · ${esc(i.dept)}</div></td>`}
        <td><b>${esc(i.title)}</b>${i.risk ? `<div class="hint">${esc(i.risk)}${i.rules && i.rules.length ? " · " + esc(i.rules.join(", ")) : ""}</div>` : ""}</td>
        <td>${esc(i.owner_name || i.owner || i.owner_role)}</td>
        <td>${esc(i.due_date)}${i.overdue ? `<div class="overdue">${i.days_overdue} days overdue</div>` : ""}</td>
        <td>${esc(i.review_date || "–")}${i.review_due && !i.overdue ? '<div class="pill warn">review due</div>' : ""}</td>
        <td><span class="status ${esc(i.status)}">${esc(i.status)}</span>${i.outcome ? `<div class="hint">${esc(i.outcome)}</div>` : ""}</td>
        ${isStudent ? "" : `<td>${i.progress ? `${fmt(i.baseline.score)} → ${fmt(i.progress.latest_score)}${i.progress.change != null ? ` <b class="${i.progress.change >= 0 ? "ok-text" : "overdue"}">(${i.progress.change > 0 ? "+" : ""}${i.progress.change})</b>` : ""}<div class="hint">${esc(i.baseline.period || "")} → now</div>` : fmt(i.baseline && i.baseline.score)}
          ${i.notes ? `<details><summary class="hint">Details${i.notes.length ? ` · ${i.notes.length} notes` : ""}</summary>
            ${i.detail ? `<p style="font-size:13px">${esc(i.detail)}</p>` : ""}
            <ul class="notes">${i.notes.map((x) => `<li>${esc(x.text)}<div class="when">${esc(x.by)} · ${esc(dt(x.at))}</div></li>`).join("")}</ul>
            ${i.outcome_note ? `<p class="hint">Outcome: ${esc(i.outcome_note)}</p>` : ""}
            ${i.can ? updForm(i, n) : ""}</details>` : ""}</td>`}
      </tr>`).join("")}</tbody></table></div>` : '<p class="muted">No interventions yet.</p>'}`;
    el.querySelectorAll("form[data-iid]").forEach((form) => {
      form.onsubmit = async (e) => {
        e.preventDefault();
        const g = (k) => form.querySelector(`[name=${k}]`);
        const body = { note: g("note").value };
        if (g("status")) {
          const it = items.find((x) => x.id === form.dataset.iid);
          if (g("status").value !== it.status) body.status = g("status").value;
          if (g("due").value !== it.due_date) body.due_date = g("due").value;
          if (g("review").value !== it.review_date) body.review_date = g("review").value;
          if (g("outcome").value) { body.outcome = g("outcome").value; body.outcome_note = g("onote").value; }
        }
        try { await api(`/api/interventions/${form.dataset.iid}`, { method: "PATCH", json: body }); toast("Intervention updated"); route(); }
        catch (x) { form.querySelector(".err").textContent = x.message; }
      };
    });
  }
  function updForm(i) {
    const full = i.can === "full";
    return `<form class="form" data-iid="${i.id}" style="margin-top:8px">
      ${full ? `<div class="grid2"><label class="f">Status<select name="status">${["Open", "In Progress", "Completed"].map((s) => `<option ${s === i.status ? "selected" : ""}>${s}</option>`).join("")}</select></label>
        <label class="f">Due<input type="date" name="due" value="${i.due_date}"></label><label class="f">Review<input type="date" name="review" value="${i.review_date}"></label>
        <label class="f">Outcome<select name="outcome"><option value="">${i.outcome ? esc(i.outcome) + " (unchanged)" : "Not recorded"}</option>${["Improved", "No change", "Worse", "Not assessed"].map((o) => `<option>${o}</option>`).join("")}</select></label></div>
        <label class="f">Outcome note<input name="onote" value="${esc(i.outcome_note || "")}"></label>` : '<p class="hint">You can add monitoring notes.</p>'}
      <label class="f">Note<textarea name="note" rows="2"></textarea></label>
      <div class="row"><button class="btn primary small" type="submit">Save</button><span class="err"></span></div></form>`;
  }
  async function interventionsPage(q) {
    const main = shell(`<div class="page-head"><h1>Interventions</h1><span class="sub" id="cnt"></span></div>
      <div class="filters" style="padding:0 0 14px;max-width:none">
        <label>Status<select id="i-status"><option value="">All</option>${["Open", "In Progress", "Completed"].map((s) => `<option ${q.status === s ? "selected" : ""}>${s}</option>`).join("")}</select></label>
        <label class="row" style="flex-direction:row;align-items:center;gap:6px"><input type="checkbox" id="i-over" ${q.overdue === "1" ? "checked" : ""}> Overdue only</label>
        <label class="row" style="flex-direction:row;align-items:center;gap:6px"><input type="checkbox" id="i-mine" ${q.mine === "1" ? "checked" : ""}> Assigned to me</label></div>
      <div class="card" id="ilist"><div class="loading">Loading…</div></div>`);
    const upd = () => go("interventions", { status: document.getElementById("i-status").value, overdue: document.getElementById("i-over").checked ? 1 : "", mine: document.getElementById("i-mine").checked ? 1 : "" });
    ["i-status", "i-over", "i-mine"].forEach((id) => (document.getElementById(id).onchange = upd));
    const d = await api("/api/interventions?" + qs({ status: q.status, overdue: q.overdue, mine: q.mine }));
    const c = d.counts;
    document.getElementById("cnt").textContent = `${d.items.length} shown · ${c.Open || 0} open · ${c["In Progress"] || 0} in progress · ${c.Completed || 0} completed · ${c.overdue || 0} overdue`;
    renderInterventions(document.getElementById("ilist"), d.items, { title: "Actions in your scope", desc: "Overdue items are highlighted. Progress compares the score when the action was opened with the latest score." });
  }

  /* ------------------------------------------------------------------ segments */
  function ruleText(w, cfgF) {
    if (!w) return "";
    if (w.all) return w.all.length ? w.all.map((x) => ruleText(x, cfgF)).join(" and ") : "everyone else";
    if (w.any) return "(" + w.any.map((x) => ruleText(x, cfgF)).join(" or ") + ")";
    return `${(cfgF[w.feature] || {}).label || w.feature} ${w.op} ${w.value}`;
  }
  async function segmentsPage(q) {
    const main = shell(`<div class="page-head"><h1>Segments</h1><span class="sub">Support groups for targeted action. Rules are checked in order; each student lands in the first group that fits.</span></div>
      ${filterBar(q, { segment: false, search: false })}<div id="segs" class="grid g-3"><div class="loading">Loading…</div></div>`);
    bindFilters("segments", q);
    const [d, c] = await Promise.all([api("/api/segments?" + qs(filterQuery(q))), api("/api/config")]);
    document.getElementById("segs").innerHTML = d.segments.map((s) => `<div class="card seg-card">
      <div class="card-head"><h3>${esc(s.label)}</h3><span class="right size">${s.count}</span></div>
      <div class="rule">Rule: ${esc(ruleText(s.rule, c.active.features))}</div>
      <div class="seg-stats"><div><div class="l">Avg score</div><div class="v">${fmt(s.avg_score)}</div></div>
        <div><div class="l">Academic</div><div class="v">${fmt(s.pillars.academic)}</div></div><div><div class="l">Readiness</div><div class="v">${fmt(s.pillars.placement)}</div></div></div>
      ${s.common_reasons.length ? `<div class="hint">Most common reasons: ${s.common_reasons.map(([r, n]) => `${esc(r)} (${n})`).join(", ")}</div>` : ""}
      <p class="play"><b>Playbook.</b> ${esc(s.playbook)}</p><div class="owner">Owner: ${esc(s.owner)}</div>
      <div style="margin-top:10px"><a class="btn" href="#/students?${qs({ ...filterQuery(q), period: undefined, segment: s.id })}">View ${s.count} students</a></div></div>`).join("");
  }

  /* ------------------------------------------------------------------ uploads (admin) */
  async function uploadsPage() {
    const main = shell(`<div class="page-head"><h1>Data uploads</h1><span class="sub">Upload a CSV or Excel export. Files are checked first; nothing changes until you import.</span></div>
      <div class="grid g-2"><div class="card"><form class="form" id="upf">
        <div class="grid2"><label class="f">Data category<select id="up-cat"></select></label>
          <label class="f">Reporting period<select id="up-per">${S.me.periods.map((p) => `<option value="${p.id}" ${p.id === S.me.current_period ? "selected" : ""}>${esc(p.label)}</option>`).join("")}</select></label></div>
        <div id="up-help" class="hint"></div>
        <label class="f">File (.csv or .xlsx, up to 6 MB)<input type="file" id="up-file" accept=".csv,.xlsx" required></label>
        <div class="row"><button class="btn primary" type="submit">Check file</button><span class="err" id="up-err"></span></div></form></div>
        <div class="card" id="up-sum"><p class="muted">The validation summary appears here.</p></div></div>
      <h2 class="section-title">Upload history</h2><div class="table-wrap"><table id="up-hist"></table></div>`);
    const [tpl, hist] = await Promise.all([api("/api/templates"), api("/api/uploads")]);
    const cat = document.getElementById("up-cat");
    cat.innerHTML = tpl.map((t) => `<option value="${t.category}">${esc(t.label)}</option>`).join("");
    const help = () => {
      const t = tpl.find((x) => x.category === cat.value);
      document.getElementById("up-help").innerHTML = `${esc(t.description)} Key: ${esc(t.key.join(" + "))}. Columns: ${t.fields.map((f) => `<code>${esc(f.name)}</code>${f.required ? "*" : ""}`).join(", ")}.
        <button class="link-btn" type="button" id="tpl">Download template</button>`;
      document.getElementById("tpl").onclick = async () => {
        const r = await api(`/api/templates/${t.category}.csv`, { raw: true });
        const a = document.createElement("a"); a.href = URL.createObjectURL(await r.blob()); a.download = `${t.category}_template.csv`; a.click();
      };
    };
    cat.onchange = help; help();
    document.getElementById("upf").onsubmit = async (e) => {
      e.preventDefault();
      const file = document.getElementById("up-file").files[0];
      document.getElementById("up-err").textContent = "";
      if (!file) return;
      try {
        const s = await api("/api/uploads?" + qs({ category: cat.value, period: document.getElementById("up-per").value, filename: file.name }),
          { method: "POST", body: await file.arrayBuffer(), headers: { "Content-Type": "application/octet-stream" } });
        showSummary(s);
      } catch (x) { document.getElementById("up-err").textContent = x.message; }
    };
    document.getElementById("up-hist").innerHTML = `<thead><tr><th>When</th><th>Category</th><th>File</th><th>Period</th><th>By</th><th>Status</th><th class="num">Accepted</th><th class="num">Rejected</th><th>Applied</th></tr></thead><tbody>
      ${hist.map((u) => `<tr><td>${esc(dt(u.uploaded_at))}</td><td>${esc(u.label)}</td><td><button class="link-btn" data-id="${u.id}" type="button">${esc(u.filename)}</button></td><td>${esc(u.reporting_period)}</td>
        <td>${esc(u.uploaded_by)}</td><td><span class="pill ${u.status === "committed" ? "good" : u.status === "rejected" ? "bad" : ""}">${esc(u.status)}</span></td>
        <td class="num">${u.accepted ?? "–"}</td><td class="num">${u.rejected ?? "–"}</td>
        <td class="hint">${u.applied ? `${u.applied.new} new, ${u.applied.changed} changed, ${u.applied.unchanged} unchanged` : ""}</td></tr>`).join("")}</tbody>`;
    document.querySelectorAll("#up-hist button[data-id]").forEach((b) => (b.onclick = async () => showSummary(await api(`/api/uploads/${b.dataset.id}`))));
  }
  function showSummary(s) {
    const el = document.getElementById("up-sum");
    const miss = Object.entries(s.missing_values || {});
    el.innerHTML = `<div class="card-head"><h2>${esc(s.filename)}</h2><span class="right pill ${s.status === "committed" ? "good" : s.status === "rejected" ? "bad" : "warn"}">${esc(s.status)}</span>
        <span class="desc">${esc(s.label)} · ${esc(s.reporting_period)} · checked ${esc(dt(s.uploaded_at))} by ${esc(s.uploaded_by)}</span></div>
      ${s.file_errors.map((e) => `<p class="err">${esc(e)}</p>`).join("")}
      ${s.warnings.map((w) => `<p class="pill warn" style="white-space:normal">${esc(w)}</p>`).join("")}
      <div class="sumgrid"><div><div class="l">Rows</div><div class="v">${s.total_rows}</div></div><div><div class="l">Accepted</div><div class="v ok-text">${s.accepted}</div></div>
        <div><div class="l">Rejected</div><div class="v ${s.rejected ? "overdue" : ""}">${s.rejected}</div></div><div><div class="l">Duplicates</div><div class="v">${s.duplicates}</div></div>
        <div><div class="l">New</div><div class="v">${s.new}</div></div><div><div class="l">Changed</div><div class="v">${s.changed}</div></div><div><div class="l">Unchanged</div><div class="v">${s.unchanged}</div></div></div>
      ${s.unmatched_ids.length ? `<p><b>Unmatched student IDs (${s.unmatched_ids.length}):</b> ${s.unmatched_ids.slice(0, 20).map(esc).join(", ")}</p>` : ""}
      ${miss.length ? `<p><b>Blank optional values:</b> ${miss.map(([k, v]) => `${esc(k)} (${v})`).join(", ")}</p>` : ""}
      ${s.errors.length ? `<details class="box" open><summary>Rows needing attention (${s.errors.length})</summary><div class="table-wrap" style="max-height:260px;overflow:auto;margin-top:8px"><table>
        <thead><tr><th class="num">Row</th><th>Student</th><th>Result</th><th>Problem</th></tr></thead><tbody>${s.errors.map((e) => `<tr><td class="num">${e.row}</td><td>${esc(e.student_id || "–")}</td><td>${esc(e.status)}</td><td>${e.errors.map(esc).join("; ")}</td></tr>`).join("")}</tbody></table></div></details>` : ""}
      ${s.status === "validated" ? `<div class="row" style="margin-top:12px"><button class="btn primary" id="commit" type="button">Import ${s.accepted} rows</button>
        <button class="btn" id="discard" type="button">Discard</button><span class="hint">Rejected rows are skipped. Scores recalculate automatically.</span></div>` : ""}
      ${s.status === "committed" && s.applied ? `<p class="ok-text">Imported ${esc(dt(s.committed_at))}: ${s.applied.new} new, ${s.applied.changed} changed, ${s.applied.unchanged} unchanged.</p>` : ""}`;
    const c = document.getElementById("commit");
    if (c) c.onclick = async () => {
      c.disabled = true; c.textContent = "Importing…";
      try { const r = await api(`/api/uploads/${s.id}/commit`, { method: "POST" }); toast(`Imported. ${r.recalculated ? "Scores recalculated." : "Recalculation pending."}`); S.me = await api("/api/me"); uploadsPage().then(() => showSummary(r)); }
      catch (x) { c.disabled = false; c.textContent = "Import"; toast(x.message); }
    };
    const x = document.getElementById("discard");
    if (x) x.onclick = async () => { await api(`/api/uploads/${s.id}/discard`, { method: "POST" }); toast("Upload discarded"); uploadsPage(); };
  }

  /* ------------------------------------------------------------------ scoring rules */
  async function scoringPage() {
    const main = shell('<div class="loading">Loading…</div>');
    const c = await api("/api/config");
    const a = c.active, v = c.validation;
    const isAdmin = S.me.permissions.edit_config;
    const ruleRows = (kind) => a.risk[kind].rules.map((r) => `<tr><td class="rule-id">${esc(r.id)}</td><td>${esc(r.why)}</td><td>${esc((a.features[r.feature] || {}).label || r.feature)} ${esc(r.op)} ${esc(Array.isArray(r.value) ? r.value.join("–") : String(r.value))}</td><td class="num">+${r.points}</td><td>${esc((a.actions[r.action] || {}).title || "–")}</td></tr>`).join("");
    const vr = (obj) => Object.entries(obj).map(([k, x]) => `<tr><td>${esc(k)}</td><td class="num">${x.students}</td><td class="num">${Math.round(x.poor_academic_rate * 100)}%</td><td class="num">${Math.round(x.not_placed_rate * 100)}%</td></tr>`).join("");
    main.innerHTML = `<div class="page-head"><h1>Scoring rules</h1><span class="sub">Version ${esc(a.version)} · ${esc(a.description || "")} · last scored ${esc(dt(c.last_run.computed_at))} (${esc(c.last_run.reason || "")})</span></div>
      <div class="stack">
      <div class="grid g-2">
        <div class="card"><div class="card-head"><h2>Success Score indicators and weights</h2><span class="desc">Indicator score = clip((value − worst) / (best − worst)) × 100. Weights rescale over indicators with data. Coverage below ${Math.round(a.coverage.provisional_below * 100)}% marks a score provisional; below ${Math.round(a.coverage.insufficient_below * 100)}% it is withheld.</span></div>
          <div class="table-wrap"><table><thead><tr><th>Pillar</th><th>Indicator</th><th class="num">0 at</th><th class="num">100 at</th><th class="num">Overall weight</th></tr></thead><tbody>
          ${a.indicators.map((i, n) => `<tr><td>${n === 0 || a.indicators[n - 1].pillar !== i.pillar ? `<b>${esc(a.pillars[i.pillar].label)}</b> ${Math.round(a.pillars[i.pillar].weight * 100)}%` : ""}</td><td>${esc((a.features[i.id] || {}).label || i.id)}${i.applies ? ' <span class="pill">placement years</span>' : ""}</td><td class="num">${i.worst}</td><td class="num">${i.best}</td><td class="num">${(a.pillars[i.pillar].weight * i.weight * 100).toFixed(1)}%</td></tr>`).join("")}</tbody></table></div>
          <p class="hint">Bands: ${a.bands.map((b) => `${esc(b.label)} ≥ ${b.min}`).join(" · ")}</p></div>
        <div class="card"><div class="card-head"><h2>Checked against real outcomes</h2><span class="desc">${v ? esc(v.batch) + ` (${v.students} students).` : "Run python -m ssp.validate to produce this report."}</span></div>
          ${v ? `<div class="sumgrid"><div><div class="l">Score AUC, poor academic outcome</div><div class="v">${v.score_auc.poor_academic}</div></div><div><div class="l">Score AUC, not placed</div><div class="v">${v.score_auc.not_placed}</div></div>
            <div><div class="l">Academic rules AUC</div><div class="v">${v.risk_points_auc.academic}</div></div><div><div class="l">Placement rules AUC</div><div class="v">${v.risk_points_auc.placement}</div></div></div>
          <div class="table-wrap" style="margin-top:10px"><table><thead><tr><th>Academic risk level</th><th class="num">Students</th><th class="num">Poor academic outcome</th><th class="num">Not placed</th></tr></thead><tbody>${vr(v.by_academic_level)}</tbody></table></div>
          <div class="table-wrap" style="margin-top:10px"><table><thead><tr><th>Placement risk level</th><th class="num">Students</th><th class="num">Poor academic outcome</th><th class="num">Not placed</th></tr></thead><tbody>${vr(v.by_placement_level)}</tbody></table></div>
          <div class="table-wrap" style="margin-top:10px"><table><thead><tr><th>Score band</th><th class="num">Students</th><th class="num">Poor academic outcome</th><th class="num">Not placed</th></tr></thead><tbody>${vr(v.by_band)}</tbody></table></div>` : ""}</div>
      </div>
      <div class="card"><div class="card-head"><h2>Risk rules</h2><span class="desc">Points add up per student. Levels: ${a.risk.levels.map((l) => `${esc(l.name)} ≥ ${l.min_points}`).join(" · ")}. If required evidence is missing the level is "Insufficient data", unless the available evidence already reaches High.</span></div>
        <h3 style="font-size:13px">Academic (required: ${esc(a.risk.academic.required_all.map((x) => a.features[x].label).join(", "))})</h3>
        <div class="table-wrap"><table><thead><tr><th>Rule</th><th>Meaning</th><th>Condition</th><th class="num">Points</th><th>Suggested action</th></tr></thead><tbody>${ruleRows("academic")}</tbody></table></div>
        <h3 style="font-size:13px;margin-top:12px">Placement (required: ${esc(a.risk.placement.required_any.map((x) => a.features[x].label).join(" or "))})</h3>
        <div class="table-wrap"><table><thead><tr><th>Rule</th><th>Meaning</th><th>Condition</th><th class="num">Points</th><th>Suggested action</th></tr></thead><tbody>${ruleRows("placement")}</tbody></table></div></div>
      <div class="card"><div class="card-head"><h2>Versions</h2></div><div class="table-wrap"><table><thead><tr><th>Version</th><th>Created</th><th>By</th><th>Note</th></tr></thead><tbody>
        ${c.versions.map((x) => `<tr><td>${esc(x.version)}${x.version === a.version ? ' <span class="pill good">active</span>' : ""}</td><td>${esc(dt(x.created_at))}</td><td>${esc(x.created_by)}</td><td>${esc(x.note || "")}</td></tr>`).join("")}</tbody></table></div></div>
      ${isAdmin ? `<div class="card"><div class="card-head"><h2>Change rules</h2><span class="desc">Edit the JSON, give it a new version number and activate. The rules are validated first; every student is re-scored and the change is audited. Older versions stay available for reproducing past scores.</span></div>
        <form class="form" id="cfgf"><textarea id="cfg-json" rows="14" spellcheck="false" style="font-family:ui-monospace,monospace;font-size:12px">${esc(JSON.stringify(a, null, 2))}</textarea>
        <label class="f">Reason for the change<input id="cfg-note" required placeholder="e.g. Raise attendance threshold after academic council review"></label>
        <div class="row"><button class="btn primary" type="submit">Validate and activate</button><button class="btn" type="button" id="recalc">Recalculate now</button><span class="err" id="cfg-err"></span></div></form></div>` : ""}
      </div>`;
    if (isAdmin) {
      document.getElementById("cfgf").onsubmit = async (e) => {
        e.preventDefault();
        let parsed;
        try { parsed = JSON.parse(document.getElementById("cfg-json").value); } catch (x) { document.getElementById("cfg-err").textContent = "Not valid JSON: " + x.message; return; }
        try { const r = await api("/api/config", { method: "POST", json: { config: parsed, note: document.getElementById("cfg-note").value } }); S.me = await api("/api/me"); toast(`Rules ${r.version} active; ${Object.values(r.run.students).reduce((a2, b) => a2 + b, 0)} scores recalculated`); scoringPage(); }
        catch (x) { document.getElementById("cfg-err").textContent = x.message; }
      };
      document.getElementById("recalc").onclick = async () => { const r = await api("/api/recalculate", { method: "POST", json: { reason: "manual recalculation" } }); S.me = await api("/api/me"); toast("Recalculated " + JSON.stringify(r.students)); scoringPage(); };
    }
  }

  /* ------------------------------------------------------------------ audit & users */
  async function auditPage(q) {
    const main = shell(`<div class="page-head"><h1>Audit log</h1><span class="sub">Uploads, scoring changes, interventions, sign-ins, user changes and profile views.</span></div>
      <div class="filters" style="padding:0 0 14px;max-width:none"><label>Action<select id="a-act"><option value="">All</option>${["upload", "scoring", "intervention", "auth", "user", "student", "summary"].map((x) => `<option ${q.action === x ? "selected" : ""}>${x}</option>`).join("")}</select></label></div>
      <div class="table-wrap"><table id="aud"><tbody><tr><td class="loading">Loading…</td></tr></tbody></table></div>`);
    document.getElementById("a-act").onchange = (e) => go("audit", { action: e.target.value });
    const rows = await api("/api/audit?" + qs({ action: q.action }));
    document.getElementById("aud").innerHTML = `<thead><tr><th>When</th><th>User</th><th>Action</th><th>Item</th><th>Details</th></tr></thead><tbody>
      ${rows.map((r) => `<tr><td style="white-space:nowrap">${esc(dt(r.ts))}</td><td>${esc(r.username)} <span class="hint">${esc(r.role)}</span></td><td><code>${esc(r.action)}</code></td>
        <td>${esc(r.entity)} ${esc(r.entity_id)}</td><td class="hint" style="max-width:420px">${esc(JSON.stringify(r.details))}</td></tr>`).join("") || '<tr><td colspan="5" class="empty">Nothing logged.</td></tr>'}</tbody>`;
  }
  async function usersPage() {
    const main = shell(`<div class="page-head"><h1>Users</h1><span class="sub">${Auth.mode === "cognito" ? "Accounts live in Amazon Cognito. New users get a temporary password by email unless you set one." : "Local accounts (development mode)."}</span></div>
      <div class="grid g-2"><div class="card"><form class="form" id="uf"><h2>Add a user</h2>
        <div class="grid2"><label class="f">Username<input id="u-name" required pattern="[a-z0-9._-]{3,40}"></label><label class="f">Full name<input id="u-full" required></label>
          <label class="f">Role<select id="u-role"><option value="mentor">Faculty / Mentor</option><option value="placement">Placement Officer</option><option value="hod">Head of Department</option><option value="admin">Administrator</option><option value="student">Student</option></select></label>
          <label class="f">Department (HOD)<input id="u-dept" placeholder="CSE"></label><label class="f">Roll number (student)<input id="u-sid"></label>
          <label class="f">Email<input id="u-email" type="email"></label><label class="f">Password ${Auth.mode === "cognito" ? "(optional)" : ""}<input id="u-pw" type="password" autocomplete="new-password"></label></div>
        <div class="row"><button class="btn primary" type="submit">Create user</button><span class="err" id="u-err"></span></div></form></div>
        <div class="card"><div class="table-wrap" style="max-height:520px;overflow:auto"><table id="ut"><tbody><tr><td class="loading">Loading…</td></tr></tbody></table></div></div></div>`);
    const users = await api("/api/users");
    document.getElementById("ut").innerHTML = `<thead><tr><th>User</th><th>Role</th><th>Scope</th><th></th></tr></thead><tbody>${users.map((u) => `<tr><td><b>${esc(u.name)}</b><div class="hint">${esc(u.username)}</div></td><td>${esc(u.role)}</td><td>${esc(u.dept || u.student_id || "")}</td>
      <td>${u.username === S.me.user.username ? "" : `<button class="btn small ${u.active ? "danger" : ""}" data-u="${esc(u.username)}" data-a="${u.active ? "disable" : "enable"}" type="button">${u.active ? "Disable" : "Enable"}</button>`}</td></tr>`).join("")}</tbody>`;
    document.querySelectorAll("#ut button[data-u]").forEach((b) => (b.onclick = async () => { await api(`/api/users/${b.dataset.u}/${b.dataset.a}`, { method: "POST" }); toast(`User ${b.dataset.a}d`); usersPage(); }));
    document.getElementById("uf").onsubmit = async (e) => {
      e.preventDefault();
      const g = (id) => document.getElementById(id).value.trim();
      try { await api("/api/users", { method: "POST", json: { username: g("u-name"), name: g("u-full"), role: g("u-role"), dept: g("u-dept").toUpperCase(), student_id: g("u-sid").toUpperCase(), email: g("u-email"), password: g("u-pw") } }); toast("User created"); usersPage(); }
      catch (x) { document.getElementById("u-err").textContent = x.message; }
    };
  }

  /* ------------------------------------------------------------------ router */
  async function route() {
    if (!S.me) return;
    const { parts, q } = hashParts();
    const page = parts[0] || (S.me.user.role === "student" ? "me" : "dashboard");
    try {
      if (S.me.user.role === "student" && page !== "me" && !(page === "student" && parts[1] === S.me.own_student_id)) return go("me");
      switch (page) {
        case "dashboard": return await dashboard(q);
        case "students": return await students(q);
        case "student": return await profile(parts[1]);
        case "me": return await profile(S.me.own_student_id);
        case "interventions": return await interventionsPage(q);
        case "segments": return await segmentsPage(q);
        case "uploads": return await uploadsPage();
        case "scoring": return await scoringPage();
        case "audit": return await auditPage(q);
        case "users": return await usersPage();
        default: shell('<div class="card empty">Page not found.</div>');
      }
    } catch (e) {
      if (e.message !== "signed out") shell(`<div class="card empty" role="alert">${esc(e.message)}</div>`);
    } finally {
      const m = document.getElementById("main");
      if (m && route.focus) m.focus({ preventScroll: true });
      route.focus = true;
    }
  }
  window.addEventListener("hashchange", () => { window.scrollTo(0, 0); route(); });

  async function boot() {
    try { await Auth.init(); } catch (e) { return renderLogin(e.message); }
    if (!Auth.signedIn()) return renderLogin();
    app.innerHTML = '<div class="loading">Loading…</div>';
    try { S.me = await api("/api/me"); } catch (e) { return renderLogin(e.message === "signed out" ? "" : e.message); }
    S.period = S.me.current_period;
    route();
  }
  boot();
})();
