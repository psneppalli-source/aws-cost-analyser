import { Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Api } from '../core/api.service';
import { Session } from '../core/session.service';
import { IV_CATEGORIES, OUTCOMES, when } from '../shared/labels';
import { message } from '../shared/page';
import { Line, MultiLine, Pair, PairedBars, SERIES } from '../shared/charts';
import { RiskBadge, StateView, StatusChip } from '../shared/ui';

interface Flag { rule: string; label: string; observed: number; operator: string; threshold: number; level: string; observed_period: string;
  suggested_intervention: { title: string } }
interface Risk { level: string; flags?: Flag[]; explanation: string; }
interface Profile {
  student: { student_id: string; name: string; department: string; year: number; programme?: string; email?: string; date_of_birth?: string; mentor_name?: string };
  insight: { period: string; score: number | null; indicative_score?: number | null; status: string; band: string | null; coverage: number; profile: string;
    components?: Record<string, { value: number | null }>; indicators?: Record<string, number | null>; risks?: { academic?: Risk; placement?: Risk };
    summary?: string; calculated_at?: string; mentor_name?: string } | null;
  history: { period: string; score: number | null; status: string; missing: string[] }[];
  interventions: { intervention_id: string; title: string; category: string; status: string; due_date: string; review_date: string; outcome?: { result: string } | null }[];
  cohort?: { label: string; students: number; score: number | null; components: Record<string, number | null> };
}
interface Rec { category: string; period: string; name?: string; issuer?: string; verification?: string; satisfaction?: number; stress?: number; updated_at: string; }

const COMP: Record<string, string> = { academic: 'Academic', attendance: 'Attendance', lms: 'LMS activity', placement: 'Placement readiness', skills: 'Skills', engagement: 'Engagement' };

