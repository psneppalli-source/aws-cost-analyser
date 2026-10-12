import { Component, DestroyRef, ElementRef, afterNextRender, computed, inject, input, output, signal } from '@angular/core';

/**
 * Chart library. Rules (see docs/architecture.md → charts):
 *  - categorical hues in a fixed order, by entity (departments keep their colour on every chart);
 *  - one hue light→dark for magnitude; status colours only for states, always with a text label;
 *  - thin marks (bars ≤ 24px, 4px rounded data end), 2px lines, hairline grid, 2px surface gaps/rings;
 *  - every chart has a hover/focus tooltip, a legend when it has 2+ series, and a table view.
 * The palette was validated with the dataviz validator (light surface; first three slots pass all-pairs).
 */
export const SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'];
export const DEPT_ORDER = ['CSE', 'ECE', 'MECH'];
export const deptColor = (d: string) => SERIES[Math.max(0, DEPT_ORDER.indexOf(d)) % SERIES.length];
export const STATUS = { good: '#0ca30c', warning: '#fab219', serious: '#ec835a', critical: '#d03b3b', neutral: '#c3c2b7' };
const SEQ = ['#cde2fb', '#b7d3f6', '#9ec5f4', '#86b6ef', '#6da7ec', '#5598e7', '#3987e5', '#2a78d6', '#256abf', '#1c5cab', '#184f95', '#104281', '#0d366b'];
const INK = '#0b0b0b';

export function niceMax(v: number): number {
  if (!(v > 0)) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  const m = v / p;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * p;
}
const fmt = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? '–' : Number.isInteger(v) ? String(v) : v.toFixed(d));
/** Rounded data-end bar path: 4px radius at the value end, square at the baseline. */
function barV(x: number, y: number, w: number, base: number): string {
  const h = base - y;
  if (h <= 0) return '';
  const r = Math.min(4, h, w / 2);
  return `M${x},${base}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${base}Z`;
}
function barH(x0: number, y: number, len: number, t: number): string {
  if (len <= 0) return '';
  const r = Math.min(4, len, t / 2);
  const x1 = x0 + len;
  return `M${x0},${y}H${x1 - r}Q${x1},${y} ${x1},${y + r}V${y + t - r}Q${x1},${y + t} ${x1 - r},${y + t}H${x0}Z`;
}

export interface TipRow { label: string; value: string; color?: string; }
export interface Tip { x: number; y: number; title: string; rows: TipRow[]; }

/** Shared behaviour: SVG width tracks the rendered width (1 unit = 1 CSS px) and one tooltip per chart. */
abstract class Sized {
  protected host = inject(ElementRef<HTMLElement>);
  readonly w = signal(560);
  readonly tip = signal<Tip | null>(null);
  constructor() {
    const ro = new ResizeObserver((e) => this.w.set(Math.max(240, Math.round(e[0].contentRect.width))));
    afterNextRender(() => ro.observe(this.host.nativeElement));
    inject(DestroyRef).onDestroy(() => ro.disconnect());
  }
  show(ev: Event, title: string, rows: TipRow[]) {
    const box = (this.host.nativeElement as HTMLElement).getBoundingClientRect();
    const pe = ev as PointerEvent;
    let x: number, y: number;
    if (pe.clientX) { x = pe.clientX - box.left; y = pe.clientY - box.top; }
    else { const r = (ev.target as Element).getBoundingClientRect(); x = r.left + r.width / 2 - box.left; y = r.top - box.top; }
    this.tip.set({ x, y, title, rows });
  }
  hide() { this.tip.set(null); }
}

@Component({
  selector: 'app-tip',
  template: `@if (tip(); as t) {
    <div class="viz-tip" role="status" [style.left.px]="left(t)" [style.top.px]="t.y + 14">
      <div class="viz-tip-title">{{ t.title }}</div>
      @for (r of t.rows; track $index) {
        <div class="viz-tip-row">@if (r.color) { <i [style.background]="r.color"></i> }<strong>{{ r.value }}</strong><span>{{ r.label }}</span></div>
      }
    </div>
  }`,
})
export class TipView {
  tip = input<Tip | null>(null);
  width = input(560);
  left(t: Tip) { return Math.max(0, Math.min(t.x + 12, this.width() - 210)); }
}

