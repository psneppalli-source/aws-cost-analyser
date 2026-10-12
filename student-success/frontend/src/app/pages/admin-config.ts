import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../core/api.service';
import { Session } from '../core/session.service';
import { COMPONENTS, when } from '../shared/labels';
import { message } from '../shared/page';
import { StateView } from '../shared/ui';

interface Rule { id: string; indicator: string; op: string; value: number; level: string; label: string; intervention: string; }
interface Config { version: string; description: string; coverage_threshold: number; components: Record<string, { weight: number; label?: string }>;
  bands: { label: string; min: number }[] | Record<string, number>; risk: { assumption_notice: string; academic: { rules: Rule[] }; placement: { rules: Rule[] } }; [k: string]: unknown; }
interface Version { config_version: string; status: string; reason: string; proposed_by: string; approved_by: string | null; created_at: string; approved_at: string | null; description: string; }

@Component({
  selector: 'app-admin-config-page',
  imports: [FormsModule, StateView],
  template: `
    <div class="page-head"><h1>Configuration</h1>
      <p class="sub">Scoring weights and risk thresholds are versioned. Changes are proposed with a reason, approved, and then applied by recalculation.</p></div>
    @if (notice()) { <p class="banner" role="status">{{ notice() }}</p> }

    @if (session.can('scoring_config', 'read')) {
      <app-state [loading]="!cfg() && !error()" [error]="error()" (retry)="load()" />
      @if (cfg(); as c) {
        <div class="grid g2 top">
          <section class="card"><div class="card-head"><h2>Active scoring v{{ c.version }}</h2></div>
            <p class="small">{{ c.description }}</p>
            <div class="table-wrap"><table><thead><tr><th>Component</th><th class="num">Weight</th></tr></thead>
              <tbody>@for (k of compKeys(c); track k) { <tr><td>{{ label(k) }}</td><td class="num">{{ c.components[k].weight }}</td></tr> }</tbody></table></div>
            <p class="small">Minimum data coverage for a Success Score: <strong>{{ c.coverage_threshold * 100 }}%</strong>. Below it the status is “Insufficient data”.</p>
          </section>
          <section class="card"><div class="card-head"><h2>Risk thresholds</h2></div>
            <p class="banner warn small">{{ c.risk.assumption_notice }}</p>
            @for (k of ['academic', 'placement']; track k) {
              <h3 style="margin-top:10px">{{ k === 'academic' ? 'Academic' : 'Placement' }}</h3>
              <div class="table-wrap"><table><thead><tr><th>Rule</th><th>Condition</th><th>Level</th></tr></thead>
                <tbody>@for (r of rules(c, k); track r.id) { <tr><td class="mono">{{ r.id }}</td><td>{{ r.indicator }} {{ r.op }} {{ r.value }}</td><td>{{ r.level }}</td></tr> }</tbody></table></div>
            }
          </section>
        </div>
        <section class="card" style="margin-top:16px"><div class="card-head"><h2>Versions</h2></div>
          <div class="table-wrap"><table><thead><tr><th>Version</th><th>Status</th><th>Reason</th><th>Proposed</th><th>Approved</th><th></th></tr></thead>
            <tbody>@for (v of versions(); track v.config_version) {
              <tr><td class="mono">{{ v.config_version }}</td><td>{{ v.config_version === c.version ? 'Active' : v.status }}</td><td class="small">{{ v.reason }}</td>
                <td class="small">{{ v.proposed_by }} · {{ when(v.created_at) }}</td><td class="small">{{ v.approved_by || '–' }}@if (v.approved_at) { · {{ when(v.approved_at) }} }</td>
                <td>@if (session.can('scoring_config', 'activate') && v.config_version !== c.version) { <button class="btn small" type="button" (click)="activateVersion = v.config_version">Activate…</button> }</td></tr>
            }</tbody></table></div>
          @if (activateVersion) {
            <form class="row" style="gap:6px;margin-top:10px" (submit)="$event.preventDefault(); activate()">
              <label class="field" style="flex:1">Reason for activating v{{ activateVersion }}<input name="ar" [(ngModel)]="activateReason" required minlength="5"></label>
              <button class="btn primary" type="submit" [disabled]="busy()">Activate</button><button class="btn" type="button" (click)="activateVersion = ''">Cancel</button>
            </form>
            <p class="small muted">Activating marks every student for recalculation; run it below.</p>
          }
        </section>
        @if (session.can('scoring_config', 'propose')) {
          <section class="card" style="margin-top:16px"><div class="card-head"><h2>Propose a new version</h2>
            <span class="desc">Edit weights, coverage threshold or rule values. Weights must add up to 100.</span></div>
            <details><summary>Edit</summary>
              <form class="stack" (submit)="$event.preventDefault(); propose()">
                <label class="field">Configuration (JSON)<textarea name="j" [(ngModel)]="draft" rows="16" class="mono" spellcheck="false"></textarea></label>
                <label class="field">Reason<input name="r" [(ngModel)]="reason" required minlength="5"></label>
                <div><button class="btn primary" type="submit" [disabled]="busy()">Propose</button></div>
              </form></details>
          </section>
        }
      }
    }

    @if (session.can('insight', 'recompute')) {
      <section class="card" style="margin-top:16px"><div class="card-head"><h2>Recalculation</h2>
        <span class="desc">Scores recalculate when data changes. If something was interrupted, students stay marked and are repaired here. Runs only when you ask.</span></div>
        <div class="row" style="gap:8px">
          <button class="btn primary" type="button" (click)="recompute(false)" [disabled]="busy()">Repair pending</button>
          <button class="btn" type="button" (click)="recompute(true)" [disabled]="busy()">Recalculate everyone</button>
        </div>
        @if (recalc()) { <p class="small" role="status">{{ recalc() }}</p> }
      </section>
    }

    @if (session.can('system_config', 'read')) {
      <section class="card" style="margin-top:16px"><div class="card-head"><h2>Platform settings</h2></div>
        @if (sys(); as s) {
          <label class="row" style="gap:8px"><input type="checkbox" style="width:auto" [checked]="s.require_second_approver" [disabled]="!session.can('system_config', 'update') || busy()"
            (change)="setSecondApprover($any($event.target).checked)"> Require a second administrator to activate scoring changes</label>
        }
      </section>
    }`,
})
export class AdminConfigPage {
  private api = inject(Api);
  session = inject(Session);
  when = when;
  cfg = signal<Config | null>(null);
  versions = signal<Version[]>([]);
  sys = signal<{ require_second_approver: boolean; version: number } | null>(null);
  error = signal<string | null>(null);
  notice = signal<string | null>(null);
  recalc = signal<string | null>(null);
  busy = signal(false);
  draft = '';
  reason = '';
  activateVersion = '';
  activateReason = '';
  recalcDs = 'real';

