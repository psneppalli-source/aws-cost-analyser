import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../core/api.service';
import { AuthService } from '../core/auth.service';
import { Session } from '../core/session.service';
import { ROLES, when } from '../shared/labels';
import { message } from '../shared/page';
import { StateView } from '../shared/ui';

interface User { sub: string; username: string; display_name: string; email: string | null; status: string; roles: string[]; departments: string[];
  student: { dataset: string; student_id: string } | null; created_at: string; version: number; }
interface Staff { sub: string; display_name: string; roles: string[]; }
interface Edit { roles: Record<string, boolean>; department: string; dataset: string; student_id: string; }

@Component({
  selector: 'app-users-page',
  imports: [FormsModule, StateView],
  template: `
    <div class="page-head"><h1>{{ sysAdmin() ? 'Users and roles' : 'Mentor assignments' }}</h1>
      <p class="sub">@if (sysAdmin()) { Accounts are created by the System Administrator only; there is no public registration. Role assignments are stored
        server-side against the account and checked on every request. You can't change your own roles, and the System Administrator role can't be combined with student-data roles. }
        @else { Assign subjects to faculty. Assign mentors to individual students from their profile. }</p></div>
    @if (notice()) { <p class="banner" role="status">{{ notice() }}</p> }
    @if (temp(); as t) {
      <p class="banner warn" role="alert"><strong>Temporary password for {{ t.username }}:</strong> <span class="mono">{{ t.password }}</span><br>
        Share it securely; it is shown once and the user must change it at first sign-in. <button class="btn small" type="button" (click)="temp.set(null)">I've recorded it</button></p>
    }

    @if (sysAdmin()) {
      <section class="card"><div class="card-head"><h2>Create account</h2></div>
        <form class="form-grid" (submit)="$event.preventDefault(); create()">
          <label class="field">Username<input name="u" [(ngModel)]="nu.username" required autocomplete="off"></label>
          <label class="field">Display name<input name="d" [(ngModel)]="nu.display_name" required></label>
          <label class="field">Email<input name="e" type="email" [(ngModel)]="nu.email"></label>
          <div class="field"><span>&nbsp;</span><button class="btn primary" type="submit" [disabled]="busy()">Create</button></div>
        </form>
        @if (auth.config()?.mode !== 'cognito') { <p class="small muted">Local demo mode: accounts are local only and sign in from the persona list.</p> }
      </section>
      <app-state [loading]="loading()" [error]="error()" (retry)="load()" />
      <div class="card" style="padding:0;margin-top:16px"><div class="table-wrap"><table>
        <thead><tr><th>User</th><th>Roles</th><th>Status</th><th>Created</th><th></th></tr></thead>
        <tbody>@for (u of users(); track u.sub) {
          <tr><td><strong>{{ u.display_name }}</strong><br><span class="mono small muted">{{ u.username }}</span></td>
            <td class="small">{{ roleText(u) }}</td><td>{{ u.status }}</td><td class="small">{{ when(u.created_at) }}</td>
            <td class="row" style="gap:4px">@if (u.sub !== me()) {
              <button class="btn small" type="button" (click)="startEdit(u)">Roles</button>
              <button class="btn small" type="button" (click)="toggle(u)" [disabled]="busy()">{{ u.status === 'active' ? 'Disable' : 'Enable' }}</button> }
              @else { <span class="small muted">You</span> }</td></tr>
          @if (editing() === u.sub) {
            <tr><td colspan="5">
              <form class="stack" (submit)="$event.preventDefault(); saveRoles(u)">
                <div class="row" style="gap:14px;flex-wrap:wrap">@for (r of roleKeys; track r) {
                  <label class="row small" style="gap:4px"><input type="checkbox" style="width:auto" [name]="'r' + r" [(ngModel)]="edit.roles[r]">{{ roleLabel(r) }}</label> }</div>
                @if (edit.roles['hod']) { <label class="field">HOD department<select name="hd" [(ngModel)]="edit.department">@for (d of departments(); track d) { <option [value]="d">{{ d }}</option> }</select></label> }
                @if (edit.roles['student']) { <div class="row" style="gap:8px">
                  <label class="field">Student ID<input name="si" [(ngModel)]="edit.student_id" placeholder="CSE24001"></label></div> }
                <div class="row" style="gap:6px"><button class="btn primary small" type="submit" [disabled]="busy()">Save roles</button>
                  <button class="btn small" type="button" (click)="editing.set(null)">Cancel</button></div>
              </form></td></tr>
          }
        }</tbody></table></div></div>
    }

    @if (session.can('mentor_assignment', 'assign')) {
      <section class="card" style="margin-top:16px"><div class="card-head"><h2>Subject assignments</h2></div>
        <div class="form-grid">
          <label class="field">Faculty member<select [(ngModel)]="mentor" name="m" (ngModelChange)="loadAssignments()"><option value="">Choose…</option>
            @for (s of mentors(); track s.sub) { <option [value]="s.sub">{{ s.display_name }}</option> }</select></label>
        </div>
        @if (mentor) {
          <h3 style="margin-top:12px">Teaches</h3>
          <ul>@for (a of assigned().subjects; track a.department + a.year + a.subject) {
            <li>{{ a.department }} Y{{ a.year }} · {{ a.subject }} <button class="btn small" type="button" (click)="subject(a.department, a.year, a.subject, true)" [disabled]="busy()">Remove</button></li>
          } @empty { <li class="muted">No subjects.</li> }</ul>
          <p class="small muted">Mentees: {{ assigned().mentees.length }} student(s).</p>
          <form class="row" style="gap:6px;flex-wrap:wrap" (submit)="$event.preventDefault(); subject(sd, +sy, ss, false)">
            <select [(ngModel)]="sd" name="sd" aria-label="Department">@for (d of departments(); track d) { <option [value]="d">{{ d }}</option> }</select>
            <select [(ngModel)]="sy" name="sy" aria-label="Year">@for (y of ['1','2','3','4']; track y) { <option [value]="y">Year {{ y }}</option> }</select>
            <select [(ngModel)]="ss" name="ss" aria-label="Subject">@for (s of subjects(); track s) { <option [value]="s">{{ s }}</option> }</select>
            <button class="btn small primary" type="submit" [disabled]="busy() || !ss">Assign subject</button></form>
        }
      </section>
    }`,
})
export class UsersPage {
  private api = inject(Api);
  auth = inject(AuthService);
  session = inject(Session);
  when = when;
  roleKeys = Object.keys(ROLES);
  users = signal<User[]>([]);
  staff = signal<Staff[]>([]);
  assigned = signal<{ mentees: unknown[]; subjects: { department: string; year: number; subject: string }[] }>({ mentees: [], subjects: [] });
  loading = signal(false);
  busy = signal(false);
  error = signal<string | null>(null);
  notice = signal<string | null>(null);
  temp = signal<{ username: string; password: string } | null>(null);
  editing = signal<string | null>(null);
  edit: Edit = { roles: {}, department: '', dataset: 'real', student_id: '' };
  nu = { username: '', display_name: '', email: '' };
  mentor = '';
  sd = '';
  sy = '1';
  ss = '';
  sysAdmin = computed(() => this.session.can('user_account', 'read'));
  me = computed(() => this.session.me()?.user.sub);
  departments = computed(() => Object.keys(this.session.me()?.departments || {}));
  mentors = computed(() => this.staff().filter((s) => s.roles.includes('mentor')));

