import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { Api } from '../core/api.service';
import { Session } from '../core/session.service';
import { SEGMENTS, pct } from '../shared/labels';
import { RealEmpty, blankFilters, message } from '../shared/page';
import { FilterBar, Filters, RiskBadge, StateView, StatusChip } from '../shared/ui';

export interface Row {
  student_id: string; dataset: string; name: string; department: string; year: number; period: string;
  score?: number | null; indicative_score?: number | null; status?: string; band?: string | null; coverage?: number;
  risks?: { academic?: { level: string }; placement?: { level: string } }; segments?: string[]; mentor_name?: string;
  components?: Record<string, number>; recalc_status?: string;
}

@Component({
  selector: 'app-students-page',
  imports: [RouterLink, FilterBar, StateView, RiskBadge, StatusChip, RealEmpty],
  template: `
    <div class="page-head"><h1>Students</h1><span class="spacer"></span>
      <label class="row small" style="gap:6px">Sort
        <select [value]="sort()" (change)="sort.set($any($event.target).value)">
          <option value="name">Name</option><option value="student_id">Student ID</option><option value="score">Score</option><option value="department">Department</option>
        </select></label>
      <p class="sub">Only students your role is assigned to are listed. {{ total() }} match.</p></div>
    <app-filters [value]="filters()" (changed)="filters.set($event)" [departments]="departments()" [periods]="periods()" [showSearch]="true" />
    <app-real-empty [show]="!loading() && total() === 0 && !anyFilter()" />
    <app-state [loading]="loading() && !rows().length" [error]="error()" (retry)="load(true)" [empty]="!loading() && !rows().length" emptyText="No students match these filters." />
    @if (rows().length) {
      <div class="card" style="padding:0"><div class="table-wrap"><table>
        <caption class="sr-only">Students with Success Score, status and risks</caption>
        <thead><tr><th scope="col">Student</th><th scope="col">Dept · Year</th><th scope="col" class="num">Score</th><th scope="col">Status</th>
          <th scope="col" class="num">Coverage</th><th scope="col">Academic risk</th><th scope="col">Placement risk</th><th scope="col">Segments</th></tr></thead>
        <tbody>
          @for (r of rows(); track r.student_id) {
            <tr><td><a [routerLink]="['/students', r.dataset, r.student_id]">{{ r.name }}</a><br><span class="muted mono small">{{ r.student_id }}</span></td>
              <td>{{ r.department }} · Y{{ r.year }}</td>
              <td class="num">@if (r.score !== undefined) { {{ r.score ?? '–' }}
                @if (r.score === null && r.indicative_score !== null && r.indicative_score !== undefined) { <br><span class="small muted" title="Calculated from incomplete data; not a Success Score">indicative {{ r.indicative_score }}</span> } } @else { <span class="muted">–</span> }</td>
              <td>@if (r.status) { <app-status [status]="r.status" /> } @if (r.recalc_status === 'stale') { <span class="chip">Recalculating</span> }</td>
              <td class="num">{{ pct(r.coverage) }}</td>
              <td><app-risk [level]="r.risks?.academic?.level" /></td>
              <td><app-risk [level]="r.risks?.placement?.level" /></td>
              <td class="small">@for (s of r.segments || []; track s) { <span class="chip" style="margin:1px">{{ seg(s) }}</span> }</td></tr>
          }
        </tbody></table></div></div>
      @if (next()) { <p style="text-align:center"><button class="btn" type="button" (click)="load(false)" [disabled]="loading()">Show more</button></p> }
    }`,
})
export class StudentsPage {
  private api = inject(Api);
  session = inject(Session);
  pct = pct;
  filters = signal<Filters>(blankFilters());
  sort = signal('name');
  rows = signal<Row[]>([]);
  total = signal(0);
  next = signal<string | null>(null);
  loading = signal(true);
  error = signal<string | null>(null);
  departments = computed(() => Object.keys(this.session.me()?.departments || {}));
  periods = computed(() => this.session.me()?.periods || []);
  anyFilter = computed(() => Object.values(this.filters()).some((v) => !!v));

  constructor() {
    const q = inject(ActivatedRoute).snapshot.queryParamMap;
    this.filters.set(blankFilters({ risk: q.get('risk') || '', segment: q.get('segment') || '', department: q.get('department') || '' }));
    let timer: ReturnType<typeof setTimeout> | undefined;
    effect(() => {
      this.session.dataset(); this.filters(); this.sort();
      clearTimeout(timer);
      timer = setTimeout(() => untracked(() => this.load(true)), 200); // debounce typing in search
    });
  }

  seg(k: string) { return SEGMENTS[k] || k; }

  async load(reset: boolean) {
    this.loading.set(true); this.error.set(null);
    const f = this.filters();
    try {
      const r = await this.api.get<{ items: Row[]; total: number; next_cursor: string | null }>('/students', {
        dataset: this.session.dataset(), department: f.department, year: f.year, period: f.period, risk: f.risk,
        segment: f.segment, q: f.q, sort: this.sort(), limit: 50, cursor: reset ? null : this.next() });
      this.rows.set(reset ? r.items : [...this.rows(), ...r.items]);
      this.total.set(r.total); this.next.set(r.next_cursor);
    } catch (e) { this.error.set(message(e)); }
    finally { this.loading.set(false); }
  }
}
