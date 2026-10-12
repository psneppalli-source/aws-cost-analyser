import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Api, ApiError } from '../core/api.service';
import { Session } from '../core/session.service';
import { message } from '../shared/page';
import { StateView } from '../shared/ui';

interface Field { name: string; type: 'int' | 'float' | 'str' | 'enum' | 'list'; required: boolean; min: number | null; max: number | null;
  choices: string[]; sensitive: boolean; help: string | null; }
interface Category { category: string; label: string; description: string; natural_key: string[]; correction_required: boolean;
  verification: boolean; fields: Field[]; actions: string[]; scopes: string[]; }
interface Existing { version: number; verification?: string; [k: string]: unknown; }
interface RosterRow { student_id: string; name: string; department: string; year: number; existing: Existing[]; }
interface GridRow extends RosterRow { values: Record<string, unknown>; match: Existing | null; state: string; error: string; dirty: boolean; }

/** Fields shared by every row of a class sheet (they identify which record is being entered). */
const COMMON: Record<string, string[]> = {
  marks: ['subject', 'assessment', 'max_score'], attendance: ['subject', 'classes_held'],
  engagement: ['activity_type', 'name', 'role'], placement_assessment: ['assessment_type'],
};
const SUBJECT = new Set(['marks', 'attendance']);