// ------------------------------------------------------------------ columns (single series, e.g. a histogram)
export interface Col { label: string; value: number; note?: string; }
@Component({
  selector: 'app-columns',
  imports: [TipView],
  host: { class: 'viz' },
  template: `
    <svg [attr.width]="w()" [attr.height]="H" role="img" [attr.aria-label]="label()">
      @for (t of ticks(); track t) {
        <line class="viz-grid" [attr.x1]="L" [attr.x2]="w() - 8" [attr.y1]="y(t)" [attr.y2]="y(t)" />
        <text class="viz-axis" [attr.x]="L - 6" [attr.y]="y(t) + 4" text-anchor="end">{{ t }}</text>
      }
      @for (d of data(); track d.label; let i = $index) {
        <g class="viz-hit" tabindex="0" [attr.aria-label]="d.label + ': ' + d.value + unit()"
           (pointermove)="show($event, d.label, [{ label: yName(), value: d.value + unit() }])" (pointerleave)="hide()"
           (focus)="show($event, d.label, [{ label: yName(), value: d.value + unit() }])" (blur)="hide()">
          <rect [attr.x]="L + i * slot()" y="0" [attr.width]="slot()" [attr.height]="base" fill="transparent" />
          <path [attr.d]="bar(i, d.value)" [attr.fill]="color()" />
          @if (d.value > 0 && showValues()) { <text class="viz-val" [attr.x]="cx(i)" [attr.y]="y(d.value) - 6" text-anchor="middle">{{ d.value }}</text> }
        </g>
        @if (i % every() === 0) { <text class="viz-axis" [attr.x]="cx(i)" [attr.y]="H - 8" text-anchor="middle">{{ d.label }}</text> }
      }
      <line class="viz-base" [attr.x1]="L" [attr.x2]="w() - 8" [attr.y1]="base" [attr.y2]="base" />
    </svg>
    <app-tip [tip]="tip()" [width]="w()" />
    <details class="data-table"><summary>Show as table</summary>
      <table><thead><tr><th>{{ xName() }}</th><th class="num">{{ yName() }}</th></tr></thead>
        <tbody>@for (d of data(); track d.label) { <tr><td>{{ d.label }}</td><td class="num">{{ d.value }}{{ unit() }}</td></tr> }</tbody></table></details>`,
})
export class Columns extends Sized {
  data = input<Col[]>([]);
  label = input('Column chart');
  xName = input('Category');
  yName = input('Value');
  unit = input('');
  color = input(SERIES[0]);
  showValues = input(true);
  readonly H = 230; readonly L = 34; readonly base = 230 - 30;
  top = computed(() => niceMax(Math.max(...this.data().map((d) => d.value), 1) * 1.1));
  ticks = computed(() => [0, 0.25, 0.5, 0.75, 1].map((k) => Math.round(k * this.top())));
  slot = computed(() => (this.w() - this.L - 8) / Math.max(1, this.data().length));
  bw = computed(() => Math.min(24, this.slot() * 0.6));
  every = computed(() => Math.max(1, Math.ceil(this.data().length * 46 / Math.max(1, this.w() - this.L))));
  y(v: number) { return 14 + (1 - v / this.top()) * (this.base - 14); }
  cx(i: number) { return this.L + i * this.slot() + this.slot() / 2; }
  bar(i: number, v: number) { return barV(this.cx(i) - this.bw() / 2, this.y(v), this.bw(), this.base); }
}

