import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { AiSummary } from '../shared/ai-summary';
import { RouterLink } from '@angular/router';
import { Api } from '../core/api.service';
import { Session } from '../core/session.service';
import { SEGMENTS, when } from '../shared/labels';
import { RealEmpty, blankFilters, message } from '../shared/page';
import { FilterBar, Filters, StateView, StatusChip } from '../shared/ui';
import { HBar, HBars, HStack, Line, MultiLine, Part, SERIES, STATUS } from '../shared/charts';

const SEG_SHORT: Record<string, string> = {
  strong_academics_low_placement: 'Strong academics', declining_attendance_results: 'Declining trend',
  strong_skills_academic_support: 'Strong skills', improving_after_intervention: 'Improving',
  consistently_performing_well: 'Consistently strong', insufficient_data: 'Not enough data',
};

interface Dashboard {
  dataset: string; period: string; periods: string[]; students: number;
  kpis: { average_score: number | null; status: Record<string, number>; academic_risk: Record<string, number>;
    placement_risk: Record<string, number>; needs_review: number; open_interventions: number; overdue_interventions: number; stale: number; };
  bands: Record<string, number>;
  risk_by_department: { department: string; students: number; academic: Record<string, number>; placement: Record<string, number> }[];
  segments: Record<string, number>;
  trend: { period: string; average_score: number | null; students_scored: number; high_academic_risk: number; high_placement_risk: number }[];
  needs_review: { student_id: string; name: string; department: string; year: number; score: number | null; status: string; reasons: string[] }[];
  last_calculated_at: string | null;
}