@Component({
  selector: 'app-entry-page',
  imports: [FormsModule, RouterLink, StateView],
  styles: [`.cats{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px;margin-bottom:16px}
    .cats button{text-align:left;padding:12px 14px;border:1px solid var(--line);border-radius:10px;background:var(--white);cursor:pointer;font:inherit}
    .cats button[aria-pressed=true]{border-color:var(--teal-500);box-shadow:0 0 0 2px var(--teal-100)}
    td input,td select{min-width:70px;padding:5px 7px} .saved{color:var(--low)} .warn{color:var(--medium)}`],
  template: `
    <div class="page-head"><h1>{{ student() ? 'Submit information' : 'Enter data' }}</h1>
      <p class="sub">Only the kinds of data your role is responsible for are listed. Every save records the source, period, time and you as the author.
        @if (!student()) { For many rows, use <a routerLink="/imports">CSV / Excel import</a>. }</p></div>
    <app-state [loading]="loading()" [error]="error()" (retry)="init()" [empty]="!loading() && !cats().length && !canCreateStudent()" emptyText="Your role does not enter student data." />

    @if (cats().length || canCreateStudent()) {
      <div class="cats" role="group" aria-label="What to enter">
        @for (c of cats(); track c.category) {
          <button type="button" [attr.aria-pressed]="cat()?.category === c.category" (click)="pick(c)"><strong>{{ c.label }}</strong><br>
            <span class="small muted">{{ c.description }}</span>
            @if (c.correction_required && !student()) { <br><span class="small">Changes to saved values go to the HOD for approval.</span> }
            @if (c.actions.includes('submit')) { <br><span class="small">Verified by the activity coordinator.</span> }</button>
        }
        @if (canCreateStudent()) { <button type="button" [attr.aria-pressed]="newStudent()" (click)="pickNewStudent()"><strong>New student</strong><br>
          <span class="small muted">Create a student master record in the {{ session.dataset() }} dataset.</span></button> }
      </div>
    }

    @if (newStudent()) {
      <section class="card"><h2>New student</h2>
        <form class="form-grid" (submit)="$event.preventDefault(); createStudent()">
          <label class="field">Student ID<input name="sid" [(ngModel)]="master.student_id" placeholder="CSE26014" required [attr.aria-invalid]="!!fieldErr()['student_id']"></label>
          <label class="field">Full name<input name="n" [(ngModel)]="master.name" required></label>
          <label class="field">Department<select name="d" [(ngModel)]="master.department">@for (d of departments(); track d) { <option [value]="d">{{ d }}</option> }</select></label>
          <label class="field">Year<select name="y" [(ngModel)]="master.year">@for (y of [1,2,3,4]; track y) { <option [ngValue]="y">{{ y }}</option> }</select></label>
          <label class="field">Email (optional)<input name="e" type="email" [(ngModel)]="master.email"></label>
          @if (formMsg()) { <p style="grid-column:1/-1" [class.error-text]="formErr()" role="status">{{ formMsg() }}</p> }
          <div style="grid-column:1/-1"><button class="btn primary" type="submit" [disabled]="busy()">Create student</button></div>
        </form></section>
    }

    @if (cat(); as c) {
      <section class="card">
        <div class="card-head"><h2>{{ c.label }}</h2></div>
        <div class="form-grid">
          <label class="field">Reporting period<select [(ngModel)]="period" name="p" (ngModelChange)="reload()">
            @for (p of periods(); track p) { <option [value]="p">{{ p }}</option> }</select></label>
          @if (!student()) {
            @if (isSubject(c)) {
              <label class="field">Class<select [(ngModel)]="classKey" name="cl" (ngModelChange)="reload()">
                @for (k of classes(); track k.key) { <option [value]="k.key">{{ k.department }} Y{{ k.year }} · {{ k.subject }}</option> }</select></label>
            } @else {
              <label class="field">Department<select [(ngModel)]="dept" name="d" (ngModelChange)="reload()"><option value="">All</option>
                @for (d of departments(); track d) { <option [value]="d">{{ d }}</option> }</select></label>
              <label class="field">Year<select [(ngModel)]="year" name="y" (ngModelChange)="reload()"><option value="">All</option>
                @for (y of ['1','2','3','4']; track y) { <option [value]="y">Year {{ y }}</option> }</select></label>
            }
          }
          @for (f of commonFields(); track f.name) {
            @if (f.name !== 'subject') {
              <label class="field">{{ f.name }}@if (f.help) { <span class="small muted"> ({{ f.help }})</span> }
                @if (f.type === 'enum') { <select [name]="'c' + f.name" [(ngModel)]="common[f.name]" (ngModelChange)="rematch()">@for (o of f.choices; track o) { <option [value]="o">{{ o }}</option> }</select> }
                @else { <input [name]="'c' + f.name" [type]="num(f) ? 'number' : 'text'" [attr.min]="f.min" [attr.max]="f.max" [(ngModel)]="common[f.name]" (ngModelChange)="rematch()"> }
              </label>
            }
          }
        </div>
        @if (msg()) { <p class="banner" role="status">{{ msg() }}</p> }
      </section>

      @if (student()) {
        <section class="card" style="margin-top:14px">
          <form class="form-grid" (submit)="$event.preventDefault(); saveOwn()">
            @for (f of c.fields; track f.name) {
              <label class="field" [style.grid-column]="f.type === 'list' || f.name === 'comment' ? '1/-1' : null">{{ f.name }}@if (!f.required) { <span class="small muted"> (optional)</span> }
                @if (f.type === 'list') {
                  <span class="row" style="gap:12px;flex-wrap:wrap">@for (o of f.choices; track o) {
                    <label class="row small" style="gap:4px"><input type="checkbox" style="width:auto" [checked]="has(own[f.name], o)" (change)="toggle(own, f.name, o)">{{ o }}</label> }</span>
                } @else if (f.type === 'enum') { <select [name]="f.name" [(ngModel)]="own[f.name]">@for (o of f.choices; track o) { <option [value]="o">{{ o }}</option> }</select>
                } @else if (f.name === 'comment') { <textarea [name]="f.name" [(ngModel)]="own[f.name]" maxlength="1000"></textarea>
                  <span class="small muted">Seen only by you, your mentor, your HOD and the college administrator.</span>
                } @else { <input [name]="f.name" [type]="num(f) ? 'number' : 'text'" [attr.min]="f.min" [attr.max]="f.max" [(ngModel)]="own[f.name]"> }
                @if (fieldErr()[f.name]) { <span class="error-text">{{ fieldErr()[f.name] }}</span> }
              </label>
            }
            @if (c.category === 'feedback') { <p class="small muted" style="grid-column:1/-1">Feedback helps staff offer support. It never lowers your score.</p> }
            <div style="grid-column:1/-1"><button class="btn primary" type="submit" [disabled]="busy()">Submit</button></div>
          </form>
        </section>
      } @else {
        <app-state [loading]="rosterLoading()" [empty]="!rosterLoading() && !rows().length" emptyText="No students you can enter this for. Check the filters or your assignments." />
        @if (rows().length) {
          <div class="card" style="padding:0;margin-top:14px"><div class="table-wrap"><table>
            <caption class="sr-only">{{ c.label }} for {{ period }}</caption>
            <thead><tr><th>Student</th>@for (f of rowFields(); track f.name) { <th>{{ f.name }}@if (f.required) { * } </th> }<th>Saved value</th><th>Status</th></tr></thead>
            <tbody>@for (r of rows(); track r.student_id) {
              <tr><td>{{ r.name }}<br><span class="mono small muted">{{ r.student_id }}</span></td>
                @for (f of rowFields(); track f.name) { <td>
                  @if (f.type === 'enum') { <select [attr.aria-label]="f.name + ' for ' + r.name" [(ngModel)]="r.values[f.name]" (ngModelChange)="touch(r)"><option value=""></option>@for (o of f.choices; track o) { <option [value]="o">{{ o }}</option> }</select> }
                  @else { <input [attr.aria-label]="f.name + ' for ' + r.name" [type]="num(f) ? 'number' : 'text'" [attr.min]="f.min" [attr.max]="f.max" [(ngModel)]="r.values[f.name]" (ngModelChange)="touch(r)" [attr.aria-invalid]="!!r.error"> }
                </td> }
                <td class="small">@if (r.match) { {{ summary(r.match) }} <span class="muted">v{{ r.match.version }}</span> } @else { – }</td>
                <td class="small" aria-live="polite"><span [class.saved]="r.state === 'Saved'" [class.warn]="r.state.startsWith('Correction')">{{ r.state }}</span>
                  @if (r.error) { <span class="error-text">{{ r.error }}</span> }</td></tr>
            }</tbody></table></div></div>
          <p class="row" style="margin-top:12px"><button class="btn primary" type="button" (click)="saveAll()" [disabled]="busy() || !dirtyCount()">Save {{ dirtyCount() }} changed row(s)</button>
            <span class="small muted">Rows are saved one by one. Unchanged values are skipped; if someone else changed a value meanwhile, that row is not overwritten.</span></p>
        }
      }
    }`,
})
export class EntryPage {
  private api = inject(Api);
  session = inject(Session);
  cats = signal<Category[]>([]);
  cat = signal<Category | null>(null);
  newStudent = signal(false);
  rows = signal<GridRow[]>([]);
  classList = signal<{ department: string; year: number; subject: string }[]>([]);
  loading = signal(true);
  rosterLoading = signal(false);
  busy = signal(false);
  error = signal<string | null>(null);
  msg = signal<string | null>(null);
  formMsg = signal<string | null>(null);
  formErr = signal(false);
  fieldErr = signal<Record<string, string>>({});
  period = '';
  classKey = '';
  dept = '';
  year = '';
  common: Record<string, unknown> = {};
  own: Record<string, unknown> = {};
  master: { student_id?: string; name?: string; department?: string; year: number; email?: string } = { year: 1 };
  student = computed(() => this.session.isStudent());
  periods = computed(() => [...(this.session.me()?.periods || [])].reverse());
  departments = computed(() => Object.keys(this.session.me()?.departments || {}));
  classes = computed(() => this.classList().map((c) => ({ ...c, key: `${c.department}|${c.year}|${c.subject}` })));
  canCreateStudent = computed(() => this.session.can('student_master', 'create'));
  commonFields = computed(() => { const c = this.cat(); return c && !this.student() ? c.fields.filter((f) => (COMMON[c.category] || []).includes(f.name)) : []; });
  rowFields = computed(() => { const c = this.cat(); return c ? c.fields.filter((f) => !(COMMON[c.category] || []).includes(f.name) && !f.sensitive && f.type !== 'list') : []; });
  dirtyCount = computed(() => this.rows().filter((r) => r.dirty).length);