// ------------------------------------------------------------------ horizontal bars (value at the tip)
export interface HBar { label: string; value: number | null; note?: string; color?: string; }
@Component({
  selector: 'app-hbars',
  imports: [TipView],
  host: { class: 'viz' },
  template: `
    <svg [attr.width]="w()" [attr.height]="data().length * ROW + 8" role="img" [attr.aria-label]="label()">
      @for (d of data(); track d.label; let i = $index) {
        <g class="viz-hit" tabindex="0" [attr.aria-label]="d.label + ': ' + f(d.value)"
           (pointermove)="show($event, d.label, row(d))" (pointerleave)="hide()" (focus)="show($event, d.label, row(d))" (blur)="hide()">
          <rect x="0" [attr.y]="i * ROW" [attr.width]="w()" [attr.height]="ROW" fill="transparent" />
          <text class="viz-label" x="0" [attr.y]="i * ROW + ROW / 2 + 4">{{ fit(d.label) }}</text>
          <rect [attr.x]="LBL" [attr.y]="i * ROW + (ROW - T) / 2" [attr.width]="track()" [attr.height]="T" rx="4" class="viz-track" />
          @if (d.value !== null) {
            <path [attr.d]="bar(i, d.value)" [attr.fill]="d.color || color()" />
            <text class="viz-val" [attr.x]="LBL + len(d.value) + 6" [attr.y]="i * ROW + ROW / 2 + 4">{{ f(d.value) }}{{ unit() }}</text>
          } @else { <text class="viz-axis" [attr.x]="LBL + 4" [attr.y]="i * ROW + ROW / 2 + 4">no data</text> }
        </g>
      }
    </svg>
    <app-tip [tip]="tip()" [width]="w()" />
    <details class="data-table"><summary>Show as table</summary>
      <table><tbody>@for (d of data(); track d.label) { <tr><td>{{ d.label }}</td><td class="num">{{ f(d.value) }}{{ d.value !== null ? unit() : '' }}</td><td class="small muted">{{ d.note }}</td></tr> }</tbody></table></details>`,
})
export class HBars extends Sized {
  data = input<HBar[]>([]);
  label = input('Bar chart');
  max = input<number | null>(null);
  unit = input('');
  color = input(SERIES[0]);
  readonly ROW = 34; readonly T = 14; readonly LBL = 150;
  top = computed(() => this.max() ?? niceMax(Math.max(...this.data().map((d) => d.value ?? 0), 1)));
  track = computed(() => Math.max(40, this.w() - this.LBL - 48));
  len(v: number) { return (Math.max(0, v) / this.top()) * this.track(); }
  bar(i: number, v: number) { return barH(this.LBL, i * this.ROW + (this.ROW - this.T) / 2, this.len(v), this.T); }
  f(v: number | null) { return fmt(v); }
  /** Labels never run under the bars: shorten to the label column (the full text is in the tooltip and table). */
  fit(s: string) { const max = Math.floor((this.LBL - 10) / 6.6); return s.length > max ? s.slice(0, max - 1) + '…' : s; }
  row(d: HBar): TipRow[] { return [{ label: d.note || (this.fit(d.label) !== d.label ? d.label : ''), value: `${this.f(d.value)}${d.value !== null ? this.unit() : ''}` }]; }
}

