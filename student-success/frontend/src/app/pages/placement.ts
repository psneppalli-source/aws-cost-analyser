import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Api } from '../core/api.service';
import { Session } from '../core/session.service';
import { RealEmpty, blankFilters, message } from '../shared/page';
import { FilterBar, Filters, RiskBadge, StackedBars, StateView } from '../shared/ui';
import { Row } from './students';

@Component({
  selector: 'app-placement-page',
  imports: [RouterLink, FilterBar, StateView, RiskBadge, StackedBars, RealEmpty],
  template: `
    <div class="page-head"><h1>Placement readiness</h1><span class="spacer"></span>
      <button class="btn small" type="button" (click)="load()" [disabled]="loading()">Refresh</button>
      <p class="sub">Years 3–4. Aptitude, coding, mock interviews and skills. A student without assessments is “insufficient data”, not low readiness.</p></div>
    <app-filters [value]="filters()" (changed)="filters.set($event)" [departments]="departments()" [showPeriod]="false" [showRisk]="false" [showSegment]="false" [showSearch]="true" />
    <app-real-empty [show]="!loading() && !all().length" />
    <app-state [loading]="loading() && !all().length" [error]="error()" (retry)="load()" [empty]="!loading() && !all().length" emptyText="No students in years 3–4 match." />
    @if (all().length) {
      <section class="kpis">
        <div class="card kpi"><div class="label">High placement risk</div><div class="value">{{ levels()['high'] || 0 }}</div></div>
        <div class="card kpi"><div class="label">Medium</div><div class="value">{{ levels()['medium'] || 0 }}</div></div>
        <div class="card kpi"><div class="label">Low</div><div class="value">{{ levels()['low'] || 0 }}</div></div>
        <div class="card kpi"><div class="label">Not yet assessed</div><div class="value">{{ levels()['insufficient_data'] || 0 }}</div><div class="note">needs placement data, not training</div></div>
        <div class="card kpi"><div class="label">Strong academics, low placement</div><div class="value">{{ strongLow() }}</div></div>
      </section>
      <section class="card" style="margin:16px 0"><div class="card-head"><h2>Placement risk by department</h2></div>
        <app-stacks [rows]="byDept()" label="Placement risk levels per department" /></section>
      <div class="row" role="group" aria-label="Risk level" style="margin-bottom:10px;gap:6px">
        @for (l of levelOpts; track l[0]) { <button type="button" class="btn small" [class.primary]="level() === l[0]" [attr.aria-pressed]="level() === l[0]" (click)="level.set(l[0])">{{ l[1] }}</button> }
      </div>
      <div class="card" style="padding:0"><div class="table-wrap"><table>
        <thead><tr><th>Student</th><th>Dept · Year</th><th>Placement risk</th><th class="num">Placement readiness</th><th class="num">Skills</th><th>Notes</th></tr></thead>
        <tbody>@for (r of rows(); track r.student_id) {
          <tr><td><a [routerLink]="['/students', r.dataset, r.student_id]">{{ r.name }}</a> <span class="mono muted small">{{ r.student_id }}</span></td>
            <td>{{ r.department }} · Y{{ r.year }}</td><td><app-risk [level]="r.risks?.placement?.level" /></td>
            <td class="num">{{ r.components?.['placement'] ?? '–' }}</td><td class="num">{{ r.components?.['skills'] ?? '–' }}</td>
            <td class="small">@if ((r.segments || []).includes('strong_academics_low_placement')) { Strong academics, low placement readiness }
              @if (r.risks?.placement?.level === 'insufficient_data') { Collect aptitude or coding results first }</td></tr>
        } @empty { <tr><td colspan="6" class="muted">No students at this level.</td></tr> }</tbody></table></div></div>
    }`,
})
export class PlacementPage {
  private api = inject(Api);
  session = inject(Session);
  filters = signal<Filters>(blankFilters());
  level = signal('');
  all = signal<Row[]>([]);
  levels = signal<Record<string, number>>({});
  strongLow = signal(0);
  loading = signal(true);
  error = signal<string | null>(null);
  levelOpts: [string, string][] = [['', 'All'], ['high', '▲ High'], ['medium', '■ Medium'], ['insufficient_data', '◌ Not assessed'], ['low', '● Low']];
  departments = computed(() => Object.keys(this.session.me()?.departments || {}));
  rows = computed(() => {
    const q = this.filters().q.trim().toLowerCase();
    return this.all().filter((r) => (!this.level() || r.risks?.placement?.level === this.level())
      && (!q || r.name?.toLowerCase().includes(q) || r.student_id.toLowerCase().includes(q)));
  });
  byDept = computed(() => {
    const m: Record<string, Record<string, number>> = {};
    for (const r of this.all()) { const l = r.risks?.placement?.level || 'insufficient_data'; (m[r.department] ||= {})[l] = (m[r.department][l] || 0) + 1; }
    return Object.entries(m).sort().map(([label, parts]) => ({ label, parts }));
  });

  constructor() { effect(() => { this.session.dataset(); this.filters().department; this.filters().year; untracked(() => this.load()); }); }

  async load() {
    this.loading.set(true); this.error.set(null);
    const f = this.filters();
    try {
      const r = await this.api.get<{ items: Row[]; levels: Record<string, number>; segment_strong_academics_low_placement: number }>('/placement',
        { dataset: this.session.dataset(), department: f.department, year: f.year });
      this.all.set(r.items); this.levels.set(r.levels); this.strongLow.set(r.segment_strong_academics_low_placement);
    } catch (e) { this.error.set(message(e)); }
    finally { this.loading.set(false); }
  }
}