  constructor() { this.load(); }

  compKeys(c: Config) { return Object.keys(c.components); }
  label(k: string) { return COMPONENTS[k] || k; }
  rules(c: Config, k: string) { return (c.risk as unknown as Record<string, { rules: Rule[] }>)[k]?.rules || []; }

  async load() {
    this.error.set(null);
    try {
      if (this.session.can('scoring_config', 'read')) {
        const r = await this.api.get<{ active: Config; versions: Version[] }>('/config/scoring');
        this.cfg.set(r.active); this.versions.set(r.versions);
        const next = { ...r.active, version: this.bump(r.active.version, r.versions.map((v) => v.config_version)), status: 'draft' };
        this.draft = JSON.stringify(next, null, 2);
      }
      if (this.session.can('system_config', 'read')) this.sys.set(await this.api.get('/system/config'));
    } catch (e) { this.error.set(message(e)); }
  }

  private bump(v: string, taken: string[]) {
    const [a, b] = v.split('.').map(Number);
    let n = b + 1;
    while (taken.includes(`${a}.${n}.0`)) n++;
    return `${a}.${n}.0`;
  }

  private async act(fn: () => Promise<string>) {
    this.busy.set(true); this.notice.set(null);
    try { this.notice.set(await fn()); await this.load(); } catch (e) { this.notice.set(message(e)); }
    finally { this.busy.set(false); }
  }

  propose() {
    return this.act(async () => {
      let config: unknown;
      try { config = JSON.parse(this.draft); } catch { throw new Error('The configuration is not valid JSON.'); }
      await this.api.post('/config/scoring/propose', { config, reason: this.reason });
      this.reason = '';
      return 'Proposed. An administrator can now activate it.';
    });
  }
  activate() {
    return this.act(async () => {
      await this.api.post('/config/scoring/activate', { version: this.activateVersion, reason: this.activateReason });
      const v = this.activateVersion;
      this.activateVersion = ''; this.activateReason = '';
      return `Version ${v} is active. Run “Recalculate everyone” to apply it.`;
    });
  }
  async recompute(all: boolean) {
    this.busy.set(true); this.recalc.set('Working…');
    let total = 0, failed = 0;
    try {
      for (let i = 0; i < 40; i++) {
        const r = await this.api.post<{ recomputed: number; failed: number; remaining: number }>('/admin/recompute', { dataset: this.recalcDs, all: all && i === 0 });
        total += r.recomputed; failed += r.failed;
        this.recalc.set(`${total} recalculated, ${failed} failed, ${r.remaining} remaining…`);
        if (!r.remaining) break;
      }
      this.recalc.set(`Done: ${total} recalculated, ${failed} failed.`);
    } catch (e) { this.recalc.set(message(e)); }
    finally { this.busy.set(false); }
  }
  setSecondApprover(on: boolean) {
    return this.act(async () => {
      this.sys.set(await this.api.put('/system/config', { require_second_approver: on, version: this.sys()?.version }));
      return 'Saved.';
    });
  }
}