// ------------------------------------------------------------------ multi-line with crosshair
export interface Line { name: string; values: (number | null)[]; color: string; }
@Component({
  selector: 'app-multiline',
  imports: [TipView],
  host: { class: 'viz' },
  template: `
    @if (series().length > 1) {
      <div class="viz-legend">@for (s of series(); track s.name) { <span><i class="line" [style.background]="s.color"></i>{{ s.name }}</span> }</div>
    }
    <svg [attr.width]="w()" [attr.height]="H" role="img" [attr.aria-label]="label()">
      @for (t of ticks(); track t) {
        <line class="viz-grid" [attr.x1]="L" [attr.x2]="right()" [attr.y1]="y(t)" [attr.y2]="y(t)" />
        <text class="viz-axis" [attr.x]="L - 6" [attr.y]="y(t) + 4" text-anchor="end">{{ t }}</text>
      }
      @if (ref() !== null) { <line class="viz-ref" [attr.x1]="L" [attr.x2]="right()" [attr.y1]="y(ref()!)" [attr.y2]="y(ref()!)" />
        <text class="viz-axis" [attr.x]="L + 18" [attr.y]="y(ref()!) - 5">{{ refLabel() }}</text> }
      @for (l of labels(); track l; let i = $index) { <text class="viz-axis" [attr.x]="x(i)" [attr.y]="H - 8" text-anchor="middle">{{ short(l) }}</text> }
      @if (hover() !== null) { <line class="viz-cross" [attr.x1]="x(hover()!)" [attr.x2]="x(hover()!)" y1="10" [attr.y2]="base" /> }
      @for (s of series(); track s.name) {
        @for (seg of segs(s); track $index) { <path [attr.d]="seg" fill="none" [attr.stroke]="s.color" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" /> }
        @for (v of s.values; track $index; let i = $index) {
          @if (v !== null && (isolated(s, i) || hover() === i || i === lastIdx(s))) {
            <circle [attr.cx]="x(i)" [attr.cy]="y(v)" r="4" [attr.fill]="s.color" class="viz-ring" />
          }
        }
        @if (endLabels() && lastIdx(s) >= 0) {
          <text class="viz-end" [attr.x]="x(lastIdx(s)) + 8" [attr.y]="endY(s) + 4">{{ s.name }} {{ f(s.values[lastIdx(s)]) }}</text>
        }
      }
      <rect [attr.x]="L" y="0" [attr.width]="right() - L" [attr.height]="base" fill="transparent" tabindex="0" class="viz-hit"
            [attr.aria-label]="label() + ' — use the table view for values'"
            (pointermove)="move($event)" (pointerleave)="hover.set(null); hide()" (focus)="focusAt(labels().length - 1, $event)" (blur)="hover.set(null); hide()" />
    </svg>
    <app-tip [tip]="tip()" [width]="w()" />
    <details class="data-table"><summary>Show as table</summary>
      <table><thead><tr><th>{{ seriesName() }}</th>@for (l of labels(); track l) { <th class="num">{{ l }}</th> }</tr></thead>
        <tbody>@for (s of series(); track s.name) { <tr><td>{{ s.name }}</td>@for (v of s.values; track $index) { <td class="num">{{ f(v) }}</td> }</tr> }</tbody></table></details>`,
})
export class MultiLine extends Sized {
  series = input<Line[]>([]);
  labels = input<string[]>([]);
  label = input('Trend');
  seriesName = input('Series');
  yMax = input(100);
  ref = input<number | null>(null);
  refLabel = input('');
  readonly H = 240; readonly L = 34; readonly base = 240 - 30;
  hover = signal<number | null>(null);
  endLabels = computed(() => {
    const ends = this.series().map((s) => this.endY(s)).sort((a, b) => a - b);
    return this.w() > 420 && ends.every((v, i) => i === 0 || v - ends[i - 1] >= 14);
  });
  right = computed(() => this.w() - (this.endLabels() ? 96 : 12));
  ticks = computed(() => [0, 0.25, 0.5, 0.75, 1].map((k) => Math.round(k * this.yMax())));
  x(i: number) { const n = Math.max(1, this.labels().length - 1); return this.L + 14 + (i / n) * (this.right() - this.L - 28); }
  y(v: number) { return 12 + (1 - v / this.yMax()) * (this.base - 12); }
  f(v: number | null | undefined) { return fmt(v); }
  short(l: string) { return l.length === 7 && l[4] === '-' ? new Date(l + '-01').toLocaleString(undefined, { month: 'short' }) + ' ' + l.slice(2, 4) : l; }
  lastIdx(s: Line) { for (let i = s.values.length - 1; i >= 0; i--) if (s.values[i] !== null) return i; return -1; }
  endY(s: Line) { const i = this.lastIdx(s); return i < 0 ? 0 : this.y(s.values[i]!); }
  isolated(s: Line, i: number) { return (i === 0 || s.values[i - 1] === null) && (i === s.values.length - 1 || s.values[i + 1] === null); }
  segs(s: Line) {
    const out: string[] = []; let cur: string[] = [];
    s.values.forEach((v, i) => { if (v === null) { if (cur.length > 1) out.push('M' + cur.join('L')); cur = []; } else cur.push(`${this.x(i)},${this.y(v)}`); });
    if (cur.length > 1) out.push('M' + cur.join('L'));
    return out;
  }
  move(ev: PointerEvent) {
    const box = (this.host.nativeElement as HTMLElement).getBoundingClientRect();
    const px = ev.clientX - box.left; const n = this.labels().length;
    let best = 0;
    for (let i = 1; i < n; i++) if (Math.abs(this.x(i) - px) < Math.abs(this.x(best) - px)) best = i;
    this.focusAt(best, ev);
  }
  focusAt(i: number, ev: Event) {
    this.hover.set(i);
    this.show(ev, this.labels()[i], this.series().map((s) => ({ label: s.name, value: this.f(s.values[i]), color: s.color })));
  }
}

