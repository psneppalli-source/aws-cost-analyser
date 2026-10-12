import { Routes } from '@angular/router';
import { landing, needs, signedIn } from './core/guards';
import { Shell } from './shell';

export const routes: Routes = [
  { path: 'login', title: 'Sign in · Smart Campus', loadComponent: () => import('./pages/login').then((m) => m.LoginPage) },
  {
    path: '', component: Shell, canActivate: [signedIn], children: [
      { path: '', pathMatch: 'full', canActivate: [landing], children: [] },
      { path: 'overview', title: 'Overview', canActivate: [needs('student_insight:read')],
        loadComponent: () => import('./pages/overview').then((m) => m.OverviewPage) },
      { path: 'insights', title: 'Insights', canActivate: [needs('student_insight:read')],
        loadComponent: () => import('./pages/insights').then((m) => m.InsightsPage) },
      { path: 'students', title: 'Students', canActivate: [needs('student_insight:read')],
        loadComponent: () => import('./pages/students').then((m) => m.StudentsPage) },
      { path: 'students/:dataset/:sid', title: 'Student profile',
        loadComponent: () => import('./pages/profile').then((m) => m.ProfilePage) },
      { path: 'risk', title: 'Academic risk', canActivate: [needs('student_insight:read')],
        loadComponent: () => import('./pages/risk').then((m) => m.RiskPage) },
      { path: 'placement', title: 'Placement readiness', canActivate: [needs('student_insight:read')],
        loadComponent: () => import('./pages/placement').then((m) => m.PlacementPage) },
      { path: 'segments', title: 'Segments', canActivate: [needs('student_insight:read')],
        loadComponent: () => import('./pages/segments').then((m) => m.SegmentsPage) },
      { path: 'entry', title: 'Enter data',
        loadComponent: () => import('./pages/entry').then((m) => m.EntryPage) },
      { path: 'imports', title: 'Imports', canActivate: [needs('import:create', 'import:read')],
        loadComponent: () => import('./pages/imports').then((m) => m.ImportsPage) },
      { path: 'interventions', title: 'Interventions', canActivate: [needs('intervention:read')],
        loadComponent: () => import('./pages/interventions').then((m) => m.InterventionsPage) },
      { path: 'reviews', title: 'Reviews', canActivate: [needs('correction:read', 'record.certification:verify')],
        loadComponent: () => import('./pages/reviews').then((m) => m.ReviewsPage) },
      { path: 'role-matrix', title: 'Role matrix', canActivate: [needs('role_matrix:read')],
        loadComponent: () => import('./pages/role-matrix').then((m) => m.RoleMatrixPage) },
      { path: 'admin/config', title: 'Configuration', canActivate: [needs('scoring_config:read', 'system_config:read')],
        loadComponent: () => import('./pages/admin-config').then((m) => m.AdminConfigPage) },
      { path: 'admin/audit', title: 'Audit history', canActivate: [needs('audit.academic:read', 'audit.technical:read')],
        loadComponent: () => import('./pages/audit').then((m) => m.AuditPage) },
      { path: 'admin/users', title: 'Users and roles', canActivate: [needs('user_account:read', 'mentor_assignment:read')],
        loadComponent: () => import('./pages/users').then((m) => m.UsersPage) },
    ],
  },
  { path: '**', redirectTo: '' },
];
