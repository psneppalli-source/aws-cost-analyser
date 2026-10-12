import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { AiHub, AiTool } from '../shared/ai-hub';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Api } from '../core/api.service';
import { Session } from '../core/session.service';
import { IV_CATEGORIES, OUTCOMES } from '../shared/labels';
import { RealEmpty, message } from '../shared/page';
import { StateView } from '../shared/ui';

interface Iv { intervention_id: string; student_id: string; student_name: string; dataset: string; department: string; year: number; title: string;
  category: string; status: string; owner_name: string; owner_sub: string; due_date: string; review_date: string; overdue: boolean; review_due: boolean;
  days_overdue: number; outcome?: { result: string } | null; }

@Component({
  selector: 'app-interventions-page',
  imports: [AiHub, FormsModule, RouterLink, StateView, RealEmpty],
  template: `
    <div class="page-head"><h1>Interventions</h1><span class="spacer"></span>
      <button class="btn small" type="button" (click)="load()" [disabled]="loading()">Refresh</button>
      <p class="sub">Support actions with owners, due and review dates, and recorded outcomes. Open a student to update one or add notes.</p></div>
    <form class="filters" (submit)="$event.preventDefault()">
      <label>Show<select name="m" [ngModel]="mine()" (ngModelChange)="mine.set($event)"><option [ngValue]="false">All I can see</option><option [ngValue]="true">Assigned to me</option></select></label>
      <label>Status<select name="s" [ngModel]="status()" (ngModelChange)="status.set($event)"><option value="">Any</option><option>Open</option><option>In Progress</option><option>Completed</option></select></label>
      <label>Department<select name="d" [ngModel]="dept()" (ngModelChange)="dept.set($event)"><option value="">All</option>@for (d of departments(); track d) { <option [value]="d">{{ d }}</option> }</select></label>
      <label class="check"><input type="checkbox" style="width:auto" name="o" [ngModel]="overdue()" (ngModelChange)="overdue.set($event)"> Overdue only</label>
    </form>
    <app-ai-hub [tools]="aiTools" [department]="dept()" />
    <app-real-empty [show]="!loading() && !items().length && !status() && !overdue()" />
    <section class="kpis" style="margin-bottom:14px">
      <div class="card kpi"><div class="label">Open</div><div class="value">{{ count('Open') }}</div></div>
      <div class="card kpi"><div class="label">In progress</div><div class="value">{{ count('In Progress') }}</div></div>
      <div class="card kpi"><div class="label">Overdue</div><div class="value">{{ overdueCount() }}</div></div>
      <div class="card kpi"><div class="label">Completed</div><div class="value">{{ count('Completed') }}</div><div class="note">{{ improved() }} with improved outcome</div></div>
    </section>
    <app-state [loading]="loading() && !items().length" [error]="error()" (retry)="load()" [empty]="!loading() && !items().length" emptyText="No interventions match." />
    @if (items().length) {
      <div class="card" style="padding:0"><div class="table-wrap"><table>
        <thead><tr><th>Student</th><th>Intervention</th><th>Owner</th><th>Due</th><th>Review</th><th>Status</th><th>Outcome</th></tr></thead>
        <tbody>@for (i of items(); track i.intervention_id) {
          <tr [class.overdue]="i.overdue"><td><a [routerLink]="['/students', i.dataset, i.student_id]">{{ i.student_name }}</a><br><span class="small muted">{{ i.department }} · Y{{ i.year }}</span></td>
            <td>{{ i.title }}<br><span class="small muted">{{ cat(i.category) }}</span></td><td>{{ i.owner_name }}</td>
            <td>{{ i.due_date }}@if (i.overdue) { <br><span class="badge high">▲ {{ i.days_overdue }}d overdue</span> }</td>
            <td>{{ i.review_date }}@if (i.review_due && !i.overdue) { <br><span class="badge medium">■ Review due</span> }</td>
            <td>{{ i.status }}</td><td>{{ i.outcome ? outcome(i.outcome.result) : '–' }}</td></tr>
        }</tbody></table></div></div>
      <p class="small muted">Outcomes are recorded by staff. A better score after an intervention is an association, not proof that the intervention caused it.</p>
    }`,
})
export class InterventionsPage {
  aiTools: AiTool[] = [{ kind: 'outcomes', label: "What's working", action: 'Summarise outcomes' }];
  private api = inject(Api);
  session = inject(Session);
  items = signal<Iv[]>([]);
  mine = signal(false);
  status = signal('');
  dept = signal('');
  overdue = signal(false);
  loading = signal(true);
  error = signal<string | null>(null);
  departments = computed(() => Object.keys(this.session.me()?.departments || {}));
  overdueCount = computed(() => this.items().filter((i) => i.overdue).length);
  improved = computed(() => this.items().filter((i) => i.outcome?.result === 'improved').length);

  constructor() { effect(() => { this.session.dataset(); this.mine(); this.status(); this.dept(); this.overdue(); untracked(() => this.load()); }); }
  count(s: string) { return this.items().filter((i) => i.status === s).length; }
  cat(c: string) { return IV_CATEGORIES[c] || c; }
  outcome(o: string) { return OUTCOMES[o] || o; }

  async load() {
    this.loading.set(true); this.error.set(null);
    try {
      this.items.set((await this.api.get<{ items: Iv[] }>('/interventions', { dataset: this.session.dataset(), owner: this.mine() ? 'me' : null,
        status: this.status(), department: this.dept(), overdue: this.overdue() || null, limit: 200 })).items);
    } catch (e) { this.error.set(message(e)); }
    finally { this.loading.set(false); }
  }
}