// ------------------------------------------------------------------ heatmap (one hue, light → dark)
@Component({
  selector: 'app-heatmap',
  imports: [TipView],
  host: { class: 'viz' },
  template: `
    @if (colTitle()) { <div class="viz-legend" style="justify-content:space-between;margin-bottom:2px"><span>{{ rowTitle() }}</span><span>{{ colTitle() }}</span></div> }
    <svg [attr.width]="w()" [attr.height]="rows().length * ch() + 30" role="img" [attr.aria-label]="label()">
      @for (c of cols(); track c; let j = $index) { <text class="viz-axis" [attr.x]="LBL + j * cw() + cw() / 2" y="14" text-anchor="middle">{{ c }}</text> }
      @for (r of rows(); track r; let i = $index) {
        <text class="viz-label" x="0" [attr.y]="22 + i * ch() + ch() / 2 + 4">{{ r }}</text>
        @for (c of cols(); track c; let j = $index) {
          <g class="viz-hit" tabindex="0" [attr.aria-label]="r + ', ' + c + ': ' + f(values()[i][j])"
             (pointermove)="show($event, r + ' · ' + c, [{ label: valueName(), value: f(values()[i][j]) }])" (pointerleave)="hide()"
             (focus)="show($event, r + ' · ' + c, [{ label: valueName(), value: f(values()[i][j]) }])" (blur)="hide()">
            <rect [attr.x]="LBL + j * cw() + 1" [attr.y]="22 + i * ch() + 1" [attr.width]="cw() - 2" [attr.height]="ch() - 2" rx="4"
                  [attr.fill]="fill(values()[i][j])" />
            <text [attr.x]="LBL + j * cw() + cw() / 2" [attr.y]="22 + i * ch() + ch() / 2 + 4" text-anchor="middle" class="viz-cell"
                  [attr.fill]="ink(values()[i][j])">{{ f(values()[i][j]) }}</text>
          </g>
        }
      }
    </svg>
    <div class="viz-scale"><span>{{ minLabel() }}</span><i></i><span>{{ maxLabel() }}</span></div>
    <app-tip [tip]="tip()" [width]="w()" />
    <details class="data-table"><summary>Show as table</summary>
      <table><thead><tr><th></th>@for (c of cols(); track c) { <th class="num">{{ c }}</th> }</tr></thead>
        <tbody>@for (r of rows(); track r; let i = $index) { <tr><td>{{ r }}</td>@for (c of cols(); track c; let j = $index) { <td class="num">{{ f(values()[i][j]) }}</td> }</tr> }</tbody></table></details>`,
})
export class Heatmap extends Sized {
  rows = input<string[]>([]);
  cols = input<string[]>([]);
  values = input<(number | null)[][]>([]);
  max = input<number | null>(null);
  label = input('Heatmap');
  valueName = input('Value');
  minLabel = input('Low');
  maxLabel = input('High');
  rowTitle = input('');
  colTitle = input('');
  readonly LBL = 96;
  cw = computed(() => (this.w() - this.LBL) / Math.max(1, this.cols().length));
  ch = computed(() => 40);
  top = computed(() => this.max() ?? Math.max(1, ...this.values().flat().map((v) => v ?? 0)));
  step(v: number) { return Math.min(SEQ.length - 1, Math.round((v / this.top()) * (SEQ.length - 1))); }
  fill(v: number | null) { return v === null ? '#f0efec' : SEQ[this.step(v)]; }
  ink(v: number | null) { return v !== null && this.step(v) >= 7 ? '#ffffff' : INK; }
  f(v: number | null) { return fmt(v, 0); }
}

// ------------------------------------------------------------------ scatter (≤ 3 groups, ringed dots, large hit areas)
export interface Pt { id: string; label: string; group: string; x: number; y: number; note?: string; }
@Component({
  selector: 'app-scatter',
  imports: [TipView],
  host: { class: 'viz' },
  template: `
    <div class="viz-legend">@for (g of groups(); track g) { <span><i [style.background]="color(g)"></i>{{ g }}</span> }</div>
    <svg [attr.width]="w()" [attr.height]="H" role="img" [attr.aria-label]="label()">
      @for (t of [0, 25, 50, 75, 100]; track t) {
        <line class="viz-grid" [attr.x1]="L" [attr.x2]="w() - 10" [attr.y1]="y(t)" [attr.y2]="y(t)" />
        <text class="viz-axis" [attr.x]="L - 6" [attr.y]="y(t) + 4" text-anchor="end">{{ t }}</text>
        <text class="viz-axis" [attr.x]="x(t)" [attr.y]="base + 16" text-anchor="middle">{{ t }}</text>
      }
      <text class="viz-axis" [attr.x]="w() - 10" [attr.y]="base + 30" text-anchor="end">{{ xName() }} →</text>
      <text class="viz-axis" [attr.x]="L" y="10">↑ {{ yName() }}</text>
      @for (p of points(); track p.id) {
        <g class="viz-hit" tabindex="0" [attr.aria-label]="p.label + ': ' + xName() + ' ' + p.x + ', ' + yName() + ' ' + p.y"
           (pointerenter)="show($event, p.label, rows(p))" (pointerleave)="hide()" (focus)="show($event, p.label, rows(p))" (blur)="hide()"
           (click)="pick.emit(p.id)" (keydown.enter)="pick.emit(p.id)">
          <circle [attr.cx]="x(p.x)" [attr.cy]="y(p.y)" r="12" fill="transparent" />
          <circle [attr.cx]="x(p.x)" [attr.cy]="y(p.y)" r="4.5" [attr.fill]="color(p.group)" class="viz-ring" />
        </g>
      }
    </svg>
    <app-tip [tip]="tip()" [width]="w()" />
    <details class="data-table"><summary>Show as table</summary>
      <table><thead><tr><th>Student</th><th>Group</th><th class="num">{{ xName() }}</th><th class="num">{{ yName() }}</th></tr></thead>
        <tbody>@for (p of points(); track p.id) { <tr><td>{{ p.label }}</td><td>{{ p.group }}</td><td class="num">{{ p.x }}</td><td class="num">{{ p.y }}</td></tr> }</tbody></table></details>`,
})
export class Scatter extends Sized {
  points = input<Pt[]>([]);
  label = input('Scatter plot');
  xName = input('x');
  yName = input('y');
  pick = output<string>();
  readonly H = 300; readonly L = 34; readonly base = 300 - 40;
  groups = computed(() => DEPT_ORDER.filter((d) => this.points().some((p) => p.group === d))
    .concat([...new Set(this.points().map((p) => p.group))].filter((g) => !DEPT_ORDER.includes(g))));
  color(g: string) { return deptColor(g); }
  x(v: number) { return this.L + 8 + (v / 100) * (this.w() - this.L - 26); }
  y(v: number) { return 18 + (1 - v / 100) * (this.base - 18); }
  rows(p: Pt): TipRow[] {
    return [{ label: this.xName(), value: String(p.x), color: this.color(p.group) }, { label: this.yName(), value: String(p.y) },
      ...(p.note ? [{ label: '', value: p.note }] : [])];
  }
}

