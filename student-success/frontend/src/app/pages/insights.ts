import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { AiHub, AiTool } from '../shared/ai-hub';
import { AskPanel } from '../shared/ask-panel';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { Api } from '../core/api.service';
import { Session } from '../core/session.service';
import { IV_CATEGORIES, OUTCOMES } from '../shared/labels';
import { RealEmpty, message } from '../shared/page';
import { Col, Columns, HBar, HBars, Heatmap, Line, MultiLine, Pt, STATUS, Scatter, Spark, StackColumns, deptColor } from '../shared/charts';
import { StateView } from '../shared/ui';

interface Mover { student_id: string; name: string; department: string; year: number; from_period: string; to_period: string;
  from: number; to: number; change: number; series: (number | null)[]; }
interface Analytics {
  dataset: string; period: string; periods: string[]; students: number; scored: number;
  kpis: { average_score: number | null; previous_average: number | null; previous_period: string | null; complete_pct: number | null;
    any_high_risk: number; improved: number; declined: number };
  distribution: { label: string; from: number; to: number; count: number }[];
  components: { key: string; label: string; avg: number | null; n: number }[];
  components_by_department: { department: string; values: Record<string, number | null> }[];
  department_trend: { department: string; values: (number | null)[] }[];
  year_averages: { year: number; avg: number | null; students: number }[];
  coverage: { period: string; complete: number; provisional: number; insufficient_data: number }[];
  risk_matrix: { levels: string[]; counts: Record<string, Record<string, number>> };
  scatter: { student_id: string; name: string; department: string; year: number; attendance: number; academic: number; score: number | null }[];
  movers: { up: Mover[]; down: Mover[] };
  risk_trend: { academic: Record<string, number>[]; placement: Record<string, number>[] };
  band_flow: { bands: string[]; counts: Record<string, Record<string, number>>; from: string | null; to: string };
  early_warning: { student_id: string; name: string; department: string; year: number; score: number | null; reasons: string[]; has_open_intervention: boolean }[];
  early_warning_total: number;
  interventions: { total: number; by_status: Record<string, number>; by_outcome: Record<string, number>; by_category: Record<string, number>; overdue: number };
}

const LEVEL: Record<string, string> = { high: 'High', medium: 'Medium', low: 'Low', insufficient_data: 'No data', not_applicable: 'N/A (yr 1–2)' };
const COMP_SHORT: Record<string, string> = { academic: 'Academic', attendance: 'Attendance', lms: 'LMS', placement: 'Placement', skills: 'Skills', engagement: 'Engagement' };