  constructor() { this.init(); }

  async init() {
    this.loading.set(true); this.error.set(null);
    try {
      const r = await this.api.get<{ categories: Category[]; periods: string[] }>('/entry/categories');
      this.cats.set(r.categories);
      this.period = this.session.me()?.current_period || this.periods()[0] || '';
      if (this.cats().some((c) => SUBJECT.has(c.category))) {
        this.classList.set((await this.api.get<{ classes: { department: string; year: number; subject: string }[] }>('/entry/classes')).classes);
        this.classKey = this.classes()[0]?.key || '';
      }
      if (this.cats().length === 1) this.pick(this.cats()[0]);
    } catch (e) { this.error.set(message(e)); }
    finally { this.loading.set(false); }
  }

  isSubject(c: Category) { return SUBJECT.has(c.category); }
  num(f: Field) { return f.type === 'int' || f.type === 'float'; }
  has(v: unknown, o: string) { return Array.isArray(v) && v.includes(o); }
  toggle(obj: Record<string, unknown>, k: string, o: string) {
    const cur = Array.isArray(obj[k]) ? obj[k] as string[] : [];
    obj[k] = cur.includes(o) ? cur.filter((x) => x !== o) : [...cur, o];
  }
  summary(e: Existing) {
    return this.rowFields().map((f) => e[f.name]).filter((v) => v !== undefined && v !== null && v !== '').join(' / ')
      + (e.verification && e.verification !== 'verified' ? ` (${e.verification})` : '');
  }

  /** Rows are mutated in place by the form; re-emit so the changed-row count updates. */
  touch(r: GridRow) { r.dirty = true; this.rows.update((x) => [...x]); }

  pick(c: Category) {
    this.newStudent.set(false);
    this.cat.set(c); this.msg.set(null); this.fieldErr.set({});
    this.common = {};
    for (const f of c.fields) if ((COMMON[c.category] || []).includes(f.name) && f.type === 'enum') this.common[f.name] = f.choices[0];
    if (c.category === 'marks') this.common['max_score'] = 50;
    this.own = {};
    this.reload();
  }
  pickNewStudent() { this.cat.set(null); this.newStudent.set(true); this.formMsg.set(null); this.master = { year: 1, department: this.departments()[0] }; }

