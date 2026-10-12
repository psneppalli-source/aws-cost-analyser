import { Component, computed, inject, signal } from '@angular/core';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { AuthService } from './core/auth.service';
import { HelpWidget } from './shared/help-widget';
import { Session } from './core/session.service';

interface NavItem { path: string; label: string; show: boolean; }

/** Signed-in layout: navigation filtered by the user's permissions, dataset switch and sign out. */
@Component({
  selector: 'app-shell',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, HelpWidget],
  template: `
    <a class="skip" href="#main">Skip to content</a>
    <div class="shell">
      <nav class="side" aria-label="Main">
        <div class="side-head">
          <div class="brand"><div class="brand-mark" aria-hidden="true">SC</div>
            <div><span class="brand-name">Smart Campus</span><small>Student success analytics</small></div></div>
          <button class="menu-btn" type="button" (click)="open.set(!open())" [attr.aria-expanded]="open()" aria-controls="nav-links">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true">
              @if (open()) { <path d="M6 6l12 12M18 6L6 18"/> } @else { <path d="M4 7h16M4 12h16M4 17h16"/> }</svg>
            Menu</button>
        </div>
        <div class="nav-links" id="nav-links" [class.open]="open()">
          @for (g of groups(); track g.name) {
            @if (g.items.length) {
              <div class="nav-group">{{ g.name }}</div>
              @for (i of g.items; track i.path) {
                <a [routerLink]="i.path" routerLinkActive="active" [routerLinkActiveOptions]="{ exact: i.path === '/students' }" (click)="open.set(false)">
                  <svg class="ico" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path [attr.d]="icon(i.path)"/></svg>
                  <span>{{ i.label }}</span></a>
              }
            }
          }
          <div class="side-user">
            <span class="avatar" aria-hidden="true">{{ initials() }}</span>
            <span class="side-who"><strong>{{ shortName() }}</strong><small>{{ me()?.user?.role_labels?.join(', ') }}</small></span>
            <button class="side-out" type="button" (click)="auth.signOut()" title="Sign out" aria-label="Sign out">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4M10 17l5-5-5-5M15 12H3"/></svg></button>
          </div>
        </div>
      </nav>
      <div class="main">
        <header class="topbar">
          <div class="crumb"><span class="crumb-title">{{ greeting() }}, {{ firstName() }}</span>
            @if (me()?.current_period) { <span class="period-pill">Reporting period · {{ month(me()!.current_period) }}</span> }</div>
          <span class="spacer"></span>
          @if (auth.config()?.mode === 'local-demo') { <span class="chip" title="Local development sign-in; refused in AWS">Local demo sign-in</span> }
          <span class="who-chip"><span class="avatar sm" aria-hidden="true">{{ initials() }}</span>
            <span class="who"><strong>{{ shortName() }}</strong><span class="role">{{ me()?.user?.role_labels?.join(', ') }}</span></span></span>
          <button class="btn small only-phone" type="button" (click)="auth.signOut()">Sign out</button>
        </header>
        <main id="main" class="content" tabindex="-1">
          <router-outlet />
        </main>
        <app-help-widget />
      </div>
    </div>`,
})
export class Shell {
  session = inject(Session);
  auth = inject(AuthService);
  me = this.session.me;
  open = signal(false);   // phone menu
  private router = inject(Router);
  private url = signal(this.router.url);
  /** Display name without the role suffix some accounts carry, e.g. "Priya Raman (College Administrator)". */
  shortName = computed(() => (this.me()?.user?.display_name || '').replace(/\s*\(.*\)\s*$/, ''));
  initials = computed(() => this.shortName().split(/\s+/).filter((w) => /^[A-Za-z]/.test(w) && !/^(Dr|Prof|Mr|Mrs|Ms)$/i.test(w))
    .slice(0, 2).map((w) => w[0].toUpperCase()).join('') || 'SC');
  title = computed(() => {
    const u = this.url().split('?')[0];
    for (const g of this.groups()) for (const i of g.items) if (u === i.path || (i.path !== '/' && u.startsWith(i.path + '/') && i.path !== '/students')) return i.label;
    return u.startsWith('/students/') ? 'Student profile' : 'Smart Campus';
  });
  firstName = computed(() => this.shortName().split(/\s+/).find((w) => !/^(Dr|Prof|Mr|Mrs|Ms)\.?$/i.test(w)) || '');
  greeting() { const h = new Date().getHours(); return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'; }
  month(p: string) { return new Date(p + '-01').toLocaleString(undefined, { month: 'short', year: 'numeric' }); }
  constructor() { this.router.events.subscribe((e) => { if (e instanceof NavigationEnd) this.url.set(e.urlAfterRedirects); }); }

  /** Simple line icons (24px grid) for the navigation. */
  icon(path: string): string {
    const p = path.startsWith('/students/') ? '/record' : path;
    const I: Record<string, string> = {
      '/overview': 'M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z',
      '/insights': 'M3 3v18h18M7 15l4-4 3 3 6-6',
      '/students': 'M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2M9 11a4 4 0 100-8 4 4 0 000 8zM22 21v-2a4 4 0 00-3-3.9M16 3.1a4 4 0 010 7.8',
      '/risk': 'M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0zM12 9v4M12 17h.01',
      '/placement': 'M3 7h18v13H3zM8 7V5a2 2 0 012-2h4a2 2 0 012 2v2M3 13h18',
      '/segments': 'M12 2l10 5-10 5L2 7zM2 17l10 5 10-5M2 12l10 5 10-5',
      '/my': 'M3 11l9-8 9 8v10a1 1 0 01-1 1h-5v-7H9v7H4a1 1 0 01-1-1z',
      '/record': 'M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8zM14 2v6h6M8 13h8M8 17h5',
      '/entry': 'M12 20h9M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z',
      '/imports': 'M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12',
      '/interventions': 'M20.8 4.6a5.5 5.5 0 00-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 00-7.8 7.8l1 1.1L12 21l7.8-7.5 1-1.1a5.5 5.5 0 000-7.8z',
      '/reviews': 'M22 11.1V12a10 10 0 11-5.9-9.1M22 4L12 14l-3-3',
      '/role-matrix': 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z',
      '/admin/config': 'M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6',
      '/admin/users': 'M16 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2M8.5 11a4 4 0 100-8 4 4 0 000 8zM20 8v6M23 11h-6',
      '/admin/audit': 'M3 12a9 9 0 109-9 9.7 9.7 0 00-6.7 2.7L3 8M3 3v5h5M12 7v5l4 2',
      '/security': 'M5 11h14v10H5zM8 11V7a4 4 0 018 0v4',
    };
    return I[p] || 'M12 12m-9 0a9 9 0 1018 0 9 9 0 10-18 0';
  }
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
        { path: '/admin/users', label: c('user_account', 'read') ? 'Users and roles' : 'Mentor assignments',
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
