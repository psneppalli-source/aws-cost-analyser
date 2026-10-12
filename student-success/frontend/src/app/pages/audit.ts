import { Component, computed, inject, signal } from '@angular/core';
import { Api } from '../core/api.service';
import { Session } from '../core/session.service';
import { when } from '../shared/labels';
import { message } from '../shared/page';
import { StateView } from '../shared/ui';

interface Entry { ts: string; actor_name: string; action: string; entity: string; entity_id: string; dataset: string; details: Record<string, unknown>; }

@Component({
  selector: 'app-audit-page',
  imports: [StateView],
  template: `
    <div class="page-head"><h1>Audit history</h1><span class="spacer"></span>
      @if (cats().length > 1) {
        <div class="row" role="group" aria-label="Audit category" style="gap:6px">
          @for (c of cats(); track c) { <button class="btn small" type="button" [class.primary]="cat() === c" (click)="switch(c)">{{ c === 'academic' ? 'Academic' : 'Technical' }}</button> }</div>
      }
      <p class="sub">{{ cat() === 'academic' ? 'Changes to student data, scores, interventions and configuration.' : 'Accounts, role assignments and platform settings.' }}
        Sensitive values (feedback comments, notes, tokens) are never recorded here.</p></div>
    <app-state [loading]="loading() && !items().length" [error]="error()" (retry)="load(true)" [empty]="!loading() && !items().length" emptyText="No audit entries." />
    @if (items().length) {
      <div class="card" style="padding:0"><div class="table-wrap"><table>
        <thead><tr><th>When</th><th>Who</th><th>Action</th><th>What</th><th>Dataset</th><th>Details</th></tr></thead>
        <tbody>@for (e of items(); track e.ts + e.action + e.entity_id) {
          <tr><td class="small when">{{ when(e.ts) }}</td><td class="small">{{ e.actor_name }}</td><td class="mono small">{{ e.action }}</td>
            <td class="small">{{ e.entity }} {{ e.entity_id }}</td><td class="small">{{ e.dataset || '–' }}</td><td class="small mono">{{ fmt(e.details) }}</td></tr>
        }</tbody></table></div></div>
      @if (next()) { <p style="text-align:center"><button class="btn" type="button" (click)="load(false)" [disabled]="loading()">Older entries</button></p> }
    }`,
})
export class AuditPage {
  private api = inject(Api);
  session = inject(Session);
  when = when;
  cats = computed(() => (['academic', 'technical'] as const).filter((c) => this.session.can(`audit.${c}`, 'read')));
  cat = signal<string>(this.cats()[0] || 'academic');
  items = signal<Entry[]>([]);
  next = signal<string | null>(null);
  loading = signal(true);
  error = signal<string | null>(null);

  constructor() { this.load(true); }
  switch(c: string) { this.cat.set(c); this.load(true); }
  fmt(d: Record<string, unknown>) { const s = JSON.stringify(d || {}); return s === '{}' ? '' : s; }

  async load(reset: boolean) {
    this.loading.set(true); this.error.set(null);
    try {
      const r = await this.api.get<{ items: Entry[]; next_cursor: string | null }>('/audit', { category: this.cat(), limit: 50, cursor: reset ? null : this.next() });
      this.items.set(reset ? r.items : [...this.items(), ...r.items]);
      this.next.set(r.next_cursor);
    } catch (e) { this.error.set(message(e)); }
    finally { this.loading.set(false); }
  }
}
