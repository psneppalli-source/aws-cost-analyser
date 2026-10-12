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
      <div class="state" role="status" aria-live="polite"><div class="skeleton" style="max-width:420px;margin:0 auto 8px"></div>
        <div class="skeleton" style="max-width:300px;margin:0 auto"></div><span class="sr-only">Loading…</span></div>
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

export interface Bar { label: string; value: number | null; note?: string; tone?: 'navy' | 'teal' | 'high' | 'medium' | 'low' | 'na'; }
const TONE: Record<string, string> = { navy: '#2a4a73', teal: '#0f8a8a', high: '#b3261e', medium: '#c98a12', low: '#2e8a50', na: '#9aa8b9' };

/** Vertical bar chart drawn in SVG, with value labels, an accessible name and a data table. */
@Component({
  selector: 'app-bars',
  template: `
    <figure class="chart" style="margin:0">
      <svg [attr.viewBox]="'0 0 ' + W + ' ' + H" role="img" [attr.aria-label]="label()">
        @for (t of ticks(); track t) {
          <line class="grid-line" [attr.x1]="40" [attr.x2]="W - 8" [attr.y1]="y(t)" [attr.y2]="y(t)" />
          <text [attr.x]="34" [attr.y]="y(t) + 4" text-anchor="end">{{ t }}{{ unit() }}</text>
        }
        @for (b of data(); track b.label; let i = $index) {
          @if (b.value !== null) {
            <rect [attr.x]="x(i)" [attr.y]="y(b.value)" [attr.width]="bw()" [attr.height]="H - 26 - y(b.value)" rx="3"
                  [attr.fill]="tone(b)"><title>{{ b.label }}: {{ b.value }}{{ unit() }}{{ b.note ? ' (' + b.note + ')' : '' }}</title></rect>
            <text class="val" [attr.x]="x(i) + bw() / 2" [attr.y]="y(b.value) - 4" text-anchor="middle">{{ fmt(b.value) }}</text>
          } @else {
            <text [attr.x]="x(i) + bw() / 2" [attr.y]="H - 32" text-anchor="middle">n/a</text>
          }
          <text [attr.x]="x(i) + bw() / 2" [attr.y]="H - 8" text-anchor="middle">{{ b.label }}</text>
        }
      </svg>
      <details class="data-table"><summary>Show as table</summary>
        <table><thead><tr><th>{{ xName() }}</th><th class="num">{{ yName() }}</th></tr></thead>
          <tbody>@for (b of data(); track b.label) { <tr><td>{{ b.label }}</td><td class="num">{{ b.value ?? 'n/a' }}{{ b.value !== null ? unit() : '' }}</td></tr> }</tbody>
        </table></details>
    </figure>`,
})
export class BarChart {
  data = input<Bar[]>([]);
  label = input('Bar chart');
  unit = input('');
  max = input<number | null>(null);
  xName = input('Category');
  yName = input('Value');
  readonly W = 560;
  readonly H = 220;
  top = computed(() => this.max() ?? Math.max(1, ...this.data().map((d) => d.value ?? 0)) * 1.15);
  ticks = computed(() => { const t = this.top(); const s = t / 4; return [0, 1, 2, 3, 4].map((k) => Math.round(k * s)); });
  bw = computed(() => Math.min(48, (this.W - 60) / Math.max(1, this.data().length) - 10));
  x(i: number) { const slot = (this.W - 56) / Math.max(1, this.data().length); return 48 + i * slot + (slot - this.bw()) / 2; }
  y(v: number) { return 10 + (1 - v / this.top()) * (this.H - 36); }
  tone(b: Bar) { return TONE[b.tone || 'teal']; }
  fmt(v: number) { return Number.isInteger(v) ? v : v.toFixed(1); }
}

export interface Stack { label: string; parts: Record<string, number>; }
const LEVELS = [
  { key: 'high', label: '▲ High', color: '#b3261e' }, { key: 'medium', label: '■ Medium', color: '#c98a12' },
  { key: 'low', label: '● Low', color: '#2e8a50' }, { key: 'insufficient_data', label: '◌ Insufficient data', color: '#9aa8b9' },
];