@Component({
  selector: 'app-insights-page',
  imports: [AiHub, AskPanel, FormsModule, RouterLink, StateView, RealEmpty, Columns, HBars, Heatmap, MultiLine, Scatter, StackColumns, Spark],
  template: `
    <div class="page-head"><h1>Insights</h1><span class="spacer"></span>
      <button class="btn small" type="button" (click)="load()" [disabled]="loading()">Refresh</button>
      <p class="sub">Patterns across the students you're responsible for. Figures describe recorded data; they show association, not cause.</p></div>
    <form class="filters" (submit)="$event.preventDefault()">
      <label>Department<select name="d" [ngModel]="dept()" (ngModelChange)="dept.set($event)"><option value="">All</option>
        @for (d of departments(); track d) { <option [value]="d">{{ d }}</option> }</select></label>
      <label>Year<select name="y" [ngModel]="year()" (ngModelChange)="year.set($event)"><option value="">All</option>
        @for (y of ['1','2','3','4']; track y) { <option [value]="y">Year {{ y }}</option> }</select></label>
    </form>
    <app-ask-panel />
    <app-ai-hub [tools]="aiTools" [department]="dept()" [year]="year()" />
    <app-real-empty [show]="!loading() && a()?.students === 0" />
    <app-state [loading]="loading() && !a()" [error]="error()" (retry)="load()" [empty]="a()?.students === 0" emptyText="No students match these filters." />

    @if (a(); as a) { @if (a.students) {
      <div [style.opacity]="loading() ? 0.55 : 1" style="transition:opacity .2s">
      <section class="grid kpis" aria-label="Headline figures">
        <div class="card stat"><div class="label">Average Success Score · {{ month(a.period) }}</div>
          <div class="value hero">{{ a.kpis.average_score ?? '–' }}</div>
          @if (delta() !== null) { <div class="delta" [class.up]="delta()! > 0" [class.down]="delta()! < 0">{{ delta()! > 0 ? '▲' : delta()! < 0 ? '▼' : '■' }}
            {{ abs(delta()!) }} pts vs {{ month(a.kpis.previous_period) }}</div> }
          @else { <div class="delta">{{ a.scored }} of {{ a.students }} students scored</div> }</div>
        <div class="card stat"><div class="label">Complete data</div><div class="value">{{ a.kpis.complete_pct ?? '–' }}%</div>
          <div class="delta">of students have every component this period</div></div>
        <div class="card stat"><div class="label">High risk (academic or placement)</div><div class="value">{{ a.kpis.any_high_risk }}</div>
          <div class="delta">{{ pctOf(a.kpis.any_high_risk, a.students) }}% of students</div></div>
        <div class="card stat"><div class="label">Improved by 5+ points</div><div class="value">{{ a.kpis.improved }}</div>
          <div class="delta down">{{ a.kpis.declined }} declined by 5+</div></div>
        <div class="card stat"><div class="label">Interventions</div><div class="value">{{ a.interventions.total }}</div>
          <div class="delta" [class.down]="a.interventions.overdue > 0">{{ a.interventions.overdue }} overdue</div></div>
      </section>

      <div class="grid g2" style="margin-top:16px">
        @if (a.distribution.length) {
          <section class="card"><div class="card-head"><h2>How scores are spread</h2></div>
            <p class="insight">{{ distText() }}</p>
            <app-columns [data]="dist()" label="Number of students in each Success Score range" xName="Score range" yName="Students" /></section>
        }
        @if (trend().length) {
          <section class="card"><div class="card-head"><h2>Average score by department</h2></div>
            <p class="insight">{{ trendText() }}</p>
            <app-multiline [series]="trend()" [labels]="a.periods" label="Average Success Score per department and month" seriesName="Department"
                           [ref]="60" refLabel="On track (60)" /></section>
        }
        <section class="card"><div class="card-head"><h2>Where students gain and lose points</h2></div>
          <p class="insight">{{ compText() }}</p>
          <app-hbars [data]="compBars()" [max]="100" label="Average component value (0–100)" /></section>
        @if (heat().rows.length) {
          <section class="card"><div class="card-head"><h2>Component strength by department</h2></div>
            <p class="insight">{{ heatText() }}</p>
            <app-heatmap [rows]="heat().rows" [cols]="heat().cols" [values]="heat().values" [max]="100" label="Average component value by department"
                         valueName="Average (0–100)" minLabel="0" maxLabel="100" /></section>
        }
        @if (scatter().length) {
          <section class="card"><div class="card-head"><h2>Attendance and academic performance</h2></div>
            <p class="insight">{{ scatterText() }}</p>
            <app-scatter [points]="scatter()" label="Each student's attendance and academic component" xName="Attendance" yName="Academic"
                         (pick)="open($event)" /></section>
        }
        <section class="card"><div class="card-head"><h2>Academic risk × placement risk</h2></div>
          <p class="insight">{{ matrixText() }}</p>
          <app-heatmap [rows]="matrix().rows" [cols]="matrix().cols" [values]="matrix().values" label="Students by academic and placement risk level"
                       rowTitle="Academic risk ↓" colTitle="Placement risk →"
                       valueName="Students" minLabel="Fewer" maxLabel="More" /></section>
        <section class="card"><div class="card-head"><h2>Data completeness over time</h2></div>
          <p class="insight">{{ coverageText() }}</p>
          <app-stack-columns [rows]="coverage()" [parts]="coverageParts" label="Students by data completeness per month" /></section>
        @if (yearBars().length > 1) {
          <section class="card"><div class="card-head"><h2>Average score by year of study</h2></div>
            <p class="insight">Years 1–2 and 3–4 use different components (placement applies from year 3), so compare within those groups.</p>
            <app-hbars [data]="yearBars()" [max]="100" label="Average Success Score by year of study" /></section>
        }
        @if (a.interventions.total) {
          <section class="card"><div class="card-head"><h2>Interventions</h2></div>
            <p class="insight">{{ ivText() }}</p>
            <app-hbars [data]="ivStatus()" label="Interventions by status" />
            <h3 style="margin-top:12px">Recorded outcomes</h3>
            <app-hbars [data]="ivOutcome()" label="Interventions by recorded outcome" /></section>
        }
      </div>

      @if (a.early_warning.length) {
        <section class="card" style="margin-top:16px"><div class="card-head"><h2>Early warning: slipped this month</h2>
          <span class="desc">{{ a.early_warning_total }} student(s) changed for the worse since {{ month(a.kpis.previous_period) }}; those without support are listed first.</span></div>
          <div class="table-wrap"><table><thead><tr><th>Student</th><th class="num">Score</th><th>What changed</th><th>Support</th></tr></thead><tbody>
            @for (w of a.early_warning; track w.student_id) {
              <tr><td><a [routerLink]="['/students', a.dataset, w.student_id]">{{ w.name }}</a><br><span class="small muted">{{ w.department }} · Y{{ w.year }}</span></td>
                <td class="num">{{ w.score ?? '–' }}</td><td class="small">{{ w.reasons.join('; ') }}</td>
                <td>@if (w.has_open_intervention) { <span class="chip teal">Intervention open</span> } @else { <span class="badge medium">■ None yet</span> }</td></tr>
            }</tbody></table></div></section>
      }
      <div class="grid g2" style="margin-top:16px">
        <section class="card"><div class="card-head"><h2>Risk over time</h2><span class="spacer"></span>
          <div class="row" role="group" aria-label="Risk type" style="gap:4px">
            @for (k of ['academic', 'placement']; track k) { <button type="button" class="btn small" [class.primary]="riskKind() === k" [attr.aria-pressed]="riskKind() === k" (click)="riskKind.set(k)">{{ k === 'academic' ? 'Academic' : 'Placement' }}</button> }
          </div></div>
          <p class="insight">{{ riskTrendText() }}</p>
          <app-stack-columns [rows]="riskTrend()" [parts]="riskParts" label="Students by risk level per month" /></section>
        @if (flow().rows.length) {
          <section class="card"><div class="card-head"><h2>Band movement since {{ month(a.band_flow.from) }}</h2></div>
            <p class="insight">{{ flowText() }}</p>
            <app-heatmap [rows]="flow().rows" [cols]="flow().cols" [values]="flow().values" label="Students moving between score bands"
                         valueName="Students" rowTitle="Last month ↓" colTitle="This month →" minLabel="Fewer" maxLabel="More" /></section>
        }
      </div>

      @if (a.movers.up.length || a.movers.down.length) {
        <div class="grid g2" style="margin-top:16px">
          @for (box of moverBoxes(); track box.title) {
            <section class="card"><div class="card-head"><h2>{{ box.title }}</h2><span class="desc">First vs latest scored month</span></div>
              <div class="table-wrap"><table class="movers"><tbody>
                @for (m of box.items; track m.student_id) {
                  <tr><td><a [routerLink]="['/students', a.dataset, m.student_id]">{{ m.name }}</a><br><span class="small muted">{{ m.department }} · Y{{ m.year }}</span></td>
                    <td><app-spark [values]="m.series" [color]="dc(m.department)" [label]="'Score trend for ' + m.name" /></td>
                    <td class="num small">{{ m.from }} → {{ m.to }}</td>
                    <td class="num"><strong [style.color]="m.change > 0 ? '#006300' : '#b42318'">{{ m.change > 0 ? '▲ +' : '▼ ' }}{{ m.change }}</strong></td></tr>
                }</tbody></table></div></section>
          }
        </div>
      }
      </div>
    } }`,
})
export class InsightsPage {
  aiTools: AiTool[] = [{ kind: 'insights', label: 'Summary', action: 'Summarise these insights' }];
  private api = inject(Api);
  private router = inject(Router);
  session = inject(Session);
  a = signal<Analytics | null>(null);
  dept = signal('');
  year = signal('');
  loading = signal(true);
  error = signal<string | null>(null);
  departments = computed(() => Object.keys(this.session.me()?.departments || {}));
  riskKind = signal('academic');
  riskParts = [
    { key: 'high', label: '▲ High', color: STATUS.critical }, { key: 'medium', label: '■ Medium', color: STATUS.warning },
    { key: 'low', label: '● Low', color: STATUS.good }, { key: 'insufficient_data', label: '◌ Not enough data', color: STATUS.neutral },
  ];
  coverageParts = [
    { key: 'complete', label: 'Complete', color: STATUS.good },
    { key: 'provisional', label: 'Provisional', color: STATUS.warning },
    { key: 'insufficient_data', label: 'Not enough data', color: STATUS.neutral },
  ];

