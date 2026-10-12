import { Component, computed, inject, signal } from '@angular/core';
import { Api } from '../core/api.service';
import { message } from '../shared/page';
import { StateView } from '../shared/ui';

interface Perm { resource: string; action: string; scope: string; fields?: string | string[]; constraints?: Record<string, unknown>; }
interface Matrix { version: string; description: string; scopes: Record<string, string>; field_sets: Record<string, string[]>;
  roles: Record<string, { label: string; summary: string; permissions: Perm[] }>; separation_of_duties: { rules: string[] }; }

@Component({
  selector: 'app-role-matrix-page',
  imports: [StateView],
  template: `
    <div class="page-head"><h1>Role matrix</h1>
      <p class="sub">The canonical permission policy (config/role-matrix.json) the API enforces on every request.
        @if (m(); as m) { Version {{ m.version }}. } Each permission is resource · action · scope · fields.</p></div>
    <app-state [loading]="!m() && !error()" [error]="error()" (retry)="load()" />
    @if (m(); as m) {
      <section class="card"><div class="card-head"><h2>Overview</h2><span class="desc">✓ = allowed in at least one scope. Hover a cell for the scopes.</span></div>
        <div class="table-wrap"><table><thead><tr><th>Resource · action</th>@for (r of roleKeys(); track r) { <th style="text-align:center">{{ m.roles[r].label }}</th> }</tr></thead>
          <tbody>@for (ra of resourceActions(); track ra) {
            <tr><td class="mono small">{{ ra }}</td>@for (r of roleKeys(); track r) {
              <td style="text-align:center" [attr.title]="scopes(r, ra)">@if (scopes(r, ra)) { <span aria-label="allowed">✓</span><br><span class="small muted">{{ scopes(r, ra) }}</span> } @else { <span class="muted" aria-label="not allowed">–</span> }</td> }</tr>
          }</tbody></table></div></section>
      <div class="grid g2" style="margin-top:16px">
        @for (r of roleKeys(); track r) {
          <section class="card"><h2>{{ m.roles[r].label }}</h2><p class="small">{{ m.roles[r].summary }}</p>
            <details><summary>{{ m.roles[r].permissions.length }} permissions</summary>
              <div class="table-wrap"><table><thead><tr><th>Resource</th><th>Action</th><th>Scope</th><th>Fields</th></tr></thead>
                <tbody>@for (p of m.roles[r].permissions; track $index) {
                  <tr><td class="mono small">{{ p.resource }}</td><td>{{ p.action }}</td><td>{{ p.scope }}</td>
                    <td class="small">{{ fields(p) }}@if (p.constraints) { <br><em>{{ json(p.constraints) }}</em> }</td></tr> }</tbody></table></div></details>
          </section>
        }
      </div>
      <div class="grid g2" style="margin-top:16px">
        <section class="card"><h2>Scopes</h2><dl>@for (s of keys(m.scopes); track s) { <dt class="mono">{{ s }}</dt><dd class="small" style="margin:0 0 8px">{{ m.scopes[s] }}</dd> }</dl></section>
        <section class="card"><h2>Separation of duties</h2><ul>@for (r of m.separation_of_duties.rules; track r) { <li>{{ r }}</li> }</ul></section>
      </div>
    }`,
})
export class RoleMatrixPage {
  private api = inject(Api);
  m = signal<Matrix | null>(null);
  error = signal<string | null>(null);
  roleKeys = computed(() => Object.keys(this.m()?.roles || {}));
  resourceActions = computed(() => {
    const s = new Set<string>();
    Object.values(this.m()?.roles || {}).forEach((r) => r.permissions.forEach((p) => s.add(`${p.resource}:${p.action}`)));
    return [...s].sort();
  });

  constructor() { this.load(); }
  async load() {
    this.error.set(null);
    try { this.m.set(await this.api.get<Matrix>('/role-matrix')); } catch (e) { this.error.set(message(e)); }
  }
  keys(o: object) { return Object.keys(o); }
  json(o: unknown) { return JSON.stringify(o); }
  scopes(role: string, ra: string) {
    const [res, act] = ra.split(':');
    return (this.m()?.roles[role].permissions || []).filter((p) => p.resource === res && p.action === act).map((p) => p.scope).join(', ');
  }
  fields(p: Perm) {
    if (!p.fields) return '–';
    if (Array.isArray(p.fields)) return p.fields.join(', ');
    const set = this.m()?.field_sets[p.fields];
    return set ? `${p.fields}: ${set.join(', ')}` : p.fields;
  }
}