/** The student's own dashboard: progress, comparison with classmates, what to focus on, support and actions. */
@Component({
  selector: 'app-student-home-page',
  imports: [RouterLink, StateView, StatusChip, RiskBadge, MultiLine, PairedBars],
  styles: [`.hero{display:flex;gap:28px;align-items:center;flex-wrap:wrap} .big{font-size:56px;font-weight:700;color:var(--navy-900);line-height:1}
    .focus li{margin:6px 0} .actions{display:flex;gap:10px;flex-wrap:wrap}`],
  template: `
    <app-state [loading]="loading() && !p()" [error]="error()" (retry)="load()" />
    @if (p(); as p) {
      <div class="page-head"><div><h1 style="margin-bottom:2px">Hello, {{ first() }}</h1>
        <span class="muted">{{ p.student.student_id }} · {{ p.student.department }} · Year {{ p.student.year }}@if (p.student.mentor_name) { · Mentor: {{ p.student.mentor_name }} }</span></div>
        <span class="spacer"></span>
        <div class="actions"><a class="btn" routerLink="/entry" [queryParams]="{ category: 'certification' }">Add a certificate</a>
          <a class="btn" routerLink="/entry" [queryParams]="{ category: 'feedback' }">Share feedback</a></div></div>

      @if (ins(); as i) {
        <section class="card hero" aria-label="Your Success Score">
          <div><div class="small muted">Success Score · {{ month(i.period) }}</div>
            <div class="big">{{ i.score ?? '–' }}</div>
            <div style="margin-top:6px"><app-status [status]="i.status" /> @if (i.band) { <span class="chip teal">{{ i.band }}</span> }</div></div>
          <div style="flex:1;min-width:260px">
            @if (change() !== null) { <p class="insight"><strong [style.color]="change()! >= 0 ? '#006300' : '#b42318'">{{ change()! >= 0 ? '▲ +' : '▼ ' }}{{ change() }} points</strong> since {{ month(firstPeriod()) }}.</p> }
            @if (i.score === null) { <p class="small">There isn't enough recorded data for a score yet ({{ pct(i.coverage) }} of what's needed). Missing: {{ missing().join(', ') || '–' }}.</p> }
            <div class="kpis" style="margin-top:8px">
              @for (t of tiles(); track t.label) { <div class="stat"><div class="label">{{ t.label }}</div><div class="value" style="font-size:24px">{{ t.value }}</div></div> }
            </div>
          </div>
        </section>
      }

      <div class="grid g2" style="margin-top:16px">
        @if (trend()[0].values.some(notNull)) {
          <section class="card"><div class="card-head"><h2>Your progress</h2></div>
            <app-multiline [series]="trend()" [labels]="labels()" label="Your Success Score by month" [ref]="60" refLabel="On track (60)" /></section>
        }
        @if (pairs().length) {
          <section class="card"><div class="card-head"><h2>You and your class</h2><span class="desc">Average of {{ p.cohort?.students }} classmates; no individual is shown.</span></div>
            <app-paired-bars [data]="pairs()" nameA="You" nameB="Class average" label="Your components compared with the class average" /></section>
        }
        <section class="card"><div class="card-head"><h2>What to focus on</h2></div>
          @if (focus().length) {
            <ul class="focus">@for (f of focus(); track f.label) {
              <li><app-risk [level]="f.level" /> <strong>{{ f.label }}</strong> <span class="small muted">({{ f.observed }} in {{ f.period }})</span><br>
                <span class="small">Suggested: {{ f.action }}</span></li> }</ul>
            <p class="small muted">These come from simple rules on your recorded data. Talk to your mentor about a plan.</p>
          } @else { <p>Nothing flagged right now. Keep it up!</p> }
        </section>
        <section class="card"><div class="card-head"><h2>Your support plans</h2></div>
          @if (p.interventions.length) {
            <div class="table-wrap"><table><thead><tr><th>Plan</th><th>Status</th><th>Review by</th></tr></thead><tbody>
              @for (iv of p.interventions; track iv.intervention_id) {
                <tr><td>{{ iv.title }}<br><span class="small muted">{{ cat(iv.category) }}</span></td>
                  <td>{{ iv.status }}@if (iv.outcome) { <br><span class="small muted">{{ outcome(iv.outcome.result) }}</span> }</td><td>{{ iv.review_date }}</td></tr>
              }</tbody></table></div>
          } @else { <p class="muted">No support plans at the moment.</p> }
        </section>
        <section class="card"><div class="card-head"><h2>Your submissions</h2><span class="spacer"></span>
          <a class="btn small" routerLink="/entry" [queryParams]="{ category: 'certification' }">Add a certificate</a></div>
          @if (certs().length) {
            <ul class="small">@for (c of certs(); track c.name + c.period) {
              <li><strong>{{ c.name }}</strong> · {{ c.issuer }} · {{ c.period }} — @switch (c.verification) {
                @case ('verified') { <span class="chip teal">✓ Verified</span> } @case ('rejected') { <span class="badge high">Rejected</span> }
                @default { <span class="badge medium">■ Awaiting verification</span> } }</li> }</ul>
          } @else { <p class="muted small">No certificates yet. Verified certificates count towards your engagement.</p> }
          @if (lastFeedback(); as f) { <p class="small muted">Last feedback: {{ f.period }} (shared with your mentor; it never lowers your score).</p> }
        </section>
        <section class="card"><div class="card-head"><h2>Your details</h2></div>
          <dl class="small" style="display:grid;grid-template-columns:auto 1fr;gap:4px 14px;margin:0">
            <dt class="muted">Programme</dt><dd style="margin:0">{{ p.student.programme }}</dd>
            <dt class="muted">Email</dt><dd style="margin:0">{{ p.student.email || '–' }}</dd>
            <dt class="muted">Date of birth</dt><dd style="margin:0">{{ p.student.date_of_birth || '–' }}</dd>
            <dt class="muted">Sign-in security</dt><dd style="margin:0">@if (session.me()?.user?.mfa?.enabled) { Authenticator app ✓ } @else { <a routerLink="/security">Set up authenticator</a> }</dd></dl>
          <p class="small muted" style="margin-top:8px">Something wrong? Contact the college office. <a [routerLink]="['/students', 'real', p.student.student_id]">See full details</a></p>
        </section>
      </div>
    }`,
})
export class StudentHomePage {
  private api = inject(Api);
  session = inject(Session);
  p = signal<Profile | null>(null);
  records = signal<Rec[]>([]);
  loading = signal(true);
  error = signal<string | null>(null);
  notNull = (v: number | null) => v !== null;

