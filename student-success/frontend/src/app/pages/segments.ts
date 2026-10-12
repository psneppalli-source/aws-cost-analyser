import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Api } from '../core/api.service';
import { Session } from '../core/session.service';
import { RealEmpty, blankFilters, message } from '../shared/page';
import { FilterBar, Filters, StateView } from '../shared/ui';

interface Segment { key: string; label: string; count: number; members: { student_id: string; name: string; department: string; year: number; score: number | null }[]; }

const ABOUT: Record<string, string> = {
  strong_academics_low_placement: 'Good academic standing but weak or declining placement indicators. Candidates for placement training.',
  declining_attendance_results: 'Attendance and marks both fell across recent comparable periods.',
  strong_skills_academic_support: 'Strong technical or communication skills alongside academic risk.',
  improving_after_intervention: 'Score rose after an intervention started. An association, not proof the intervention caused it.',
  consistently_performing_well: 'Strong band in each recent comparable period with no high risk.',
  insufficient_data: 'Not enough recorded data for a Success Score. Collect data before drawing conclusions.',
};

@Component({
  selector: 'app-segments-page',
  imports: [RouterLink, FilterBar, StateView, RealEmpty],
  template: `
    <div class="page-head"><h1>Segments</h1><span class="spacer"></span>
      <button class="btn small" type="button" (click)="load()" [disabled]="loading()">Refresh</button>
      <p class="sub">Transparent rules group students for planning. A student can be in several segments. {{ students() }} students in view.</p></div>
    <app-filters [value]="filters()" (changed)="filters.set($event)" [departments]="departments()" [periods]="periods()" [showRisk]="false" [showSegment]="false" />
    <app-real-empty [show]="!loading() && !students()" />
    <app-state [loading]="loading() && !segs().length" [error]="error()" (retry)="load()" />
    <div class="grid g2">
      @for (s of segs(); track s.key) {
        <section class="card">
          <div class="card-head"><h2>{{ s.label }}</h2><span class="spacer"></span><span class="kpi"><span class="value" style="font-size:26px">{{ s.count }}</span></span></div>
          <p class="small muted">{{ about(s.key) }}</p>
          <div class="meter" role="img" [attr.aria-label]="s.count + ' of ' + students() + ' students'"><span [style.width.%]="students() ? s.count * 100 / students() : 0"></span></div>
          @if (s.count) {
            <details style="margin-top:10px"><summary>Show students</summary>
              <ul class="small">@for (m of s.members; track m.student_id) {
                <li><a [routerLink]="['/students', session.dataset(), m.student_id]">{{ m.name }}</a> · {{ m.department }} Y{{ m.year }} · score {{ m.score ?? '–' }}</li> }</ul>
              <a class="btn small" routerLink="/students" [queryParams]="{ segment: s.key }">Open in student list</a>
            </details>
          }
        </section>
      }
    </div>`,
})
export class SegmentsPage {
  private api = inject(Api);
  session = inject(Session);
  filters = signal<Filters>(blankFilters());
  segs = signal<Segment[]>([]);
  students = signal(0);
  loading = signal(true);
  error = signal<string | null>(null);
  departments = computed(() => Object.keys(this.session.me()?.departments || {}));
  periods = computed(() => this.session.me()?.periods || []);
  about(k: string) { return ABOUT[k] || ''; }

  constructor() { effect(() => { this.session.dataset(); this.filters(); untracked(() => this.load()); }); }

  async load() {
    this.loading.set(true); this.error.set(null);
    const f = this.filters();
    try {
      const r = await this.api.get<{ segments: Segment[]; students: number }>('/segments', { dataset: this.session.dataset(), department: f.department, year: f.year, period: f.period });
      this.segs.set(r.segments); this.students.set(r.students);
    } catch (e) { this.error.set(message(e)); }
    finally { this.loading.set(false); }
  }
}