  constructor() { effect(() => { this.session.dataset(); this.dept(); this.year(); untracked(() => this.load()); }); }

  async load() {
    this.loading.set(true); this.error.set(null);
    try { this.a.set(await this.api.get<Analytics>('/analytics', { dataset: this.session.dataset(), department: this.dept(), year: this.year() })); }
    catch (e) { this.error.set(message(e)); }
    finally { this.loading.set(false); }
  }

  // --- helpers
  abs = Math.abs;
  dc = deptColor;
  month(p?: string | null) { return p ? new Date(p + '-01').toLocaleString(undefined, { month: 'long', year: 'numeric' }) : ''; }
  pctOf(n: number, d: number) { return d ? Math.round((100 * n) / d) : 0; }
  open(id: string) { this.router.navigate(['/students', this.a()!.dataset, id]); }

  delta = computed(() => { const k = this.a()?.kpis; return k && k.average_score !== null && k.previous_average !== null ? +(k.average_score - k.previous_average).toFixed(1) : null; });
  dist = computed<Col[]>(() => (this.a()?.distribution || []).map((b) => ({ label: b.label, value: b.count })));
  trend = computed<Line[]>(() => (this.a()?.department_trend || []).filter((d) => d.values.some((v) => v !== null))
    .map((d) => ({ name: d.department, values: d.values, color: deptColor(d.department) })));
  compBars = computed<HBar[]>(() => (this.a()?.components || []).map((c) => ({ label: c.label, value: c.avg, note: `${c.n} students with data` })));
  heat = computed(() => {
    const a = this.a(); const keys = (a?.components || []).filter((c) => c.avg !== null).map((c) => c.key);
    const rows = (a?.components_by_department || []);
    return { rows: rows.map((r) => r.department), cols: keys.map((k) => COMP_SHORT[k]), values: rows.map((r) => keys.map((k) => r.values[k] ?? null)) };
  });
  scatter = computed<Pt[]>(() => (this.a()?.scatter || []).map((s) => ({ id: s.student_id, label: s.name, group: s.department,
    x: Math.round(s.attendance), y: Math.round(s.academic), note: s.score !== null ? `Score ${s.score}` : 'Not enough data for a score' })));
  matrix = computed(() => {
    const m = this.a()?.risk_matrix; if (!m) return { rows: [], cols: [], values: [] };
    const used = (lv: string, axis: 'r' | 'c') => m.levels.some((o) => (axis === 'r' ? m.counts[lv][o] : m.counts[o][lv]) > 0);
    const rows = m.levels.filter((l) => used(l, 'r')); const cols = m.levels.filter((l) => used(l, 'c'));
    return { rows: rows.map((r) => LEVEL[r]), cols: cols.map((c) => LEVEL[c]), values: rows.map((r) => cols.map((c) => m.counts[r][c])) };
  });
  coverage = computed(() => (this.a()?.coverage || []).map((c) => ({ label: c.period, values: { complete: c.complete, provisional: c.provisional, insufficient_data: c.insufficient_data } })));
  yearBars = computed<HBar[]>(() => (this.a()?.year_averages || []).map((y) => ({ label: `Year ${y.year}`, value: y.avg, note: `${y.students} students` })));
  ivStatus = computed<HBar[]>(() => ['Open', 'In Progress', 'Completed'].map((s) => ({ label: s, value: this.a()?.interventions.by_status[s] || 0 })));
  ivOutcome = computed<HBar[]>(() => Object.keys(OUTCOMES).map((o) => ({ label: OUTCOMES[o], value: this.a()?.interventions.by_outcome[o] || 0,
    color: o === 'improved' ? STATUS.good : o === 'declined' ? STATUS.critical : STATUS.neutral })));
  riskTrend = computed(() => { const a = this.a(); if (!a) return [];
    const series = a.risk_trend[this.riskKind() as 'academic' | 'placement'];
    return a.periods.map((p, i) => ({ label: p, values: series[i] || {} })); });
  riskTrendText = computed(() => {
    const r = this.riskTrend(); if (r.length < 2) return '';
    const hi = (x: { values: Record<string, number> }) => x.values['high'] || 0;
    const first = r.find((x) => Object.keys(x.values).length) || r[0]; const last = r[r.length - 1];
    const d = hi(last) - hi(first);
    return `${hi(last)} students at high ${this.riskKind()} risk in ${this.month(last.label)} — ${d === 0 ? 'unchanged' : (d > 0 ? 'up ' : 'down ') + Math.abs(d)} since ${this.month(first.label)}.`;
  });
  flow = computed(() => {
    const f = this.a()?.band_flow; if (!f || !f.from) return { rows: [], cols: [], values: [] };
    const used = f.bands.filter((b) => f.bands.some((o) => (f.counts[b]?.[o] || 0) + (f.counts[o]?.[b] || 0) > 0));
    const name = (b: string) => (b === 'Not enough data' ? 'No data' : b);
    return { rows: used.map(name), cols: used.map(name), values: used.map((r) => used.map((c) => f.counts[r][c] || 0)) };
  });
  flowText = computed(() => {
    const f = this.a()?.band_flow; if (!f || !f.from) return '';
    const order = f.bands.slice(0, -1); let up = 0, down = 0, same = 0;
    order.forEach((a, i) => order.forEach((b, j) => { const n = f.counts[a][b] || 0; if (j < i) up += n; else if (j > i) down += n; else same += n; }));
    return `${up} moved up a band, ${down} moved down, ${same} stayed. Bands: Strong 75+, On track 60+, Needs attention 45+.`;
  });
  moverBoxes = computed(() => [{ title: 'Biggest improvements', items: this.a()?.movers.up || [] }, { title: 'Largest declines', items: this.a()?.movers.down || [] }]
    .filter((b) => b.items.length));

