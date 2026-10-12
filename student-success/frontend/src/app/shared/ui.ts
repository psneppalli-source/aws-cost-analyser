import { Component, computed, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';

const LEVEL_TEXT: Record<string, [string, string]> = {
  high: ['▲', 'High'], medium: ['■', 'Medium'], low: ['●', 'Low'],
  insufficient_data: ['◌', 'Insufficient data'], not_applicable: ['–', 'Not applicable'],
};

/** Risk level as symbol + text + colour (never colour alone). */
@Component({
  selector: 'app-risk',
  template: `<span class="badge" [class]="'badge ' + (level() || 'na')"><span aria-hidden="true">{{ sym() }}</span>{{ prefix() }}{{ text() }}</span>`,
})
export class RiskBadge {
  level = input<string | null | undefined>();
  prefix = input<string>('');
  sym = computed(() => (LEVEL_TEXT[this.level() || ''] || ['', '–'])[0]);
  text = computed(() => (LEVEL_TEXT[this.level() || ''] || ['', '–'])[1]);
}

@Component({
  selector: 'app-status',
  template: `
    @switch (status()) {
      @case ('complete') { <span class="chip teal">Complete</span> }
      @case ('provisional') { <span class="chip" title="Some components are missing; weights were re-normalised">Provisional</span> }
      @case ('insufficient_data') { <span class="badge insufficient_data">◌ Insufficient data</span> }
      @default { <span class="chip">{{ status() || 'Not calculated' }}</span> }
    }`,
})
export class StatusChip {
  status = input<string | null | undefined>();
}

/** Loading, empty and error states with one component. */
@Component({
  selector: 'app-state',
  template: `
    @if (loading()) {
      <div class="state loading-state" role="status" aria-live="polite">
        <div class="sk-row"><div class="sk-card"></div><div class="sk-card"></div><div class="sk-card"></div><div class="sk-card"></div></div>
        <div class="sk-panel"><div class="skeleton" style="width:40%"></div><div class="skeleton"></div><div class="skeleton" style="width:85%"></div><div class="skeleton" style="width:70%"></div></div>
        <span class="sr-only">Loading…</span></div>
    } @else if (error()) {
      <div class="state error" role="alert">{{ error() }} <button class="btn small" type="button" (click)="retry.emit()">Try again</button></div>
    } @else if (empty()) {
      <div class="state">{{ emptyText() }}</div>
    }`,
})
export class StateView {
  loading = input(false);
  error = input<string | null>(null);
  empty = input(false);
  emptyText = input('Nothing to show yet.');
  retry = output<void>();
}

export interface Filters { department: string; year: string; period: string; risk: string; segment: string; q: string; }

/** Shared filter bar (department, year, reporting period, risk, segment, search). */
@Component({
  selector: 'app-filters',
  imports: [FormsModule],
  template: `
    <form class="filters" role="search" (submit)="$event.preventDefault()">
      <label>Department<select name="d" [ngModel]="value().department" (ngModelChange)="set('department', $event)">
        <option value="">All</option>@for (d of departments(); track d) { <option [value]="d">{{ d }}</option> }</select></label>
      <label>Year<select name="y" [ngModel]="value().year" (ngModelChange)="set('year', $event)">
        <option value="">All</option>@for (y of [1, 2, 3, 4]; track y) { <option [value]="'' + y">Year {{ y }}</option> }</select></label>
      @if (showPeriod()) {
        <label>Reporting period<select name="p" [ngModel]="value().period" (ngModelChange)="set('period', $event)">
          <option value="">Latest</option>@for (p of periods(); track p) { <option [value]="p">{{ p }}</option> }</select></label>
      }
      @if (showRisk()) {
        <label>Risk<select name="r" [ngModel]="value().risk" (ngModelChange)="set('risk', $event)">
          <option value="">Any</option>
          <option value="academic:high">Academic: high</option><option value="academic:medium">Academic: medium</option>
          <option value="academic:insufficient_data">Academic: insufficient data</option>
          <option value="placement:high">Placement: high</option><option value="placement:medium">Placement: medium</option>
          <option value="placement:insufficient_data">Placement: not assessed</option></select></label>
      }
      @if (showSegment()) {
        <label>Segment<select name="s" [ngModel]="value().segment" (ngModelChange)="set('segment', $event)">
          <option value="">Any</option>@for (s of segments; track s[0]) { <option [value]="s[0]">{{ s[1] }}</option> }</select></label>
      }
      @if (showSearch()) {
        <label>Search<input name="q" type="search" placeholder="Name or student ID" [ngModel]="value().q" (ngModelChange)="set('q', $event)"></label>
      }
    </form>`,
})
export class FilterBar {
  value = input.required<Filters>();
  departments = input<string[]>([]);
  periods = input<string[]>([]);
  showPeriod = input(true);
  showRisk = input(true);
  showSegment = input(true);
  showSearch = input(false);
  changed = output<Filters>();
  segments: [string, string][] = [
    ['strong_academics_low_placement', 'Strong academics, low placement readiness'],
    ['declining_attendance_results', 'Declining attendance and results'],
    ['strong_skills_academic_support', 'Strong skills, academic support required'],
    ['improving_after_intervention', 'Improving after intervention'],
    ['consistently_performing_well', 'Consistently performing well'],
    ['insufficient_data', 'Insufficient data'],
  ];
  set(k: keyof Filters, v: string) { this.changed.emit({ ...this.value(), [k]: v ?? '' }); }
}