// ------------------------------------------------------------------ stacked columns (parts of a whole per period)
export interface Part { key: string; label: string; color: string; }
@Component({
  selector: 'app-stack-columns',
  imports: [TipView],
  host: { class: 'viz' },
  template: `
    <div class="viz-legend">@for (p of parts(); track p.key) { <span><i [style.background]="p.color"></i>{{ p.label }}</span> }</div>
    <svg [attr.width]="w()" [attr.height]="H" role="img" [attr.aria-label]="label()">
      @for (t of ticks(); track t) {
        <line class="viz-grid" [attr.x1]="L" [attr.x2]="w() - 8" [attr.y1]="y(t)" [attr.y2]="y(t)" />
        <text class="viz-axis" [attr.x]="L - 6" [attr.y]="y(t) + 4" text-anchor="end">{{ t }}</text>
      }
      @for (r of rows(); track r.label; let i = $index) {
        <g class="viz-hit" tabindex="0" [attr.aria-label]="r.label"
           (pointermove)="show($event, r.label, tipRows(r))" (pointerleave)="hide()" (focus)="show($event, r.label, tipRows(r))" (blur)="hide()">
          <rect [attr.x]="L + i * slot()" y="0" [attr.width]="slot()" [attr.height]="base" fill="transparent" />
          @for (s of segs(r); track s.key) { <path [attr.d]="s.d" [attr.fill]="s.color" /> }
        </g>
        <text class="viz-axis" [attr.x]="cx(i)" [attr.y]="H - 8" text-anchor="middle">{{ short(r.label) }}</text>
      }
      <line class="viz-base" [attr.x1]="L" [attr.x2]="w() - 8" [attr.y1]="base" [attr.y2]="base" />
    </svg>
    <app-tip [tip]="tip()" [width]="w()" />
    <details class="data-table"><summary>Show as table</summary>
      <table><thead><tr><th></th>@for (p of parts(); track p.key) { <th class="num">{{ p.label }}</th> }</tr></thead>
        <tbody>@for (r of rows(); track r.label) { <tr><td>{{ r.label }}</td>@for (p of parts(); track p.key) { <td class="num">{{ r.values[p.key] || 0 }}</td> }</tr> }</tbody></table></details>`,
})
export class StackColumns extends Sized {
  rows = input<{ label: string; values: Record<string, number> }[]>([]);
  parts = input<Part[]>([]);
  label = input('Stacked columns');
  readonly H = 230; readonly L = 34; readonly base = 230 - 30;
  top = computed(() => niceMax(Math.max(1, ...this.rows().map((r) => this.parts().reduce((a, p) => a + (r.values[p.key] || 0), 0)))));
  ticks = computed(() => [0, 0.5, 1].map((k) => Math.round(k * this.top())));
  slot = computed(() => (this.w() - this.L - 8) / Math.max(1, this.rows().length));
  bw = computed(() => Math.min(24, this.slot() * 0.6));
  y(v: number) { return 12 + (1 - v / this.top()) * (this.base - 12); }
  cx(i: number) { return this.L + i * this.slot() + this.slot() / 2; }
  short(l: string) { return l.length === 7 && l[4] === '-' ? new Date(l + '-01').toLocaleString(undefined, { month: 'short' }) : l; }
  segs(r: { label: string; values: Record<string, number> }) {
    const i = this.rows().indexOf(r); const x = this.cx(i) - this.bw() / 2;
    let acc = 0; const out: { key: string; color: string; d: string }[] = [];
    const visible = this.parts().filter((p) => (r.values[p.key] || 0) > 0);
    visible.forEach((p, k) => {
      const v = r.values[p.key]; const y0 = this.y(acc); acc += v; const y1 = this.y(acc);
      const gap = k < visible.length - 1 ? 2 : 0; // 2px surface gap between segments
      const top = k === visible.length - 1;
      const h = y0 - y1 - gap;
      if (h <= 0) return;
      out.push({ key: p.key, color: p.color, d: top ? barV(x, y1, this.bw(), y0) : `M${x},${y0}V${y1 + gap}H${x + this.bw()}V${y0}Z` });
    });
    return out;
  }
  tipRows(r: { values: Record<string, number> }) { return this.parts().map((p) => ({ label: p.label, value: String(r.values[p.key] || 0), color: p.color })); }
}

