import { Component, effect, inject, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Api } from '../core/api.service';
import { Session } from '../core/session.service';
import { when } from '../shared/labels';
import { message } from '../shared/page';
import { StateView } from '../shared/ui';

interface Correction { correction_id: string; student_id: string; student_name: string; dataset: string; department: string; year: number; category: string;
  period: string; current: Record<string, unknown>; proposed: Record<string, unknown>; requested_by_name: string; requested_at: string; status: string; }
interface Pending { record_key: string; student_id: string; dataset: string; department: string; year: number; category: string; period: string;
  name?: string; issuer?: string; evidence_ref?: string; activity_type?: string; role?: string; version: number; updated_at: string; }

@Component({
  selector: 'app-reviews-page',
  imports: [FormsModule, RouterLink, StateView],
  template: `
    <div class="page-head"><h1>Approvals and verification</h1><span class="spacer"></span>
      <button class="btn small" type="button" (click)="load()">Refresh</button>
      <p class="sub">Changes to saved marks, attendance and results need a second person. Student submissions count only after verification.</p></div>
    @if (notice()) { <p class="banner" role="status">{{ notice() }}</p> }
    @if (canApprove || session.can('correction', 'read')) {
      <section class="card"><div class="card-head"><h2>Correction requests</h2></div>
        <app-state [loading]="loading()" [error]="error()" (retry)="load()" [empty]="!loading() && !corrections().length" emptyText="No pending corrections." />
        @if (corrections().length) {
          <div class="table-wrap"><table><thead><tr><th>Student</th><th>Record</th><th>Current</th><th>Proposed</th><th>Requested</th>@if (canApprove) { <th>Decision</th> }</tr></thead>
            <tbody>@for (c of corrections(); track c.correction_id) {
              <tr><td><a [routerLink]="['/students', c.dataset, c.student_id]">{{ c.student_name }}</a><br><span class="mono small muted">{{ c.student_id }}</span></td>
                <td>{{ c.category }} · {{ c.period }}</td><td class="small mono">{{ fmt(c.current) }}</td><td class="small mono">{{ fmt(c.proposed) }}</td>
                <td class="small">{{ c.requested_by_name }}<br>{{ when(c.requested_at) }}</td>
                @if (canApprove) { <td><input [(ngModel)]="reasons[c.correction_id]" [name]="'r' + c.correction_id" placeholder="Reason (optional)" aria-label="Reason">
                  <div class="row" style="gap:4px;margin-top:4px"><button class="btn small primary" type="button" (click)="decide(c, true)" [disabled]="busy()">Approve</button>
                  <button class="btn small" type="button" (click)="decide(c, false)" [disabled]="busy()">Reject</button></div></td> }</tr>
            }</tbody></table></div>
        }
      </section>
    }
    @if (canVerify) {
      <section class="card" style="margin-top:16px"><div class="card-head"><h2>Submissions awaiting verification</h2></div>
        <app-state [loading]="loading()" [empty]="!loading() && !pending().length" emptyText="Nothing waiting for verification." />
        @if (pending().length) {
          <div class="table-wrap"><table><thead><tr><th>Student</th><th>Type</th><th>Details</th><th>Period</th><th>Submitted</th><th>Decision</th></tr></thead>
            <tbody>@for (r of pending(); track r.record_key + r.student_id) {
              <tr><td><a [routerLink]="['/students', r.dataset, r.student_id]">{{ r.student_id }}</a><br><span class="small muted">{{ r.department }} · Y{{ r.year }}</span></td>
                <td>{{ r.category }}</td><td>{{ r.name }}@if (r.issuer) { · {{ r.issuer }} }@if (r.evidence_ref) { <br><span class="small mono">{{ r.evidence_ref }}</span> }</td>
                <td>{{ r.period }}</td><td class="small">{{ when(r.updated_at) }}</td>
                <td class="row" style="gap:4px"><button class="btn small primary" type="button" (click)="verify(r, 'verified')" [disabled]="busy()">Verify</button>
                  <button class="btn small" type="button" (click)="verify(r, 'rejected')" [disabled]="busy()">Reject</button></td></tr>
            }</tbody></table></div>
        }
      </section>
    }`,
})
export class ReviewsPage {
  private api = inject(Api);
  session = inject(Session);
  when = when;
  corrections = signal<Correction[]>([]);
  pending = signal<Pending[]>([]);
  loading = signal(true);
  busy = signal(false);
  error = signal<string | null>(null);
  notice = signal<string | null>(null);
  reasons: Record<string, string> = {};
  canApprove = this.session.can('correction', 'approve');
  canVerify = this.session.can('record.certification', 'verify') || this.session.can('record.engagement', 'verify');

  constructor() { effect(() => { this.session.dataset(); untracked(() => this.load()); }); }
  fmt(o: Record<string, unknown>) { return Object.entries(o || {}).map(([k, v]) => `${k}: ${v}`).join(', '); }

  async load() {
    this.loading.set(true); this.error.set(null);
    const ds = this.session.dataset();
    try {
      const [c, v] = await Promise.all([
        this.session.can('correction', 'read') ? this.api.get<{ items: Correction[] }>('/corrections', { dataset: ds }) : Promise.resolve({ items: [] }),
        this.canVerify ? this.api.get<{ items: Pending[] }>('/verifications', { dataset: ds }) : Promise.resolve({ items: [] }),
      ]);
      this.corrections.set(c.items); this.pending.set(v.items);
    } catch (e) { this.error.set(message(e)); }
    finally { this.loading.set(false); }
  }

  async decide(c: Correction, approve: boolean) {
    await this.act(() => this.api.post(`/students/${c.dataset}/${c.student_id}/corrections/${c.correction_id}`, { approve, reason: this.reasons[c.correction_id] || '' }),
      approve ? 'Correction approved and applied.' : 'Correction rejected.');
  }
  async verify(r: Pending, decision: string) {
    await this.act(() => this.api.post(`/students/${r.dataset}/${r.student_id}/verify`, { category: r.category, record_key: r.record_key, decision, version: r.version }),
      decision === 'verified' ? 'Verified; the score will include it.' : 'Rejected.');
  }
  private async act(fn: () => Promise<unknown>, ok: string) {
    this.busy.set(true); this.notice.set(null);
    try { await fn(); this.notice.set(ok); } catch (e) { this.notice.set(message(e)); }
    finally { this.busy.set(false); await this.load(); }
  }
}