  constructor() {
    this.sd = this.departments()[0] || '';
    this.load();
  }

  subjects() { return this.session.me()?.departments[this.sd]?.subjects[this.sy] || []; }
  roleLabel(r: string) { return ROLES[r] || r; }
  roleText(u: User) {
    return (u.roles || []).map((r) => r === 'hod' ? `HOD (${u.departments.join(', ')})` : r === 'student' && u.student ? `Student ${u.student.student_id} (${u.student.dataset})` : this.roleLabel(r)).join(', ') || 'No roles';
  }

  async load() {
    this.loading.set(true); this.error.set(null);
    try {
      if (this.sysAdmin()) this.users.set((await this.api.get<{ items: User[] }>('/users')).items);
      if (this.session.can('mentor_assignment', 'assign')) this.staff.set((await this.api.get<{ items: Staff[] }>('/staff', { role: 'mentor' })).items);
    } catch (e) { this.error.set(message(e)); }
    finally { this.loading.set(false); }
  }

  private async act(fn: () => Promise<string>) {
    this.busy.set(true); this.notice.set(null);
    try { this.notice.set(await fn()); } catch (e) { this.notice.set(message(e)); }
    finally { this.busy.set(false); }
  }

  create() {
    return this.act(async () => {
      const r = await this.api.post<User & { temporary_password?: string }>('/users', this.nu);
      if (r.temporary_password) this.temp.set({ username: r.username, password: r.temporary_password });
      this.nu = { username: '', display_name: '', email: '' };
      await this.load();
      return `Created ${r.username}. Assign roles next.`;
    });
  }

  startEdit(u: User) {
    this.edit = { roles: Object.fromEntries(u.roles.map((r) => [r, true])), department: u.departments[0] || this.departments()[0],
      dataset: 'real', student_id: u.student?.student_id || '' };
    this.editing.set(u.sub);
  }

  saveRoles(u: User) {
    return this.act(async () => {
      const assignments = Object.entries(this.edit.roles).filter(([, on]) => on).map(([role]) =>
        role === 'hod' ? { role, department: this.edit.department } : role === 'student' ? { role, dataset: this.edit.dataset, student_id: this.edit.student_id } : { role });
      await this.api.put(`/users/${encodeURIComponent(u.sub)}/roles`, { assignments, version: u.version });
      this.editing.set(null);
      await this.load();
      return `Roles updated for ${u.username}.`;
    });
  }

  toggle(u: User) {
    return this.act(async () => {
      await this.api.put(`/users/${encodeURIComponent(u.sub)}/status`, { status: u.status === 'active' ? 'disabled' : 'active', version: u.version });
      await this.load();
      return `${u.username} is now ${u.status === 'active' ? 'disabled' : 'active'}.`;
    });
  }

  async loadAssignments() {
    if (!this.mentor) return;
    try { this.assigned.set(await this.api.get(`/assignments/${encodeURIComponent(this.mentor)}`)); } catch (e) { this.notice.set(message(e)); }
  }

  subject(department: string, year: number, subject: string, remove: boolean) {
    return this.act(async () => {
      await this.api.post('/assignments/subjects', { mentor_sub: this.mentor, department, year, subject, remove });
      await this.loadAssignments();
      return remove ? 'Subject removed.' : 'Subject assigned.';
    });
  }
}
