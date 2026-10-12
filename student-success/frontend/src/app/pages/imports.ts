import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../core/api.service';
import { Session } from '../core/session.service';
import { download, when } from '../shared/labels';
import { message } from '../shared/page';
import { StateView } from '../shared/ui';

interface Problem { row: number; student_id: string; status: string; errors: string[]; }
interface Import {
  import_id: string; category: string; dataset: string; filename: string; status: string; created_at: string; created_by_name: string;
  total_rows: number; accepted: number; rejected: number; duplicates: number; planned: Record<string, number>;
  batches_total: number; next_batch: number; written: number; unchanged: number; failed: number; ignored_columns: string[];
  mapping: Record<string, string>; problems: Problem[];
}

@Component({
  selector: 'app-imports-page',
  imports: [FormsModule, StateView],
  template: `
    <div class="page-head"><h1>Import CSV or Excel</h1>
      <p class="sub">Upload, preview and fix problems before anything is saved. Imports follow the same permissions as manual entry,
        are applied in small batches, and can be resumed safely: retrying never writes a row twice.</p></div>
    <section class="card">
      <form class="form-grid" (submit)="$event.preventDefault(); preview()">
        <label class="field">What are you importing?<select name="c" [(ngModel)]="category">
          @for (c of cats(); track c.category) { <option [value]="c.category">{{ c.label }}</option> }</select></label>
        <div class="field"><span>Template</span><button class="btn" type="button" style="min-height:38px;white-space:nowrap" (click)="template()" [disabled]="!category">Download CSV template</button></div>
        <label class="field" style="grid-column:1/-1">File (.csv or .xlsx, up to 2,000 rows)
          <input type="file" accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" (change)="file = $any($event.target).files?.[0] || null"></label>
        @if (err()) { <p class="error-text" role="alert" style="grid-column:1/-1">{{ err() }}</p> }
        <div style="grid-column:1/-1"><button class="btn primary" type="submit" [disabled]="busy() || !file || !category">Upload and preview</button></div>
      </form>
    </section>

    @if (cur(); as i) {
      <section class="card" style="margin-top:16px" aria-live="polite">
        <div class="card-head"><h2>{{ i.filename }}</h2><span class="chip">{{ statusLabel(i.status) }}</span><span class="spacer"></span><span class="mono small muted">{{ i.import_id }}</span></div>
        <section class="kpis">
          <div class="kpi"><div class="label">Rows</div><div class="value">{{ i.total_rows }}</div></div>
          <div class="kpi"><div class="label">Accepted</div><div class="value">{{ i.accepted }}</div>
            <div class="note">{{ i.planned['create'] || 0 }} new · {{ i.planned['update'] || 0 }} updates · {{ i.planned['unchanged'] || 0 }} unchanged</div></div>
          <div class="kpi"><div class="label">Rejected</div><div class="value">{{ i.rejected }}</div></div>
          <div class="kpi"><div class="label">Duplicates</div><div class="value">{{ i.duplicates }}</div></div>
          @if (i.status !== 'previewed' && i.status !== 'rejected') {
            <div class="kpi"><div class="label">Applied</div><div class="value">{{ i.written }}</div><div class="note">{{ i.unchanged }} unchanged · {{ i.failed }} failed · batch {{ i.next_batch }}/{{ i.batches_total }}</div></div>
          }
        </section>
        @if (i.ignored_columns.length) { <p class="banner warn small">Ignored columns: {{ i.ignored_columns.join(', ') }}</p> }
        @if (i.status === 'previewed' || i.status === 'partial' || i.status === 'processing') {
          <p class="row"><button class="btn primary" type="button" (click)="commit()" [disabled]="busy() || !i.accepted">
            {{ i.status === 'previewed' ? 'Apply ' + i.accepted + ' accepted row(s)' : 'Resume import' }}</button>
            <span class="small muted">Rejected and duplicate rows are skipped. Fix them in the file and import again.</span></p>
        }
        @if (i.status === 'completed') { <p class="banner">Import complete. Scores for affected students have been recalculated.</p> }
        @if (i.problems.length) {
          <h3>Rows needing attention</h3>
          <div class="table-wrap"><table><thead><tr><th class="num">Row</th><th>Student</th><th>Result</th><th>Problem</th></tr></thead>
            <tbody>@for (p of i.problems; track p.row) { <tr><td class="num">{{ p.row }}</td><td class="mono">{{ p.student_id || '–' }}</td><td>{{ p.status }}</td><td class="small">{{ p.errors.join('; ') }}</td></tr> }</tbody></table></div>
          <p class="row" style="gap:8px"><button class="btn small" type="button" (click)="exportProblems(i)">Download problems as CSV</button>
            @if (session.me()?.ai) { <button class="btn small" type="button" (click)="explain(i)" [disabled]="exBusy()">{{ exBusy() ? 'Explaining…' : '✨ Explain these problems' }}</button> }</p>
          @if (exError()) { <p class="error-text" role="alert">{{ exError() }}</p> }
          @if (ex().length) {
            <div class="banner" style="margin-top:8px" aria-live="polite">
              @for (l of ex(); track $index) { @if (l.startsWith('- ')) { <div style="margin:4px 0">• {{ l.slice(2) }}</div> } @else { <p style="margin:0 0 6px"><strong>{{ l }}</strong></p> } }
              <p class="small muted" style="margin:8px 0 0">AI explanation of the problems above (row values are not shared). Fix the file and upload it again.</p></div>
          }
        }
      </section>
    }

    <section class="card" style="margin-top:16px"><div class="card-head"><h2>Recent imports</h2><span class="spacer"></span>
      <button class="btn small" type="button" (click)="history()">Refresh</button></div>
      <app-state [loading]="histLoading()" [empty]="!histLoading() && !past().length" emptyText="No imports yet." />
      @if (past().length) {
        <div class="table-wrap"><table><thead><tr><th>When</th><th>File</th><th>Type</th><th>Dataset</th><th>By</th><th>Status</th><th class="num">Accepted</th><th class="num">Applied</th><th></th></tr></thead>
          <tbody>@for (i of past(); track i.import_id) {
            <tr><td class="small">{{ when(i.created_at) }}</td><td>{{ i.filename }}</td><td>{{ i.category }}</td><td>{{ i.dataset }}</td><td>{{ i.created_by_name }}</td>
              <td>{{ statusLabel(i.status) }}</td><td class="num">{{ i.accepted }}</td><td class="num">{{ i.written }}</td>
              <td><button class="btn small" type="button" (click)="open(i.import_id)">Open</button></td></tr> }</tbody></table></div>
      }
    </section>`,
})
export class ImportsPage {
  private api = inject(Api);
  session = inject(Session);
  when = when;
  cats = signal<{ category: string; label: string }[]>([]);
  cur = signal<Import | null>(null);
  past = signal<Import[]>([]);
  busy = signal(false);
  histLoading = signal(false);
  err = signal<string | null>(null);
  category = '';
  file: File | null = null;
  canMaster = computed(() => this.session.can('student_master', 'create'));