  // --- one-line takeaways (descriptive only)
  distText = computed(() => {
    const d = this.a()?.distribution || []; const n = d.reduce((s, b) => s + b.count, 0); if (!n) return '';
    const top = [...d].sort((x, y) => y.count - x.count)[0];
    const below40 = d.filter((b) => b.to <= 40).reduce((s, b) => s + b.count, 0);
    const over75 = d.filter((b) => b.from >= 80).reduce((s, b) => s + b.count, 0) + Math.round((d.find((b) => b.from === 70)?.count || 0) / 2);
    return `The most common range is ${top.label} (${top.count} of ${n} students). ${this.pctOf(below40, n)}% score below 40; roughly ${this.pctOf(over75, n)}% are in the Strong band (75+).`;
  });
  trendText = computed(() => {
    const t = this.trend(); if (!t.length) return '';
    const last = t.map((s) => ({ n: s.name, v: [...s.values].reverse().find((v) => v !== null) as number })).sort((x, y) => y.v - x.v);
    return last.length > 1 ? `${last[0].n} leads at ${last[0].v}; ${last[last.length - 1].n} is lowest at ${last[last.length - 1].v}. Gaps mean not enough data that month.`
      : `${last[0].n} averages ${last[0].v} in the latest month.`;
  });
  compText = computed(() => {
    const c = (this.a()?.components || []).filter((x) => x.avg !== null).sort((x, y) => y.avg! - x.avg!); if (!c.length) return '';
    return c.length > 1 ? `Strongest: ${c[0].label} (${c[0].avg}). Weakest: ${c[c.length - 1].label} (${c[c.length - 1].avg}) — the clearest place to focus support.`
      : `${c[0].label} averages ${c[0].avg}.`;
  });
  heatText = computed(() => {
    const h = this.heat(); let best = { v: 101, r: '', c: '' };
    h.values.forEach((row, i) => row.forEach((v, j) => { if (v !== null && v < best.v) best = { v, r: h.rows[i], c: h.cols[j] }; }));
    return best.r ? `Lowest cell: ${best.r} · ${best.c} (${Math.round(best.v)}). Darker means stronger.` : '';
  });
  scatterText = computed(() => {
    const s = this.scatter(); if (s.length < 5) return '';
    const mx = s.reduce((a, p) => a + p.x, 0) / s.length, my = s.reduce((a, p) => a + p.y, 0) / s.length;
    let num = 0, dx = 0, dy = 0; s.forEach((p) => { num += (p.x - mx) * (p.y - my); dx += (p.x - mx) ** 2; dy += (p.y - my) ** 2; });
    const r = dx && dy ? num / Math.sqrt(dx * dy) : 0;
    const strength = Math.abs(r) >= 0.6 ? 'strongly' : Math.abs(r) >= 0.3 ? 'moderately' : 'weakly';
    return `Attendance and academic results are ${strength} ${r >= 0 ? 'linked' : 'inversely linked'} (r = ${r.toFixed(2)}, ${s.length} students). Select a dot to open the student.`;
  });
  matrixText = computed(() => {
    const m = this.a()?.risk_matrix; if (!m) return '';
    const both = m.counts['high']?.['high'] || 0; const acadOnly = Object.entries(m.counts['high'] || {}).filter(([k]) => k !== 'high').reduce((s, [, v]) => s + v, 0);
    return `${both} student${both === 1 ? '' : 's'} at high risk on both; ${acadOnly} high academic risk only. Placement applies from year 3.`;
  });
  coverageText = computed(() => {
    const c = this.a()?.coverage || []; if (!c.length) return '';
    const last = c[c.length - 1]; const tot = last.complete + last.provisional + last.insufficient_data;
    return `In ${this.month(last.period)}, ${this.pctOf(last.complete, tot)}% complete, ${this.pctOf(last.insufficient_data, tot)}% without enough data for a score.`;
  });
  ivText = computed(() => {
    const iv = this.a()?.interventions; if (!iv) return '';
    const done = iv.by_status['Completed'] || 0; const imp = iv.by_outcome['improved'] || 0;
    const top = Object.entries(iv.by_category).sort((x, y) => y[1] - x[1])[0];
    return `${done} completed, ${imp} with an improved outcome. Most common: ${top ? IV_CATEGORIES[top[0]] || top[0] : '–'}.`;
  });
}