@Component({
  selector: 'app-overview-page',
  imports: [AiSummary, RouterLink, FilterBar, StateView, HBars, HStack, MultiLine, StatusChip, RealEmpty],
  template: `
    <div class="page-head">
      <h1>Overview</h1><span class="spacer"></span>
      <button class="btn small" type="button" (click)="load()" [disabled]="loading()">Refresh</button>
      <p class="sub">Success Scores, independent academic and placement risks, and the students who need a review.
        @if (d(); as d) { Period {{ d.period }} · {{ d.students }} students · calculated {{ when(d.last_calculated_at) }} · scoring v{{ session.me()?.scoring_version }} }</p>
    </div>
    <app-filters [value]="filters()" (changed)="filters.set($event)" [departments]="departments()" [periods]="periods()" [showRisk]="false" [showSegment]="false" />
    <app-ai-summary kind="overview" [department]="filters().department" [year]="filters().year" subject="this overview" />
    <app-real-empty [show]="!loading() && d()?.students === 0" />
    <app-state [loading]="loading() && !d()" [error]="error()" (retry)="load()" [empty]="d()?.students === 0" emptyText="No students match these filters." />
    @if (d(); as d) { @if (d.students) {
      <section class="kpis" aria-label="Key figures">
        <div class="card kpi hero"><div class="label">Average Success Score</div><div class="value">{{ d.kpis.average_score ?? '–' }}</div>
          <div class="note">of {{ scored() }} students with enough data</div></div>
        <div class="card kpi"><div class="label">High academic risk</div><div class="value">{{ d.kpis.academic_risk['high'] || 0 }}</div>
          <div class="note">{{ d.kpis.academic_risk['medium'] || 0 }} medium</div></div>
        <div class="card kpi"><div class="label">High placement risk</div><div class="value">{{ d.kpis.placement_risk['high'] || 0 }}</div>
          <div class="note">{{ d.kpis.placement_risk['insufficient_data'] || 0 }} not yet assessed</div></div>
        <div class="card kpi"><div class="label">Need review</div><div class="value">{{ d.kpis.needs_review }}</div>
          <div class="note">rules-based, see reasons below</div></div>
        <div class="card kpi"><div class="label">Open interventions</div><div class="value">{{ d.kpis.open_interventions }}</div>
          <div class="note">{{ d.kpis.overdue_interventions }} overdue</div></div>
        <div class="card kpi"><div class="label">Insufficient data</div><div class="value">{{ d.kpis.status['insufficient_data'] || 0 }}</div>
          <div class="note">{{ d.kpis.status['provisional'] || 0 }} provisional · {{ d.kpis.stale }} awaiting recalculation</div></div>
      </section>
      <div class="grid g2" style="margin-top:16px">
        <section class="card"><div class="card-head"><h2>Average score by period</h2>
          <span class="desc">Only students with enough data; profiles are not mixed across years.</span></div>
          <app-multiline [labels]="trendLabels()" [series]="trendSeries()" label="Average Success Score by reporting period" [ref]="60" refLabel="On track (60)" /></section>
        <section class="card"><div class="card-head"><h2>Score bands</h2><span class="desc">Students without enough data are counted separately, never as zero.</span></div>
          <app-hbars [data]="bands()" label="Students per score band" /></section>
        <section class="card"><div class="card-head"><h2>Academic risk by department</h2></div>
          <app-hstack [rows]="riskRows('academic')" [parts]="riskParts" label="Academic risk levels per department" /></section>
        <section class="card"><div class="card-head"><h2>Placement risk by department</h2><span class="desc">Years 3–4 only. Missing assessments are “insufficient data”, not poor readiness.</span></div>
          <app-hstack [rows]="riskRows('placement')" [parts]="riskParts" label="Placement risk levels per department" /></section>
      </div>
      <section class="card" style="margin-top:16px"><div class="card-head"><h2>Segments</h2><span class="desc">Rules-based groupings; a student can be in more than one.</span></div>
        <app-hbars [data]="segmentBars()" label="Students per segment" /></section>
      <section class="card" style="margin-top:16px">
        <div class="card-head"><h2>Students needing review</h2><span class="desc">Staff decide what to do; nothing is assigned automatically.</span></div>
        <div class="table-wrap"><table>
          <thead><tr><th>Student</th><th>Dept · Year</th><th class="num">Score</th><th>Status</th><th>Why</th></tr></thead>
          <tbody>
            @for (r of d.needs_review; track r.student_id) {
              <tr><td><a [routerLink]="['/students', d.dataset, r.student_id]">{{ r.name }}</a><br><span class="muted mono small">{{ r.student_id }}</span></td>
                <td>{{ r.department }} · Y{{ r.year }}</td><td class="num">{{ r.score ?? '–' }}</td><td><app-status [status]="r.status" /></td>
                <td class="small">{{ r.reasons.join('; ') }}</td></tr>
            } @empty { <tr><td colspan="5" class="muted">No students currently meet the review rules.</td></tr> }
          </tbody></table></div>
      </section>
    } }`,
})
export class OverviewPage {
  private api = inject(Api);
  session = inject(Session);
  when = when;
  filters = signal<Filters>(blankFilters());
  d = signal<Dashboard | null>(null);
  loading = signal(true);
  error = signal<string | null>(null);
  departments = computed(() => Object.keys(this.session.me()?.departments || {}));
  periods = computed(() => this.session.me()?.periods || []);
  scored = computed(() => { const s = this.d()?.kpis.status || {}; return (s['complete'] || 0) + (s['provisional'] || 0); });
  trendLabels = computed(() => (this.d()?.trend || []).map((t) => t.period));
  trendSeries = computed<Line[]>(() => [{ name: 'Average score', color: SERIES[0], values: (this.d()?.trend || []).map((t) => t.average_score) }]);
  /** Score bands are ordered: one blue ramp from strong to at-risk; "not enough data" is neutral, never a score. */
  bands = computed<HBar[]>(() => {
    const b = this.d()?.bands || {};
    const order: [string, string][] = [['Strong', '#184f95'], ['On track', '#2a78d6'], ['Needs attention', '#5598e7'], ['At risk', '#86b6ef'], ['Insufficient data', STATUS.neutral]];
    return order.map(([k, color]) => ({ label: k === 'Insufficient data' ? 'Not enough data' : k, value: b[k] || 0, color, note: 'students' }));
  });
  segmentBars = computed<HBar[]>(() => Object.entries(SEGMENTS).map(([k, v]) => ({ label: SEG_SHORT[k] || v, note: v, value: this.d()?.segments[k] || 0,
    color: k === 'insufficient_data' ? STATUS.neutral : SERIES[0] })));
  riskParts: Part[] = [{ key: 'high', label: '▲ High', color: STATUS.critical }, { key: 'medium', label: '■ Medium', color: STATUS.warning },
    { key: 'low', label: '● Low', color: STATUS.good }, { key: 'insufficient_data', label: '◌ Not enough data', color: STATUS.neutral }];

  constructor() {
    effect(() => { this.session.dataset(); this.filters(); untracked(() => this.load()); });
  }

  riskRows(kind: 'academic' | 'placement') {
    return (this.d()?.risk_by_department || []).map((r) => ({ label: r.department, values: r[kind] }));
  }

  async load() {
    this.loading.set(true); this.error.set(null);
    const f = this.filters();
    try {
      this.d.set(await this.api.get<Dashboard>('/dashboard', { dataset: this.session.dataset(), department: f.department, year: f.year, period: f.period }));
    } catch (e) { this.error.set(message(e)); }
    finally { this.loading.set(false); }
  }
}
