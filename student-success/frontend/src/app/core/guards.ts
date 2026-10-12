import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from './auth.service';
import { Session } from './session.service';

/** Signed in, with the user's assignments loaded from the server (the source of truth for access). */
export const signedIn: CanActivateFn = async (_route, state) => {
  const auth = inject(AuthService);
  const session = inject(Session);
  const router = inject(Router);
  // visitors who aren't signed in see the home page first; deep links go straight to sign-in
  if (!(await auth.token())) return router.parseUrl(state.url === '/' || state.url === '' ? '/home' : '/login');
  if (!session.me()) {
    try { await session.load(); } catch { return router.parseUrl('/login'); }
  }
  return true;
};

/** Until a required authenticator is set up, every page leads to the Security page. */
export const mfaReady: CanActivateFn = (_r, state) => {
  const s = inject(Session);
  return !s.mfaPending() || state.url.startsWith('/security') || inject(Router).parseUrl('/security');
};

/** Route-level convenience only; the API enforces every permission. */
export function needs(...perms: string[]): CanActivateFn {
  return () => {
    const s = inject(Session);
    return perms.some((p) => { const [r, a] = p.split(':'); return s.can(r, a); }) || inject(Router).parseUrl('/');
  };
}

/** Pages across many students: a student-only account is sent to their own dashboard instead. */
export const staffOnly: CanActivateFn = () => {
  const s = inject(Session);
  return !(s.me()?.user.student && s.me()!.user.roles.length === 1) || inject(Router).parseUrl('/my');
};

/** Send each role to its natural landing page. */
export const landing: CanActivateFn = () => {
  const s = inject(Session);
  const r = inject(Router);
  const me = s.me();
  if (!me) return r.parseUrl('/login');
  if (s.isSysAdmin() && me.user.roles.length === 1) return r.parseUrl('/admin/users');
  if (s.mfaPending()) return r.parseUrl('/security');
  if (me.user.student && me.user.roles.length === 1) return r.parseUrl('/my');
  return r.parseUrl('/overview');
};