// ------------------------------------------------------------------ 100% horizontal stacks (e.g. risk level mix per department)
@Component({
  selector: 'app-hstack',
  imports: [TipView],
  host: { class: 'viz' },
  template: `
    <div class="viz-legend">@for (p of parts(); track p.key) { <span><i [style.background]="p.color"></i>{{ p.label }}</span> }</div>
    <svg [attr.width]="w()" [attr.height]="rows().length * 36 + 4" role="img" [attr.aria-label]="label()">
      @for (r of rows(); track r.label; let i = $index) {
        <g class="viz-hit" tabindex="0" [attr.aria-label]="r.label"
           (pointermove)="show($event, r.label, tipRows(r))" (pointerleave)="hide()" (focus)="show($event, r.label, tipRows(r))" (blur)="hide()">
          <text class="viz-label" x="0" [attr.y]="i * 36 + 22">{{ r.label }}</text>
          @for (s of segs(r); track s.key) {
            <rect [attr.x]="s.x" [attr.y]="i * 36 + 9" [attr.width]="s.w" height="18" [attr.fill]="s.color" rx="2" />
            @if (s.w > 38) { <text [attr.x]="s.x + s.w / 2" [attr.y]="i * 36 + 22" text-anchor="middle" class="viz-cell" [attr.fill]="s.ink">{{ s.pct }}%</text> }
          }
        </g>
      }
    </svg>
    <app-tip [tip]="tip()" [width]="w()" />
    <details class="data-table"><summary>Show as table</summary>
      <table><thead><tr><th></th>@for (p of parts(); track p.key) { <th class="num">{{ p.label }}</th> }</tr></thead>
        <tbody>@for (r of rows(); track r.label) { <tr><td>{{ r.label }}</td>@for (p of parts(); track p.key) { <td class="num">{{ r.values[p.key] || 0 }}</td> }</tr> }</tbody></table></details>`,
})
export class HStack extends Sized {
  rows = input<{ label: string; values: Record<string, number> }[]>([]);
  parts = input<Part[]>([]);
  label = input('Stacked bars');
  readonly LBL = 70;
  segs(r: { values: Record<string, number> }) {
    const total = this.parts().reduce((a, p) => a + (r.values[p.key] || 0), 0) || 1;
    const visible = this.parts().filter((p) => (r.values[p.key] || 0) > 0);
    const avail = this.w() - this.LBL - 2 * Math.max(0, visible.length - 1);
    let x = this.LBL;
    return visible.map((p) => {
      const n = r.values[p.key]; const w = (n / total) * avail;
      const s = { key: p.key, color: p.color, x, w, pct: Math.round((n / total) * 100), ink: p.key === 'high' || p.key === 'low' ? '#ffffff' : INK };
      x += w + 2;
      return s;
    });
  }
  tipRows(r: { values: Record<string, number> }) { return this.parts().map((p) => ({ label: p.label, value: String(r.values[p.key] || 0), color: p.color })); }
}