  async reload() {
    const c = this.cat();
    if (!c || this.student()) return;
    if (this.isSubject(c)) { this.common['subject'] = this.classKey.split('|')[2]; if (!this.classKey) { this.rows.set([]); return; } }
    this.rosterLoading.set(true); this.msg.set(null);
    const [d, y] = this.isSubject(c) ? this.classKey.split('|') : [this.dept, this.year];
    try {
      const r = await this.api.get<{ items: RosterRow[] }>('/entry/roster', { category: c.category, period: this.period,
        dataset: this.session.dataset(), department: d, year: y, subject: this.common['subject'] as string });
      this.rows.set(r.items.map((x) => ({ ...x, values: {}, match: null, state: '', error: '', dirty: false })));
      this.rematch();
    } catch (e) { this.msg.set(message(e)); this.rows.set([]); }
    finally { this.rosterLoading.set(false); }
  }

  /** Find each student's saved record for the identifying fields chosen above and prefill the row. */
  rematch() {
    const c = this.cat();
    if (!c) return;
    const keys = c.natural_key.filter((k) => k !== 'student_id' && k !== 'period');
    this.rows.update((rows) => rows.map((r) => {
      const match = r.existing.find((e) => keys.every((k) => String(e[k] ?? '').toLowerCase() === String(this.common[k] ?? '').toLowerCase())) || null;
      const values: Record<string, unknown> = {};
      for (const f of this.rowFields()) values[f.name] = match ? match[f.name] ?? '' : '';
      return { ...r, match, values, dirty: false, state: '', error: '' };
    }));
  }

  private payload(values: Record<string, unknown>) {
    const c = this.cat()!;
    const data: Record<string, unknown> = {};
    for (const f of c.fields) {
      const v = f.name in values ? values[f.name] : this.common[f.name];
      if (v === '' || v === undefined || v === null) continue;
      data[f.name] = f.type === 'int' || f.type === 'float' ? Number(v) : v;
    }
    return data;
  }

  async saveAll() {
    const c = this.cat()!;
    this.busy.set(true);
    let saved = 0, corrections = 0, failed = 0;
    for (const r of this.rows().filter((x) => x.dirty)) {
      try {
        const res = await this.api.put<{ status: string; record?: Existing }>(`/students/${this.session.dataset()}/${r.student_id}/records/${c.category}/${this.period}`,
          { data: this.payload(r.values), version: r.match?.version });
        if (res.status === 'pending_correction') { r.state = 'Correction requested'; corrections++; }
        else { r.state = res.status === 'unchanged' ? 'No change' : 'Saved'; saved++; if (res.record) { r.match = res.record; } }
        r.error = ''; r.dirty = false;
      } catch (e) {
        failed++;
        r.state = '';
        r.error = e instanceof ApiError && e.status === 409 ? 'Changed by someone else. Reload to see the latest value.' : message(e);
      }
      this.rows.update((x) => [...x]);
    }
    this.msg.set(`${saved} saved, ${corrections} sent for HOD approval, ${failed} not saved.`);
    this.busy.set(false);
  }

  async saveOwn() {
    const c = this.cat()!;
    const me = this.session.me()!.user.student!;
    this.busy.set(true); this.fieldErr.set({}); this.msg.set(null);
    try {
      const existing = (await this.api.get<{ items: Existing[] }>(`/students/${me.dataset}/${me.student_id}/records`, { category: c.category, period: this.period })).items;
      const data = this.payload(this.own);
      const keys = c.natural_key.filter((k) => k !== 'student_id' && k !== 'period');
      const match = existing.find((e) => keys.every((k) => String(e[k] ?? '').toLowerCase() === String(data[k] ?? '').toLowerCase()));
      const res = await this.api.put<{ status: string }>(`/students/${me.dataset}/${me.student_id}/records/${c.category}/${this.period}`, { data, version: match?.version });
      this.msg.set(res.status === 'unchanged' ? 'Nothing changed.' : c.verification ? 'Submitted. It will count once the activity coordinator verifies it.' : 'Thank you. Your response was saved.');
      this.own = {};
    } catch (e) {
      if (e instanceof ApiError) this.fieldErr.set(e.fields);
      this.msg.set(message(e));
    } finally { this.busy.set(false); }
  }

  async createStudent() {
    this.busy.set(true); this.formMsg.set(null); this.fieldErr.set({});
    try {
      const r = await this.api.post<{ student_id: string }>('/students', { ...this.master, dataset: this.session.dataset() });
      this.formErr.set(false); this.formMsg.set(`Created ${r.student_id}.`);
      this.master = { year: 1, department: this.departments()[0] };
    } catch (e) {
      this.formErr.set(true); this.formMsg.set(message(e));
      if (e instanceof ApiError) this.fieldErr.set(e.fields);
    } finally { this.busy.set(false); }
  }
}