/** Horizontal 100% stacked bars for risk levels, with legend and data table. */
@Component({
  selector: 'app-stacks',
  template: `
    <figure class="chart" style="margin:0">
      <svg [attr.viewBox]="'0 0 560 ' + (rows().length * 34 + 10)" role="img" [attr.aria-label]="label()">
        @for (r of rows(); track r.label; let i = $index) {
          <text [attr.x]="60" [attr.y]="i * 34 + 22" text-anchor="end">{{ r.label }}</text>
          @for (s of segs(r); track s.key) {
            <rect [attr.x]="70 + s.x" [attr.y]="i * 34 + 8" [attr.width]="s.w" height="20" [attr.fill]="s.color">
              <title>{{ r.label }} · {{ s.label }}: {{ s.n }} ({{ s.pct }}%)</title></rect>
            @if (s.w > 34) { <text [attr.x]="70 + s.x + s.w / 2" [attr.y]="i * 34 + 22" text-anchor="middle" style="fill:#fff;font-weight:600">{{ s.pct }}%</text> }
          }
        }
      </svg>
      <div class="legend">@for (l of levels; track l.key) { <span><i [style.background]="l.color"></i>{{ l.label }}</span> }</div>
      <details class="data-table"><summary>Show as table</summary>
        <table><thead><tr><th>Group</th>@for (l of levels; track l.key) { <th class="num">{{ l.label }}</th> }</tr></thead>
          <tbody>@for (r of rows(); track r.label) { <tr><td>{{ r.label }}</td>@for (l of levels; track l.key) { <td class="num">{{ r.parts[l.key] || 0 }}</td> }</tr> }</tbody>
        </table></details>
    </figure>`,
})
export class StackedBars {
  rows = input<Stack[]>([]);
  label = input('Risk levels');
  levels = LEVELS;
  segs(r: Stack) {
    const total = LEVELS.reduce((a, l) => a + (r.parts[l.key] || 0), 0) || 1;
    let x = 0;
    return LEVELS.map((l) => {
      const n = r.parts[l.key] || 0;
      const w = (n / total) * 480;
      const seg = { key: l.key, label: l.label, color: l.color, n, pct: Math.round((n / total) * 100), x, w };
      x += w;
      return seg;
    }).filter((s) => s.n > 0);
  }
}

export interface Series { name: string; values: (number | null)[]; color?: string; }

/** Line chart for trends across reporting periods; gaps are shown as gaps, not zeros. */
@Component({
  selector: 'app-lines',
  template: `
    <figure class="chart" style="margin:0">
      <svg [attr.viewBox]="'0 0 560 ' + H" role="img" [attr.aria-label]="label()">
        @for (t of [0, 25, 50, 75, 100]; track t) {
          <line class="grid-line" x1="40" x2="548" [attr.y1]="y(t)" [attr.y2]="y(t)" /><text x="34" [attr.y]="y(t) + 4" text-anchor="end">{{ t }}</text>
        }
        @if (ref() !== null) { <line x1="40" x2="548" [attr.y1]="y(ref()!)" [attr.y2]="y(ref()!)" stroke="#b3261e" stroke-dasharray="4 3" /> }
        @for (s of series(); track s.name) {
          @for (seg of segments(s); track $index) { <path [attr.d]="seg" fill="none" [attr.stroke]="s.color || '#0f8a8a'" stroke-width="2.5" stroke-linejoin="round" /> }
          @for (v of s.values; track $index; let i = $index) {
            @if (v !== null) { <circle [attr.cx]="x(i)" [attr.cy]="y(v)" r="4" [attr.fill]="s.color || '#0f8a8a'" stroke="#fff" stroke-width="1.5"><title>{{ s.name }} · {{ labels()[i] }}: {{ v }}</title></circle> }
          }
        }
        @for (l of labels(); track l; let i = $index) { <text [attr.x]="x(i)" [attr.y]="H - 6" text-anchor="middle">{{ l }}</text> }
      </svg>
      @if (series().length > 1) { <div class="legend">@for (s of series(); track s.name) { <span><i [style.background]="s.color || '#0f8a8a'"></i>{{ s.name }}</span> }</div> }
      <details class="data-table"><summary>Show as table</summary>
        <table><thead><tr><th>Series</th>@for (l of labels(); track l) { <th class="num">{{ l }}</th> }</tr></thead>
          <tbody>@for (s of series(); track s.name) { <tr><td>{{ s.name }}</td>@for (v of s.values; track $index) { <td class="num">{{ v ?? '–' }}</td> }</tr> }</tbody>
        </table></details>
    </figure>`,
})
export class LineChart {
  series = input<Series[]>([]);
  labels = input<string[]>([]);
  label = input('Trend');
  ref = input<number | null>(null);
  readonly H = 210;
  x(i: number) { const n = Math.max(1, this.labels().length - 1); return 56 + (i / n) * 480; }
  y(v: number) { return 10 + (1 - v / 100) * (this.H - 36); }
  segments(s: Series): string[] {
    const out: string[] = [];
    let cur: string[] = [];
    s.values.forEach((v, i) => {
      if (v === null) { if (cur.length > 1) out.push('M' + cur.join('L')); cur = []; return; }
      cur.push(`${this.x(i)},${this.y(v)}`);
    });
    if (cur.length > 1) out.push('M' + cur.join('L'));
    return out;
  }
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
