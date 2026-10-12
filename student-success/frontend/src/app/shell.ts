import { Component, computed, inject } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { AuthService } from './core/auth.service';
import { Session } from './core/session.service';

interface NavItem { path: string; label: string; show: boolean; }

/** Signed-in layout: navigation filtered by the user's permissions, dataset switch and sign out. */
@Component({
  selector: 'app-shell',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  template: `
    <a class="skip" href="#main">Skip to content</a>
    <div class="shell">
      <nav class="side" aria-label="Main">
        <div class="brand"><div class="brand-mark" aria-hidden="true">SC</div>
          <div>Smart Campus<small>Student success analytics</small></div></div>
        @for (g of groups(); track g.name) {
          @if (g.items.length) {
            <div class="nav-group">{{ g.name }}</div>
            @for (i of g.items; track i.path) {
              <a [routerLink]="i.path" routerLinkActive="active" [routerLinkActiveOptions]="{ exact: i.path === '/students' }">{{ i.label }}</a>
            }
          }
        }
      </nav>
      <div class="main">
        <header class="topbar">
          <span class="spacer"></span>
          <span class="small"><strong>{{ me()?.user?.display_name }}</strong>
            <span class="muted"> · {{ me()?.user?.role_labels?.join(', ') }}</span></span>
          @if (auth.config()?.mode === 'local-demo') { <span class="chip" title="Local development sign-in; refused in AWS">Local demo sign-in</span> }
          <button class="btn small" type="button" (click)="auth.signOut()">Sign out</button>
        </header>
        <main id="main" class="content" tabindex="-1">
          <router-outlet />
        </main>
      </div>
    </div>`,
})
export class Shell {
  session = inject(Session);
  auth = inject(AuthService);
  me = this.session.me;
  datasets = computed(() => this.me()?.datasets || []);

  groups = computed(() => {
    const c = (r: string, a: string) => this.session.can(r, a);
    const me = this.me();
    const staff = c('student_insight', 'read') && !this.session.isStudent();
    const own = me?.user.student;
    const g = (name: string, items: NavItem[]) => ({ name, items: items.filter((i) => i.show) });
    return [
      g('Insights', [
        { path: '/overview', label: 'Overview', show: staff },
        { path: '/insights', label: 'Insights & charts', show: staff },
        { path: '/students', label: 'Students', show: staff },
        { path: '/risk', label: 'Academic risk', show: staff && !this.only('placement_officer', 'activity_coordinator') },
        { path: '/placement', label: 'Placement readiness', show: staff && !this.only('activity_coordinator') },
        { path: '/segments', label: 'Segments', show: staff },
        { path: '/my', label: 'My dashboard', show: !!own },
        { path: own ? `/students/${own.dataset}/${own.student_id}` : '/', label: 'My full record', show: !!own },
      ]),
      g('Actions', [
        { path: '/entry', label: own && this.session.isStudent() ? 'Submit information' : 'Enter data',
          show: this.canEnter() },
        { path: '/imports', label: 'Import CSV / Excel', show: c('import', 'create') },
        { path: '/interventions', label: 'Interventions', show: c('intervention', 'read') && !this.session.isStudent() },
        { path: '/reviews', label: 'Approvals & verification', show: c('correction', 'read') || c('record.certification', 'verify') },
      ]),
      g('Governance', [
        { path: '/role-matrix', label: 'Role matrix', show: c('role_matrix', 'read') && !this.session.isStudent() },
        { path: '/admin/config', label: 'Configuration', show: c('scoring_config', 'read') || c('system_config', 'read') },
        { path: '/admin/users', label: this.session.isSysAdmin() ? 'Users and roles' : 'Mentor assignments',
          show: c('user_account', 'read') || c('mentor_assignment', 'assign') },
        { path: '/admin/audit', label: 'Audit history', show: c('audit.academic', 'read') || c('audit.technical', 'read') },
      ]),
      g('Account', [{ path: '/security', label: 'Security', show: true }]),
    ];
  });

  private only(...roles: string[]) {
    const r = this.session.roles();
    return [...r].every((x) => roles.includes(x));
  }
  private canEnter() {
    return (this.me()?.permissions || []).some((p) => p.startsWith('record.') && /:(create|update|submit)$/.test(p));
  }
}
