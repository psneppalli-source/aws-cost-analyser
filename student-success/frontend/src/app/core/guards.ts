import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from './auth.service';
import { Session } from './session.service';

/** Signed in, with the user's assignments loaded from the server (the source of truth for access). */
export const signedIn: CanActivateFn = async () => {
  const auth = inject(AuthService);
  const session = inject(Session);
  const router = inject(Router);
  if (!(await auth.token())) return router.parseUrl('/login');
  if (!session.me()) {
    try { await session.load(); } catch { return router.parseUrl('/login'); }
  }
  return true;
};

/** Route-level convenience only; the API enforces every permission. */
export function needs(...perms: string[]): CanActivateFn {
  return () => {
    const s = inject(Session);
    return perms.some((p) => { const [r, a] = p.split(':'); return s.can(r, a); }) || inject(Router).parseUrl('/');
  };
}

/** Send each role to its natural landing page. */
export const landing: CanActivateFn = () => {
  const s = inject(Session);
  const r = inject(Router);
  const me = s.me();
  if (!me) return r.parseUrl('/login');
  if (s.isSysAdmin() && me.user.roles.length === 1) return r.parseUrl('/admin/users');
  if (me.user.student && me.user.roles.length === 1) return r.parseUrl(`/students/${me.user.student.dataset}/${me.user.student.student_id}`);
  return r.parseUrl('/overview');
};