  constructor() { this.init(); this.history(); }

  ex = signal<string[]>([]);
  exBusy = signal(false);
  exError = signal<string | null>(null);
  async explain(i: { import_id: string }) {
    this.exBusy.set(true); this.exError.set(null);
    try { this.ex.set((await this.api.post<{ lines: string[] }>('/ai/tool', { tool: 'import_help', import_id: i.import_id })).lines); }
    catch (e) { this.exError.set(message(e)); }
    finally { this.exBusy.set(false); }
  }

  async init() {
    try {
      const r = await this.api.get<{ categories: { category: string; label: string }[] }>('/entry/categories');
      const list = r.categories.filter((c) => c.category !== 'feedback' && c.category !== 'certification');
      if (this.canMaster()) list.unshift({ category: 'student_master', label: 'Student master records' });
      this.cats.set(list);
      this.category = list[0]?.category || '';
    } catch (e) { this.err.set(message(e)); }
  }

  async history() {
    this.histLoading.set(true);
    try { this.past.set((await this.api.get<{ items: Import[] }>('/imports')).items); } catch { /* shown as empty */ }
    finally { this.histLoading.set(false); }
  }

  statusLabel(s: string) { return ({ previewed: 'Previewed — not yet applied', partial: 'Partly applied — resume', processing: 'Applying', completed: 'Completed', rejected: 'Nothing to apply' } as Record<string, string>)[s] || s; }

  async template() {
    try { download(`${this.category}_template.csv`, await this.api.text(`/templates/${this.category}.csv`)); }
    catch (e) { this.err.set(message(e)); }
  }

  async preview() {
    if (!this.file) return;
    this.busy.set(true); this.err.set(null);
    try {
      const buf = await this.file.arrayBuffer();
      this.cur.set(await this.api.upload<Import>('/imports/preview', buf, { category: this.category, dataset: this.session.dataset(), filename: this.file.name }));
      this.history();
    } catch (e) { this.err.set(message(e)); }
    finally { this.busy.set(false); }
  }

  /** Each call applies batches for up to ~10 s; keep calling until done. Safe to retry after a network error. */
  async commit() {
    const i = this.cur();
    if (!i) return;
    this.busy.set(true); this.err.set(null);
    try {
      let r = i;
      for (let n = 0; n < 50; n++) {
        r = await this.api.post<Import>(`/imports/${i.import_id}/commit`);
        this.cur.set(r);
        if (r.status === 'completed') break;
      }
      this.history();
    } catch (e) { this.err.set(`${message(e)} You can press Resume to continue where it stopped.`); }
    finally { this.busy.set(false); }
  }

  async open(id: string) {
    try { this.cur.set(await this.api.get<Import>(`/imports/${id}`)); } catch (e) { this.err.set(message(e)); }
  }

  exportProblems(i: Import) {
    const esc = (s: string) => `"${s.replace(/"/g, '""')}"`;
    download(`${i.import_id}_problems.csv`, ['row,student_id,status,problem', ...i.problems.map((p) => [p.row, esc(p.student_id || ''), p.status, esc(p.errors.join('; '))].join(','))].join('\n'));
  }
}