  ins = computed(() => this.p()?.insight || null);
  first = computed(() => (this.p()?.student.name || '').split(' ')[0]);
  labels = computed(() => (this.p()?.history || []).map((h) => h.period));
  trend = computed<Line[]>(() => [{ name: 'Your score', color: SERIES[0], values: (this.p()?.history || []).map((h) => h.score) }]);
  scored = computed(() => (this.p()?.history || []).filter((h) => h.score !== null));
  firstPeriod = computed(() => this.scored()[0]?.period || null);
  change = computed(() => { const s = this.scored(); return s.length > 1 ? +(s[s.length - 1].score! - s[0].score!).toFixed(1) : null; });
  missing = computed(() => { const h = this.p()?.history || []; return h.length ? h[h.length - 1].missing || [] : []; });
  tiles = computed(() => {
    const ind = this.ins()?.indicators || {}; const out: { label: string; value: string }[] = [];
    const f = (v: number | null | undefined, unit = '') => (v === null || v === undefined ? '–' : `${Math.round(v * 10) / 10}${unit}`);
    out.push({ label: 'Attendance', value: f(ind['attendance_pct'], '%') });
    out.push({ label: 'CGPA', value: f(ind['cgpa']) });
    out.push({ label: 'Assignments submitted', value: f(ind['assignment_completion_pct'], '%') });
    if (this.ins()?.profile === 'placement_years') out.push({ label: 'Coding assessment', value: f(ind['coding']) });
    return out;
  });
  pairs = computed<Pair[]>(() => {
    const c = this.p()?.cohort; const comps = this.ins()?.components; if (!c || !comps) return [];
    return Object.keys(COMP).filter((k) => k in comps).map((k) => ({ label: COMP[k], a: comps[k]?.value ?? null, b: c.components[k] ?? null }));
  });
  focus = computed(() => {
    const r = this.ins()?.risks || {}; const out: { label: string; level: string; observed: number; period: string; action: string }[] = [];
    for (const k of ['academic', 'placement'] as const) for (const f of r[k]?.flags || [])
      out.push({ label: f.label, level: f.level, observed: f.observed, period: f.observed_period, action: f.suggested_intervention.title });
    return out.sort((a, b) => (a.level === 'high' ? 0 : 1) - (b.level === 'high' ? 0 : 1)).slice(0, 6);
  });
  certs = computed(() => this.records().filter((r) => r.category === 'certification').sort((a, b) => b.period.localeCompare(a.period)));
  lastFeedback = computed(() => this.records().filter((r) => r.category === 'feedback').sort((a, b) => b.period.localeCompare(a.period))[0] || null);

  constructor() { this.load(); }

  month(p?: string | null) { return p ? new Date(p + '-01').toLocaleString(undefined, { month: 'long', year: 'numeric' }) : ''; }
  pct(v: number) { return `${Math.round(v * 100)}%`; }
  cat(c: string) { return IV_CATEGORIES[c] || c; }
  outcome(o: string) { return OUTCOMES[o] || o; }
  when = when;

  async load() {
    const st = this.session.me()?.user.student;
    if (!st) { this.error.set('This page is for student accounts.'); this.loading.set(false); return; }
    this.loading.set(true); this.error.set(null);
    try {
      const [p, r] = await Promise.all([
        this.api.get<Profile>(`/students/${st.dataset}/${st.student_id}`),
        this.api.get<{ items: Rec[] }>(`/students/${st.dataset}/${st.student_id}/records`),
      ]);
      this.p.set(p); this.records.set(r.items);
    } catch (e) { this.error.set(message(e)); }
    finally { this.loading.set(false); }
  }
}
