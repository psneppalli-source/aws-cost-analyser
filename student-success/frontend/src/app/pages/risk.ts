import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Api } from '../core/api.service';
import { Session } from '../core/session.service';
import { SEGMENTS } from '../shared/labels';
import { RealEmpty, blankFilters, message } from '../shared/page';
import { FilterBar, Filters, RiskBadge, StateView, StatusChip } from '../shared/ui';
import { Row } from './students';

@Component({
  selector: 'app-risk-page',
  imports: [RouterLink, FilterBar, StateView, RiskBadge, StatusChip, RealEmpty],
  template: `
    <div class="page-head"><h1>Academic risk</h1><span class="spacer"></span>
      <button class="btn small" type="button" (click)="load()" [disabled]="loading()">Refresh</button>
      <p class="sub">Rules on CGPA, backlogs, marks, attendance and assignment completion. Thresholds are demonstration assumptions,
        shown with every flag on the student profile. Placement readiness is assessed separately.</p></div>
    <app-filters [value]="filters()" (changed)="filters.set($event)" [departments]="departments()" [periods]="periods()" [showRisk]="false" />
    <div class="row" role="group" aria-label="Risk level" style="margin:-4px 0 14px;gap:6px">
      @for (l of levels; track l[0]) {
        <button type="button" class="btn small" [class.primary]="level() === l[0]" [attr.aria-pressed]="level() === l[0]" (click)="level.set(l[0])">
          {{ l[1] }}@if (l[0]) { ({{ counts()[l[0]] || 0 }}) }</button>
      }
    </div>
    <app-real-empty [show]="!loading() && !all().length" />
    <app-state [loading]="loading() && !all().length" [error]="error()" (retry)="load()" [empty]="!loading() && !rows().length" emptyText="No students at this risk level." />
    @if (rows().length) {
      <div class="card" style="padding:0"><div class="table-wrap"><table>
        <thead><tr><th>Student</th><th>Dept · Year</th><th>Academic risk</th><th class="num">Score</th><th>Status</th><th>Segments</th><th>Mentor</th></tr></thead>
        <tbody>@for (r of rows(); track r.student_id) {
          <tr><td><a [routerLink]="['/students', r.dataset, r.student_id]">{{ r.name }}</a> <span class="mono muted small">{{ r.student_id }}</span></td>
            <td>{{ r.department }} · Y{{ r.year }}</td><td><app-risk [level]="r.risks?.academic?.level" /></td>
            <td class="num">{{ r.score ?? '–' }}</td><td><app-status [status]="r.status" /></td>
            <td class="small">{{ segs(r) }}</td><td class="small">{{ r.mentor_name || '–' }}</td></tr>
        }</tbody></table></div></div>
      <p class="small muted">Open a student to see the triggered rules, observed values, thresholds, periods and suggested interventions.</p>
    }`,
})
export class RiskPage {
  private api = inject(Api);
  session = inject(Session);
  filters = signal<Filters>(blankFilters());
  level = signal('');
  all = signal<Row[]>([]);
  loading = signal(true);
  error = signal<string | null>(null);
  levels: [string, string][] = [['', 'All'], ['high', '▲ High'], ['medium', '■ Medium'], ['insufficient_data', '◌ Insufficient data'], ['low', '● Low']];
  departments = computed(() => Object.keys(this.session.me()?.departments || {}));
  periods = computed(() => this.session.me()?.periods || []);
  counts = computed(() => this.all().reduce((a, r) => { const l = r.risks?.academic?.level || ''; a[l] = (a[l] || 0) + 1; return a; }, {} as Record<string, number>));
  rows = computed(() => {
    const f = this.filters();
    return this.all().filter((r) => (!this.level() || r.risks?.academic?.level === this.level()) && (!f.segment || (r.segments || []).includes(f.segment)));
  });

  constructor() { effect(() => { this.session.dataset(); this.filters().department; this.filters().year; this.filters().period; untracked(() => this.load()); }); }
  segs(r: Row) { return (r.segments || []).map((s) => SEGMENTS[s] || s).join('; ') || '–'; }

  async load() {
    this.loading.set(true); this.error.set(null);
    const f = this.filters();
    try {
      this.all.set((await this.api.get<{ items: Row[] }>('/risk/academic', { dataset: this.session.dataset(), department: f.department, year: f.year, period: f.period })).items);
    } catch (e) { this.error.set(message(e)); }
    finally { this.loading.set(false); }
  }
}