// ------------------------------------------------------------------ sparkline
@Component({
  selector: 'app-spark',
  template: `<svg [attr.width]="W" height="28" role="img" [attr.aria-label]="label()">
    @for (s of segs(); track $index) { <path [attr.d]="s" fill="none" stroke="#898781" stroke-width="1.5" stroke-linejoin="round" /> }
    @if (last(); as p) { <circle [attr.cx]="p[0]" [attr.cy]="p[1]" r="3" [attr.fill]="color()" /> }
  </svg>`,
})
export class Spark {
  values = input<(number | null)[]>([]);
  color = input(SERIES[0]);
  label = input('Trend');
  readonly W = 96;
  pts = computed(() => { const v = this.values(); const n = Math.max(1, v.length - 1);
    return v.map((x, i) => (x === null ? null : [2 + (i / n) * (this.W - 6), 4 + (1 - x / 100) * 20] as [number, number])); });
  segs = computed(() => { const out: string[] = []; let cur: string[] = [];
    this.pts().forEach((p) => { if (!p) { if (cur.length > 1) out.push('M' + cur.join('L')); cur = []; } else cur.push(p.join(',')); });
    if (cur.length > 1) out.push('M' + cur.join('L')); return out; });
  last = computed(() => [...this.pts()].reverse().find((p) => p) || null);
}

// ------------------------------------------------------------------ paired bars (e.g. student vs class average per component)
export interface Pair { label: string; a: number | null; b: number | null; }
@Component({
  selector: 'app-paired-bars',
  imports: [TipView],
  host: { class: 'viz' },
  template: `
    <div class="viz-legend"><span><i [style.background]="colorA()"></i>{{ nameA() }}</span><span><i [style.background]="colorB()"></i>{{ nameB() }}</span></div>
    <svg [attr.width]="w()" [attr.height]="data().length * ROW + 4" role="img" [attr.aria-label]="label()">
      @for (d of data(); track d.label; let i = $index) {
        <g class="viz-hit" tabindex="0" [attr.aria-label]="d.label + ': ' + nameA() + ' ' + f(d.a) + ', ' + nameB() + ' ' + f(d.b)"
           (pointermove)="show($event, d.label, rows(d))" (pointerleave)="hide()" (focus)="show($event, d.label, rows(d))" (blur)="hide()">
          <rect x="0" [attr.y]="i * ROW" [attr.width]="w()" [attr.height]="ROW" fill="transparent" />
          <text class="viz-label" x="0" [attr.y]="i * ROW + ROW / 2 + 4">{{ d.label }}</text>
          <rect [attr.x]="LBL" [attr.y]="i * ROW + 8" [attr.width]="track()" [attr.height]="T * 2 + 2" rx="4" class="viz-track" />
          @if (d.a !== null) { <path [attr.d]="bar(i, d.a, 0)" [attr.fill]="colorA()" />
            <text class="viz-val" [attr.x]="LBL + len(d.a) + 6" [attr.y]="i * ROW + 8 + T - 1">{{ f(d.a) }}</text> }
          @if (d.b !== null) { <path [attr.d]="bar(i, d.b, 1)" [attr.fill]="colorB()" />
            <text class="viz-axis" [attr.x]="LBL + len(d.b) + 6" [attr.y]="i * ROW + 8 + 2 * T + 1">{{ f(d.b) }}</text> }
        </g>
      }
    </svg>
    <app-tip [tip]="tip()" [width]="w()" />
    <details class="data-table"><summary>Show as table</summary>
      <table><thead><tr><th></th><th class="num">{{ nameA() }}</th><th class="num">{{ nameB() }}</th><th class="num">Difference</th></tr></thead>
        <tbody>@for (d of data(); track d.label) { <tr><td>{{ d.label }}</td><td class="num">{{ f(d.a) }}</td><td class="num">{{ f(d.b) }}</td>
          <td class="num">{{ d.a !== null && d.b !== null ? (d.a - d.b > 0 ? '+' : '') + f(d.a - d.b) : '–' }}</td></tr> }</tbody></table></details>`,
})
export class PairedBars extends Sized {
  data = input<Pair[]>([]);
  nameA = input('This student');
  nameB = input('Class average');
  colorA = input(SERIES[0]);
  colorB = input('#b9b7ae');
  label = input('Comparison');
  readonly ROW = 40; readonly T = 10; readonly LBL = 150;
  track = computed(() => Math.max(40, this.w() - this.LBL - 44));
  len(v: number) { return (Math.max(0, v) / 100) * this.track(); }
  bar(i: number, v: number, k: number) { return barH(this.LBL, i * this.ROW + 8 + k * (this.T + 2), this.len(v), this.T); }
  f(v: number | null) { return fmt(v); }
  rows(d: Pair): TipRow[] { return [{ label: this.nameA(), value: this.f(d.a), color: this.colorA() }, { label: this.nameB(), value: this.f(d.b), color: this.colorB() }]; }
}
