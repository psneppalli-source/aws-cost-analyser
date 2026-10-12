/* Smart Campus Analytics: dashboard application. Data comes from data.js (window.SSP_DATA). */
(function () {
  const D = window.SSP_DATA;
  const C = window.Charts;
  const { esc } = C;
  const $ = (s) => document.querySelector(s);

  const BAND_COLOR = { "Critical": "var(--critical)", "Needs attention": "var(--serious)", "On track": "var(--neutral-band)", "Thriving": "var(--good)" };
  const BANDS = ["Critical", "Needs attention", "On track", "Thriving"];
  const TIERS = [
    { key: "High", label: "High", color: "var(--critical)", labelInk: "#ffffff" },
    { key: "Medium", label: "Medium", color: "var(--warning)", labelInk: "#0b0b0b" },
    { key: "Low", label: "Low", color: "var(--good)", labelInk: "#0b0b0b" },
  ];
  const TIER_COLOR = { High: "var(--critical)", Medium: "var(--warning)", Low: "var(--good)" };
  const PILLARS = D.score.pillars;
  const SEG = Object.fromEntries(D.segments.map((s) => [s.key, s]));
  const LABEL = D.feature_labels;
  const DEPTS = [...new Set(D.students.map((s) => s.dept))].sort();
  const MONTHS = ["Jul", "Aug", "Sep"];
  const byId = Object.fromEntries(D.students.map((s) => [s.id, s]));

  const state = { view: "overview", sort: { k: "acad_risk", dir: -1 }, page: 0, riskKind: "acad", scoreRange: null };
  const PAGE = 25;

  /* ---------------- Theme ---------------- */
  function resolvedTheme() {
    const t = document.documentElement.dataset.theme;
    if (t) return t;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function applyTheme(t) {
    if (t) document.documentElement.dataset.theme = t;
    document.documentElement.dataset.themeResolved = resolvedTheme();
    try { if (t) localStorage.setItem("ssp-theme", t); } catch (e) { /* storage unavailable */ }
  }
  try { const saved = localStorage.getItem("ssp-theme"); if (saved) document.documentElement.dataset.theme = saved; } catch (e) { /* ignore */ }
  applyTheme();
  $("#themeBtn").addEventListener("click", () => { applyTheme(resolvedTheme() === "dark" ? "light" : "dark"); renderAll(); });
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { applyTheme(); renderAll(); });

  /* ---------------- Filters ---------------- */
  DEPTS.forEach((d) => $("#fDept").insertAdjacentHTML("beforeend", `<option value="${d}">${d}</option>`));
  D.segments.forEach((s) => $("#fSeg").insertAdjacentHTML("beforeend", `<option value="${s.key}">${esc(s.label)}</option>`));

  function filters() {
    return { dept: $("#fDept").value, year: $("#fYear").value, seg: $("#fSeg").value, risk: $("#fRisk").value, q: $("#fSearch").value.trim().toLowerCase() };
  }
  function matchRisk(s, r) {
    switch (r) {
      case "acadHigh": return s.acad_tier === "High";
      case "placeHigh": return s.place_tier === "High";
      case "anyHigh": return s.acad_tier === "High" || s.place_tier === "High";
      case "attendance": return s.flags.includes("Attendance < 75%");
      case "lms": return s.flags.includes("LMS drop-off");
      case "wellbeing": return s.flags.includes("Wellbeing concern");
      default: return true;
    }
  }
  function filtered() {
    const f = filters();
    return D.students.filter((s) =>
      (!f.dept || s.dept === f.dept) &&
      (!f.year || String(s.year) === f.year) &&
      (!f.seg || s.segment === f.seg) &&
      matchRisk(s, f.risk) &&
      (!state.scoreRange || (s.score >= state.scoreRange[0] && s.score < state.scoreRange[1])) &&
      (!f.q || s.name.toLowerCase().includes(f.q) || s.id.toLowerCase().includes(f.q)));
  }
  ["#fDept", "#fYear", "#fSeg", "#fRisk"].forEach((id) => $(id).addEventListener("change", () => { state.page = 0; renderAll(); }));
  $("#fSearch").addEventListener("input", () => { state.page = 0; renderAll(); });
  $("#fReset").addEventListener("click", () => {
    ["#fDept", "#fYear", "#fSeg", "#fRisk", "#fSearch"].forEach((id) => ($(id).value = ""));
    state.scoreRange = null; state.page = 0; renderAll();
  });
  function setFilter(patch) {
    if ("risk" in patch) $("#fRisk").value = patch.risk;
    if ("seg" in patch) $("#fSeg").value = patch.seg;
    if ("dept" in patch) $("#fDept").value = patch.dept;
    if ("scoreRange" in patch) state.scoreRange = patch.scoreRange;
    state.page = 0;
    show("students");
  }

  /* ---------------- Tabs ---------------- */
  function show(view) {
    state.view = view;
    document.querySelectorAll(".tab").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.view === view)));
    document.querySelectorAll(".view").forEach((v) => (v.hidden = v.id !== "view-" + view));
    $("#filters").style.display = view === "method" ? "none" : "";
    renderAll();
    if (location.hash !== "#" + view && !location.hash.startsWith("#student=")) history.replaceState(null, "", "#" + view);
  }
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => show(t.dataset.view)));

  /* ---------------- Helpers ---------------- */
  const mean = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : NaN);
  const pct = (n, d) => (d ? Math.round((100 * n) / d) : 0);
  const fmt1 = (v) => (v == null || Number.isNaN(v) ? "–" : (+v).toFixed(1));
  function tierBadge(tier, p) {
    if (!tier) return `<span class="badge na">n/a</span>`;
    const pp = p == null ? "" : ` <span class="muted">${probFmt(p)}</span>`;
    return `<span class="badge ${tier.toLowerCase()}"><span class="dot"></span>${tier}${pp}</span>`;
  }
  // Avoid implying certainty: clamp displayed probabilities to 1-99%.
  const probFmt = (p) => (p >= 0.99 ? ">99%" : p <= 0.01 ? "<1%" : Math.round(p * 100) + "%");
  function riskBadge(label, tier, p) {
    return `<span class="badge ${tier.toLowerCase()}"><span class="dot"></span>${label}: ${tier} <span class="muted">${probFmt(p)}</span></span>`;
  }
  function bandBadge(band) {
    return `<span class="badge"><span class="dot" style="background:${C.esc(cssColor(BAND_COLOR[band]))}"></span>${band}</span>`;
  }
  function cssColor(v) {
    if (!v.startsWith("var(")) return v;
    return getComputedStyle(document.documentElement).getPropertyValue(v.slice(4, -1)).trim();
  }
  function topDriver(s) {
    const neg = s.score_drivers.filter((d) => d.v < 0);
    if (!neg.length) return "–";
    return LABEL[neg[0].col] || neg[0].col;
  }

  /* ================= OVERVIEW ================= */
  function renderKpis(list) {
    const n = list.length;
    const avg = mean(list.map((s) => s.score));
    const acadHigh = list.filter((s) => s.acad_tier === "High").length;
    const elig = list.filter((s) => s.place_tier);
    const placeHigh = elig.filter((s) => s.place_tier === "High").length;
    const att = list.filter((s) => s.flags.includes("Attendance < 75%")).length;
    const lms = list.filter((s) => s.flags.includes("LMS drop-off")).length;
    const wb = list.filter((s) => s.flags.includes("Wellbeing concern")).length;
    const tiles = [
      { cls: "hero", label: "Average Success Score", value: fmt1(avg), note: `${n} students in view`, meter: avg },
      { label: "High academic risk", value: acadHigh, note: `${pct(acadHigh, n)}% of students`, go: { risk: "acadHigh" } },
      { label: "High placement risk", value: placeHigh, note: `${pct(placeHigh, elig.length)}% of ${elig.length} 3rd/4th years`, go: { risk: "placeHigh" } },
      { label: "Attendance below 75%", value: att, note: "exam-eligibility risk", go: { risk: "attendance" } },
      { label: "LMS drop-off", value: lms, note: "activity down 40%+ in last 4 weeks", go: { risk: "lms" } },
      { label: "Wellbeing concerns", value: wb, note: "from mentor remarks", go: { risk: "wellbeing" } },
    ];
    $("#kpis").innerHTML = tiles.map((t, i) => `
      <div class="card kpi ${t.cls || ""} ${t.go ? "clickable" : ""}" data-i="${i}" ${t.go ? 'role="button" tabindex="0" title="Show these students"' : ""}>
        <div class="label">${esc(t.label)}</div>
        <div class="value">${t.value}</div>
        <div class="note">${esc(t.note)}</div>
        ${t.meter != null ? `<div class="meter"><span style="width:${Math.max(0, Math.min(100, t.meter))}%"></span></div>` : ""}
      </div>`).join("");
    $("#kpis").querySelectorAll(".clickable").forEach((elx) => {
      const go = tiles[+elx.dataset.i].go;
      elx.addEventListener("click", () => setFilter(go));
      elx.addEventListener("keydown", (e) => { if (e.key === "Enter") setFilter(go); });
    });
  }

  function renderInsights() {
    const kindLabel = { "risk": "Risk driver", "early-warning": "Early warning", "segment": "Segment", "department": "Department", "driver": "Placement lever", "wellbeing": "Wellbeing", "placement": "Placement" };
    $("#insights").innerHTML = D.insights.map((i) => `
      <div class="insight"><div class="k">${esc(kindLabel[i.kind] || i.kind)} · campus-wide</div>
      <h3>${esc(i.title)}</h3><p>${esc(i.detail)}</p></div>`).join("");
  }

  function renderHist(list) {
    const bins = [];
    for (let x = 0; x < 100; x += 5) {
      const inBin = list.filter((s) => s.score >= x && s.score < x + 5);
      const band = x >= 70 ? "Thriving" : x >= 55 ? "On track" : x >= 40 ? "Needs attention" : "Critical";
      bins.push({ label: String(x), v: inBin.length, color: BAND_COLOR[band], range: [x, x + 5],
        tip: C.rows(`Score ${x}–${x + 5}`, [["Students", inBin.length], ["Band", band]]) });
    }
    C.columns($("#chHist"), bins, { height: 220, xLabelEvery: 2, onClick: (d) => d.v && setFilter({ scoreRange: d.range }) });
    C.legend($("#lgHist"), BANDS.map((b) => ({ label: b + (b === "Critical" ? " < 40" : b === "Needs attention" ? " 40–55" : b === "On track" ? " 55–70" : " ≥ 70"), color: cssColor(BAND_COLOR[b]) })));
  }

  function renderDept(list) {
    const k = state.riskKind;
    const rows = DEPTS.map((d) => {
      const g = list.filter((s) => s.dept === d && (k === "acad" || s.place_tier));
      const values = {};
      TIERS.forEach((t) => (values[t.key] = g.filter((s) => s[k + "_tier"] === t.key).length));
      return { label: d, values };
    }).filter((r) => Object.values(r.values).some((v) => v > 0));
    if (!rows.length) { $("#chDept").innerHTML = `<div class="empty">No students match the filters.</div>`; return; }
    C.stacked($("#chDept"), rows, TIERS.map((t) => ({ ...t, color: cssColor(t.color) })), {
      labelW: 56,
      onClick: (row, tier) => { $("#fDept").value = row.label; setFilter({ risk: tier.key === "High" ? (k === "acad" ? "acadHigh" : "placeHigh") : "" }); },
    });
    C.legend($("#lgDept"), TIERS.map((t) => ({ label: `${t.label} ${k === "acad" ? "academic" : "placement"} risk`, color: cssColor(t.color) })));
  }
  document.querySelectorAll("#riskToggle button").forEach((b) => b.addEventListener("click", () => {
    state.riskKind = b.dataset.k;
    document.querySelectorAll("#riskToggle button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    renderDept(filtered());
  }));

  // Trend cohorts: the disengagement signal is a minority pattern, so averaging by
  // risk tier would hide it. Compare the flagged group against everyone else.
  const COHORTS = [
    { name: "Disengaging signal", color: "var(--s2)", test: (s) => s.raw.lms_login_trend < 0.6 || s.raw.attendance_trend <= -10 },
    { name: "Other high academic risk", color: "var(--s1)", test: (s) => s.acad_tier === "High" },
    { name: "All other students", color: "var(--s3)", test: () => true },
  ];
  function cohortSeries(list, getter, len) {
    const left = new Set(list);
    return COHORTS.map((c) => {
      const g = [...left].filter(c.test);
      g.forEach((s) => left.delete(s));
      const values = Array.from({ length: len }, (_, i) => {
        const v = g.map((s) => getter(s)[i]).filter((x) => x != null);
        return v.length ? +mean(v).toFixed(1) : null;
      });
      return { name: `${c.name} (${g.length})`, short: c.name.split(" ").slice(0, 2).join(" "), color: cssColor(c.color), values };
    }).filter((s) => s.values.some((v) => v != null));
  }

  function renderTrends(list) {
    const weeks = Array.from({ length: 12 }, (_, i) => "W" + (i + 1));
    const sLms = cohortSeries(list, (s) => s.raw.lms_weekly_logins, 12);
    C.lines($("#chLms"), sLms, weeks, { yMin: 0, yFmt: (v) => (+v).toFixed(v % 1 ? 1 : 0) });
    C.legend($("#lgLms"), sLms.map((s) => ({ label: s.name, color: s.color, line: true })));
    const sAtt = cohortSeries(list, (s) => s.raw.attendance_monthly, 3);
    C.lines($("#chAtt"), sAtt, MONTHS, { yMin: 50, yMax: 100, ticks: 5, ref: 75, refLabel: "75% exam-eligibility rule", yFmt: (v) => Math.round(v) + "%" });
    C.legend($("#lgAtt"), sAtt.map((s) => ({ label: s.name, color: s.color, line: true })));
  }

  function studentTip(s) {
    return C.rows(`${s.name} · ${s.id}`, [["Success Score", s.score], ["Academic pillar", fmt1(s.pillars.academic)], ["Readiness", fmt1(s.readiness)], ["Academic risk", s.acad_tier], ["Segment", SEG[s.segment].label]]);
  }

  function renderScatter(list) {
    const pts = list.map((s) => ({ x: s.pillars.academic, y: s.readiness, color: cssColor(TIER_COLOR[s.acad_tier]), tip: studentTip(s), id: s.id }));
    C.scatter($("#chScatter"), pts, { height: 330, xLabel: "Academic pillar (0–100)", yLabel: "Placement readiness (0–100)", quad: [65, 45], quadLabel: "Achiever, placement-unready", onClick: (p) => openStudent(p.id) });
    C.legend($("#lgScatter"), TIERS.map((t) => ({ label: `${t.label} academic risk`, color: cssColor(t.color) })));
  }

  function pillarMatrix(groups, list, keyFn) {
    return groups.map((g) => {
      const gs = list.filter((s) => keyFn(s) === g);
      return PILLARS.map((p) => {
        const v = gs.map((s) => s.pillars[p.key]).filter((x) => x != null);
        return v.length ? mean(v) : null;
      });
    });
  }

  function renderHeat(list) {
    const depts = DEPTS.filter((d) => list.some((s) => s.dept === d));
    if (!depts.length) { $("#chHeat").innerHTML = `<div class="empty">No students match the filters.</div>`; return; }
    C.heatmap($("#chHeat"), depts, PILLARS.map((p) => p.label), pillarMatrix(depts, list, (s) => s.dept), {
      labelW: 56, min: 20, max: 90,
      extra: (i) => [["Students", list.filter((s) => s.dept === depts[i]).length]],
    });
  }

  /* ================= STUDENTS ================= */
  function sortVal(s, k) {
    if (k === "segment") return SEG[s.segment].label;
    if (k === "place_risk") return s.place_risk == null ? -1 : s.place_risk;
    return s[k];
  }
  function renderTable(list) {
    const { k, dir } = state.sort;
    const rows = [...list].sort((a, b) => {
      const x = sortVal(a, k), y = sortVal(b, k);
      return (x < y ? -1 : x > y ? 1 : 0) * dir;
    });
    const pages = Math.max(1, Math.ceil(rows.length / PAGE));
    state.page = Math.min(state.page, pages - 1);
    const slice = rows.slice(state.page * PAGE, state.page * PAGE + PAGE);
    const tb = $("#stuTable tbody");
    tb.innerHTML = slice.length ? slice.map((s) => `
      <tr class="row-click" data-id="${s.id}" tabindex="0">
        <td><div style="font-weight:600">${esc(s.name)}</div><div class="muted" style="font-size:12px">${s.id}</div></td>
        <td>${s.dept}</td>
        <td class="num">${s.year}</td>
        <td><div class="score-cell"><b>${fmt1(s.score)}</b><div class="bar"><span style="width:${s.score}%;background:${cssColor(BAND_COLOR[s.band])}"></span></div></div><div class="muted" style="font-size:11.5px">${s.band}</div></td>
        <td>${tierBadge(s.acad_tier, s.acad_risk)}</td>
        <td>${tierBadge(s.place_tier, s.place_risk)}</td>
        <td style="font-size:12.5px">${esc(SEG[s.segment].label)}</td>
        <td style="font-size:12.5px" class="ink2">${esc(topDriver(s))}</td>
        <td>${s.flags.map((f) => `<span class="chip">${esc(f)}</span>`).join("")}</td>
      </tr>`).join("") : `<tr><td colspan="9" class="empty">No students match the filters.</td></tr>`;
    tb.querySelectorAll("tr[data-id]").forEach((tr) => {
      tr.addEventListener("click", () => openStudent(tr.dataset.id));
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter") openStudent(tr.dataset.id); });
    });
    document.querySelectorAll("#stuTable th.sortable").forEach((th) => {
      const on = th.dataset.k === k;
      th.innerHTML = th.innerHTML.replace(/ <span class="arrow">.*<\/span>$/, "") + (on ? ` <span class="arrow">${dir > 0 ? "▲" : "▼"}</span>` : "");
    });
    const hi = list.filter((s) => s.acad_tier === "High" || s.place_tier === "High").length;
    $("#stuSummary").textContent = `${list.length} students · ${hi} with a high-risk flag${state.scoreRange ? ` · score ${state.scoreRange[0]}–${state.scoreRange[1]}` : ""}`;
    $("#pager").innerHTML = `<span>Page ${state.page + 1} of ${pages}</span>
      <button type="button" id="pgPrev" ${state.page === 0 ? "disabled" : ""}>Previous</button>
      <button type="button" id="pgNext" ${state.page >= pages - 1 ? "disabled" : ""}>Next</button>`;
    $("#pgPrev").onclick = () => { state.page--; renderTable(filtered()); };
    $("#pgNext").onclick = () => { state.page++; renderTable(filtered()); };
  }
  document.querySelectorAll("#stuTable th.sortable").forEach((th) => th.addEventListener("click", () => {
    const k = th.dataset.k;
    state.sort = { k, dir: state.sort.k === k ? -state.sort.dir : (["name", "dept", "segment"].includes(k) ? 1 : -1) };
    renderTable(filtered());
  }));

  $("#exportBtn").addEventListener("click", () => {
    const cols = ["roll_no", "name", "dept", "year", "success_score", "band", "academic_risk_tier", "academic_risk_prob", "placement_risk_tier", "placement_risk_prob", "segment", "flags", "priority_action", "action_owner"];
    const q = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const lines = [cols.join(",")].concat(filtered().sort((a, b) => b.acad_risk - a.acad_risk).map((s) => [
      s.id, s.name, s.dept, s.year, s.score, s.band, s.acad_tier, s.acad_risk, s.place_tier || "", s.place_risk ?? "",
      SEG[s.segment].label, s.flags.join("; "), s.actions[0]?.action, s.actions[0]?.owner].map(q).join(",")));
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "intervention_list.csv";
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  });

  /* ================= SEGMENTS ================= */
  function renderSegments(list) {
    $("#segCards").innerHTML = D.segments.map((sg) => {
      const g = list.filter((s) => s.segment === sg.key);
      const r = g.map((s) => s.readiness).filter((x) => x != null);
      return `<div class="card seg-card">
        <div class="card-head"><h3>${esc(sg.label)}</h3><span class="right size">${g.length}</span></div>
        <div class="rule">${esc(sg.rule)}</div>
        <div class="seg-stats">
          <div><div class="l">Avg score</div><div class="v">${fmt1(mean(g.map((s) => s.score)))}</div></div>
          <div><div class="l">Avg CGPA</div><div class="v">${g.length ? mean(g.map((s) => s.raw.cgpa)).toFixed(2) : "–"}</div></div>
          <div><div class="l">Readiness</div><div class="v">${fmt1(mean(r))}</div></div>
        </div>
        <div class="play"><b>Playbook.</b> ${esc(sg.playbook)}</div>
        <div class="owner" style="margin-top:6px">Owner: ${esc(sg.owner)}</div>
        <div style="margin-top:10px"><button class="btn" type="button" data-seg="${sg.key}" ${g.length ? "" : "disabled"}>View ${g.length} students →</button></div>
      </div>`;
    }).join("");
    $("#segCards").querySelectorAll("button[data-seg]").forEach((b) => b.addEventListener("click", () => setFilter({ seg: b.dataset.seg })));
    const keys = D.segments.map((s) => s.key).filter((k) => list.some((s) => s.segment === k));
    if (!keys.length) { $("#chSegHeat").innerHTML = `<div class="empty">No students match the filters.</div>`; return; }
    C.heatmap($("#chSegHeat"), keys.map((k) => SEG[k].label), PILLARS.map((p) => p.label), pillarMatrix(keys, list, (s) => s.segment), {
      labelW: Math.min(250, ($("#chSegHeat").clientWidth || 600) * 0.36), min: 20, max: 90,
      extra: (i) => [["Students", list.filter((s) => s.segment === keys[i]).length]],
    });
  }

  /* ================= METHOD ================= */
  function table(elx, head, body) {
    elx.innerHTML = `<thead><tr>${head.map((h) => `<th class="${h.num ? "num" : ""}">${esc(h.t)}</th>`).join("")}</tr></thead>
      <tbody>${body.map((r) => `<tr>${r.map((c, i) => `<td class="${head[i].num ? "num" : ""}">${c}</td>`).join("")}</tr>`).join("")}</tbody>`;
  }
  function renderMethod() {
    const I = D.integration;
    $("#lineageDesc").textContent = `${I.raw_rows_total.toLocaleString()} raw rows from 8 tables reconciled into ${I.students} student records (avg ${I.avg_sources_linked} sources linked per student).`;
    table($("#lineageTable"), [{ t: "Source" }, { t: "Join key" }, { t: "Rows", num: true }, { t: "Students matched", num: true }],
      Object.entries(I.lineage).map(([k, v]) => [esc(k), `<code>${esc(v.key)}</code>`, v.rows.toLocaleString(), v.students]));
    table($("#dqTable"), [{ t: "Source" }, { t: "Issue" }, { t: "Rows", num: true }, { t: "Fix" }],
      I.quality_log.map((q) => [esc(q.source), esc(q.issue), q.rows.toLocaleString(), esc(q.action)]));
    const ind = D.score.indicators;
    table($("#weightsTable"), [{ t: "Pillar" }, { t: "Indicator" }, { t: "0 at" , num: true }, { t: "100 at", num: true }, { t: "Weight", num: true }],
      ind.map((i, idx) => [
        idx === 0 || ind[idx - 1].pillar !== i.pillar ? `<b>${esc(i.pillar_label)}</b> <span class="muted">${Math.round(D.score.pillars.find((p) => p.key === i.pillar).weight * 100)}%</span>` : "",
        esc(i.label), i.worst, i.best, (i.weight_overall * 100).toFixed(1) + "%"]));

    const V = D.validation;
    $("#valDesc").textContent = `Last year's batch (${V.historical_students} students): the score computed at the start of final year vs what actually happened. AUC ${V.score_auc_academic} for poor academic outcome, ${V.score_auc_placement} for not being placed.`;
    C.columns($("#chVal"), V.by_band.map((b) => ({ label: b.band, v: Math.round(b.poor_academic_rate * 100), color: cssColor(BAND_COLOR[b.band]),
      tip: C.rows(b.band, [["Students", b.students], ["Poor academic outcome", Math.round(b.poor_academic_rate * 100) + "%"]]) })), { height: 190, yMax: 100, yFmt: (v) => v + "%", valueLabels: true, barMax: 48 });
    $("#lgVal").innerHTML = `<span>Share with poor academic outcome at graduation, by Success Score band</span>`;
    C.columns($("#chVal2"), V.by_band.map((b) => ({ label: b.band, v: Math.round(b.placed_rate * 100), color: cssColor(BAND_COLOR[b.band]),
      tip: C.rows(b.band, [["Students", b.students], ["Placed within 6 months", Math.round(b.placed_rate * 100) + "%"]]) })), { height: 190, yMax: 100, yFmt: (v) => v + "%", valueLabels: true, barMax: 48 });
    $("#lgVal2").innerHTML = `<span>Share placed within 6 months, by Success Score band</span>`;

    $("#modelCards").innerHTML = ["academic", "placement"].map((k) => {
      const m = D.models[k];
      return `<div class="card"><div class="card-head"><h2>${k === "academic" ? "Academic" : "Placement"} risk model</h2>
        <span class="desc">Logistic regression trained on ${m.train_size} students from last year's batch, tested on ${m.test_size} held out. Target: ${esc(m.target)}.</span></div>
        <div class="grid g-kpi" style="grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:12px">
          <div class="kpi"><div class="label">AUC (holdout)</div><div class="value" style="font-size:22px">${m.auc_test}</div></div>
          <div class="kpi"><div class="label">Recall</div><div class="value" style="font-size:22px">${Math.round(m.recall_at_medium * 100)}%</div></div>
          <div class="kpi"><div class="label">Precision</div><div class="value" style="font-size:22px">${Math.round(m.precision_at_medium * 100)}%</div></div>
          <div class="kpi"><div class="label">Base rate</div><div class="value" style="font-size:22px">${Math.round(m.base_rate * 100)}%</div></div>
        </div>
        <p class="muted" style="font-size:12px;margin:0 0 8px">Recall/precision at the Medium threshold (${Math.round(m.thresholds.medium * 100)}%). High ≥ ${Math.round(m.thresholds.high * 100)}%. Bars: effect of +1 standard deviation on the log-odds of risk (red raises risk, blue lowers it).</p>
        <div class="chart" id="imp-${k}"></div>
        ${m.dropped_features.length ? `<p class="muted" style="font-size:12px">Dropped for contradicting domain direction (collinearity): ${esc(m.dropped_features.join(", "))}.</p>` : ""}
      </div>`;
    }).join("");
    ["academic", "placement"].forEach((k) => {
      C.diverging($(`#imp-${k}`), D.models[k].importance.map((f) => ({ label: f.label, v: f.coef })), {
        posColor: cssColor("var(--div-pos)"), negColor: cssColor("var(--div-neg)"), fmt: (v) => (v > 0 ? "+" : "") + v.toFixed(2), labelW: 170,
      });
    });
  }

  /* ================= STUDENT DRAWER ================= */
  function openStudent(id) {
    const s = byId[id];
    if (!s) return;
    const r = s.raw;
    const seg = SEG[s.segment];
    const prio = { 1: "Urgent", 2: "This week", 3: "This month" };
    const yesno = (b) => (b ? "Yes" : "No");
    $("#drawer").innerHTML = `
      <div class="drawer-head">
        <div class="who">
          <h2>${esc(s.name)}</h2>
          <div class="meta">${s.id} · ${s.dept} · Year ${s.year} · ${s.hosteller ? "Hosteller" : "Day scholar"} · ${r.sources_linked} sources linked</div>
          <div class="tags">${bandBadge(s.band)} ${riskBadge("Academic risk", s.acad_tier, s.acad_risk)}
            ${s.place_tier ? riskBadge("Placement risk", s.place_tier, s.place_risk) : '<span class="badge na">Placement risk n/a (2nd year)</span>'}
            <span class="badge">${esc(seg.label)}</span></div>
        </div>
        <div class="big-score"><div class="v">${fmt1(s.score)}</div><div class="b">Success Score</div></div>
        <button class="icon-btn" id="closeDrawer" type="button" aria-label="Close">✕</button>
      </div>
      <div class="drawer-body">
        <div class="card">
          <div class="card-head"><h2>Recommended actions</h2><span class="desc">Generated from this student's indicators and mentor notes. Segment playbook: ${esc(seg.playbook)}</span></div>
          <ul class="actions-list">${s.actions.map((a) => `<li><span class="prio p${a.priority}">${prio[a.priority]}</span><div><div>${esc(a.action)}</div><div class="owner">Owner: ${esc(a.owner)}</div></div></li>`).join("")}</ul>
        </div>
        <div class="grid g-2">
          <div class="card">
            <div class="card-head"><h2>Why this Success Score?</h2>
              <span class="desc">Points each indicator adds (blue) or removes (red) compared with the campus-average student. Baseline ${fmt1(s.baseline)} ${sumSign(s)} = <b>${fmt1(s.score)}</b>.</span></div>
            <div class="chart" id="dScore"></div>
          </div>
          <div class="card">
            <div class="card-head"><h2>Why this risk flag?</h2>
              <span class="desc">Factors pushing predicted risk up (red) or down (blue), from the trained model. ${s.place_tier ? "" : "Placement risk starts in 3rd year."}</span></div>
            <div class="seg-toggle" id="dRiskToggle" style="margin-bottom:8px">
              <button type="button" data-k="acad" aria-pressed="true">Academic ${s.acad_tier}</button>
              ${s.place_tier ? `<button type="button" data-k="place" aria-pressed="false">Placement ${s.place_tier}</button>` : ""}
            </div>
            <div class="chart" id="dRisk"></div>
          </div>
        </div>
        <div class="card">
          <div class="card-head"><h2>Pillar scores vs campus average</h2></div>
          <div class="chart" id="dPillars"></div>
          <div class="legend"><span><span class="sw" style="background:${cssColor("var(--s1)")}"></span>This student</span><span><span class="ln" style="background:${cssColor("var(--ink-2)")}"></span>Campus average</span></div>
        </div>
        <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr))">
          <div class="card"><div class="card-head"><h3>LMS logins per week</h3></div><div class="chart" id="dLms"></div></div>
          <div class="card"><div class="card-head"><h3>Attendance by month</h3></div><div class="chart" id="dAtt"></div></div>
          <div class="card"><div class="card-head"><h3>SGPA by semester</h3></div><div class="chart" id="dSgpa"></div></div>
        </div>
        <div class="card">
          <div class="card-head"><h2>Unified student view</h2><span class="desc">One record assembled from seven systems.</span></div>
          <div class="src-grid">
            ${src("Academic (SIS + exams)", [["CGPA", r.cgpa], ["Active backlogs", r.backlogs], ["SGPA trend", sgn(r.sgpa_trend)], ["Internal marks", r.internal_pct + "%"], ["Weakest subject", `${r.weakest_subject} (${r.weakest_subject_pct}%)`]])}
            ${src("Attendance (biometric)", [["Overall", r.attendance_pct + "%"], ["Lowest subject", `${r.attendance_min_subject} (${r.attendance_min_subject_pct}%)`], ["Change Jul→Sep", sgn(r.attendance_trend) + " pts"]])}
            ${src("LMS", [["Logins / week", r.lms_logins_per_week], ["Assignments submitted", r.lms_completion_pct + "%"], ["Quiz average", r.lms_quiz_avg], ["Last 4 vs first 4 wks", Math.round(r.lms_login_trend * 100) + "%"]])}
            ${src("Engagement", [["Events", r.events], ["Clubs", r.clubs], ["Hackathons", r.hackathons], ["Certifications", r.certifications]])}
            ${s.year >= 3 ? src("Placement cell", [["Took tests", yesno(r.placement_assessed)], ["Aptitude", r.aptitude_score + (r.placement_assessed ? "" : "*")], ["Coding", r.coding_score + (r.placement_assessed ? "" : "*")], ["Mock interview", r.mock_interview_rating + "/5"], ["Resume reviewed", yesno(r.resume_reviewed)]]) : src("Placement cell", [["Status", "Starts in 3rd year"]])}
            ${src("Skills assessment", [["Technical", r.technical_skill], ["Communication", r.communication], ["Teamwork", r.teamwork], ["Problem solving", r.problem_solving]])}
            ${src("Feedback", [["Satisfaction", r.survey_responded ? r.satisfaction + "/5" : "No response"], ["Stress", r.survey_responded ? r.stress + "/5" : "–"], ["Mentor rating", r.mentor_rating + "/5"], ["Concerns", r.concern_tags.join(", ") || "None"]])}
          </div>
          ${!r.placement_assessed && s.year >= 3 ? '<p class="muted" style="font-size:12px">* No placement test taken: conservatively imputed at the department\'s 10th percentile.</p>' : ""}
          ${r.mentor_remark ? `<p class="remark" style="margin-top:12px">Mentor remark: “${esc(r.mentor_remark)}”</p>` : ""}
        </div>
      </div>`;
    $("#drawer").classList.add("show");
    $("#drawer").setAttribute("aria-hidden", "false");
    $("#scrim").classList.add("show");
    $("#closeDrawer").addEventListener("click", closeStudent);
    $("#closeDrawer").focus();
    history.replaceState(null, "", "#student=" + s.id);
    // Charts need the drawer laid out to measure width.
    requestAnimationFrame(() => drawStudentCharts(s, "acad"));
    document.querySelectorAll("#dRiskToggle button").forEach((b) => b.addEventListener("click", () => {
      document.querySelectorAll("#dRiskToggle button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      drawRisk(s, b.dataset.k);
    }));
  }
  function sgn(v) { return (v > 0 ? "+" : "") + v; }
  function sumSign(s) {
    const d = s.score - s.baseline;
    return (d >= 0 ? "+ " : "− ") + Math.abs(d).toFixed(1) + " from indicators";
  }
  function src(title, pairs) {
    return `<div class="src"><h4>${esc(title)}</h4><dl class="kv">${pairs.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl></div>`;
  }
  const campusPillar = Object.fromEntries(PILLARS.map((p) => {
    const v = D.students.map((s) => s.pillars[p.key]).filter((x) => x != null);
    return [p.key, mean(v)];
  }));
  function rawFor(s, col) {
    const v = s.raw[col];
    if (typeof v === "boolean") return v ? "Yes" : "No";
    return v == null ? "–" : v;
  }
  function drawRisk(s, kind) {
    const drivers = (kind === "acad" ? s.acad_drivers : s.place_drivers);
    const top = [...drivers].sort((a, b) => Math.abs(b.v) - Math.abs(a.v)).slice(0, 7).sort((a, b) => b.v - a.v);
    C.diverging($("#dRisk"), top.map((d) => ({ label: LABEL[d.col] || d.col, v: d.v,
      tip: C.rows(LABEL[d.col] || d.col, [["Student's value", rawFor(s, d.col)], ["Effect on risk", d.v > 0 ? "raises" : "lowers"], ["Log-odds", (d.v > 0 ? "+" : "") + d.v.toFixed(2)]]) })),
    { posColor: cssColor("var(--div-pos)"), negColor: cssColor("var(--div-neg)"), fmt: (v) => (v > 0 ? "+" : "") + v.toFixed(2), labelW: 170 });
  }
  function drawStudentCharts(s, kind) {
    const top = [...s.score_drivers].sort((a, b) => Math.abs(b.v) - Math.abs(a.v)).slice(0, 9).sort((a, b) => b.v - a.v);
    C.diverging($("#dScore"), top.map((d) => ({ label: LABEL[d.col] || d.col, v: d.v,
      tip: C.rows(LABEL[d.col] || d.col, [["Student's value", rawFor(s, d.col)], ["Points vs average", (d.v > 0 ? "+" : "") + d.v.toFixed(2)]]) })),
    { posColor: cssColor("var(--div-neg)"), negColor: cssColor("var(--div-pos)"), fmt: (v) => (v > 0 ? "+" : "") + v.toFixed(1), labelW: 190 });
    drawRisk(s, kind);
    // Pillars: bars for student with campus-average tick.
    const host = $("#dPillars");
    host.innerHTML = `<div style="display:grid;gap:8px">${PILLARS.map((p) => {
      const v = s.pillars[p.key];
      const avg = campusPillar[p.key];
      return `<div style="display:grid;grid-template-columns:minmax(110px,170px) 1fr 40px;align-items:center;gap:10px;font-size:12.5px">
        <span class="ink2">${esc(p.label)} <span class="muted">${Math.round(p.weight * 100)}%</span></span>
        <div style="position:relative;height:14px;background:var(--surface-2);border-radius:4px">
          ${v == null ? "" : `<div style="height:100%;width:${v}%;background:var(--s1);border-radius:0 4px 4px 0"></div>`}
          <div title="Campus average ${avg.toFixed(1)}" style="position:absolute;top:-3px;bottom:-3px;left:${avg}%;width:2px;background:var(--ink-2)"></div>
        </div>
        <b class="num" style="text-align:right">${v == null ? "n/a" : Math.round(v)}</b></div>`;
    }).join("")}</div>`;
    const r = s.raw;
    C.spark($("#dLms"), r.lms_weekly_logins, { min: 0, max: Math.max(8, ...r.lms_weekly_logins), labels: r.lms_weekly_logins.map((_, i) => "Week " + (i + 1)), name: "Logins", color: cssColor("var(--s1)") });
    C.spark($("#dAtt"), r.attendance_monthly, { min: 40, max: 100, ref: 75, labels: MONTHS, name: "Attendance", fmt: (v) => Math.round(v) + "%", color: cssColor("var(--s1)") });
    C.spark($("#dSgpa"), r.sgpa_history, { min: 4, max: 10, labels: r.sgpa_history.map((_, i) => "Sem " + (i + 1)), name: "SGPA", fmt: (v) => (+v).toFixed(2), color: cssColor("var(--s1)") });
  }
  function closeStudent() {
    $("#drawer").classList.remove("show");
    $("#drawer").setAttribute("aria-hidden", "true");
    $("#scrim").classList.remove("show");
    C.tip.hide();
    history.replaceState(null, "", "#" + state.view);
  }
  $("#scrim").addEventListener("click", closeStudent);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && $("#drawer").classList.contains("show")) closeStudent(); });

  /* ================= RENDER ================= */
  function renderAll() {
    const list = filtered();
    $("#fCount").textContent = `${list.length} of ${D.students.length} students${state.scoreRange ? ` · score ${state.scoreRange[0]}–${state.scoreRange[1]}` : ""}`;
    if (state.view === "overview") {
      renderKpis(list); renderInsights();
      if (!list.length) {
        ["#chHist", "#chDept", "#chLms", "#chAtt", "#chScatter", "#chHeat"].forEach((id) => ($(id).innerHTML = `<div class="empty">No students match the filters.</div>`));
        return;
      }
      renderHist(list); renderDept(list); renderTrends(list); renderScatter(list); renderHeat(list);
    } else if (state.view === "students") {
      renderTable(list);
    } else if (state.view === "segments") {
      renderSegments(list);
    } else if (state.view === "method") {
      renderMethod();
    }
  }
  let rT;
  window.addEventListener("resize", () => {
    clearTimeout(rT);
    rT = setTimeout(() => {
      renderAll();
      const m = location.hash.match(/^#student=(.+)$/);
      if (m && $("#drawer").classList.contains("show")) openStudent(m[1]);
    }, 150);
  });

  $("#asof").textContent = `Data as of ${D.generated_on}`;
  const h = location.hash.slice(1);
  if (h.startsWith("student=")) { show("students"); openStudent(h.slice(8)); }
  else show(["overview", "students", "segments", "method"].includes(h) ? h : "overview");
})();
