import { Injectable, signal } from '@angular/core';

/** Runtime configuration served at /config.json by the Web Lambda (or the local server). */
export interface AppConfig {
  mode: 'cognito' | 'local-demo';
  domain?: string;        // Cognito hosted login domain, e.g. https://prefix.auth.eu-west-2.amazoncognito.com
  clientId?: string;      // public SPA client (no secret)
  redirectUri?: string;   // the site URL
  region?: string;        // AWS region of the user pool (authenticator setup calls Cognito directly)
}

interface Session { idToken: string; accessToken?: string; refreshToken?: string; exp: number; }

const KEY = 'ssp.session';
const PKCE = 'ssp.pkce';

function b64url(bytes: ArrayBuffer | Uint8Array): string {
  const arr = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let s = '';
  arr.forEach((b) => (s += String.fromCharCode(b)));
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
function randomString(n: number): string {
  const a = new Uint8Array(n);
  crypto.getRandomValues(a);
  return b64url(a);
}
export function claims(jwt: string): Record<string, unknown> {
  try {
    return JSON.parse(atob(jwt.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
  } catch {
    return {};
  }
}

/**
 * Sign-in for both modes. Cognito uses the authorisation code flow with PKCE against
 * the hosted login (public client, no secret). Tokens are kept in sessionStorage only,
 * so closing the tab signs the user out. Local demo mode is for development only and
 * is refused by the backend in AWS.
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  readonly config = signal<AppConfig | null>(null);
  readonly signedIn = signal(false);

  async init(): Promise<void> {
    let cfg: AppConfig;
    try {
      const r = await fetch('/config.json', { cache: 'no-store' });
      cfg = r.ok ? await r.json() : { mode: 'local-demo' };
    } catch {
      cfg = { mode: 'local-demo' };
    }
    this.config.set(cfg);
    if (cfg.mode === 'cognito') await this.completeRedirect();
    this.signedIn.set(!!this.load() && this.load()!.exp > Date.now() / 1000);
  }

  private load(): Session | null {
    try { return JSON.parse(sessionStorage.getItem(KEY) || 'null'); } catch { return null; }
  }
  private save(s: Session): void {
    try { sessionStorage.setItem(KEY, JSON.stringify(s)); } catch { /* storage unavailable */ }
    this.signedIn.set(true);
  }
  clear(): void {
    try { sessionStorage.removeItem(KEY); sessionStorage.removeItem(PKCE); } catch { /* ignore */ }
    this.signedIn.set(false);
  }

  /** Return to the address the user is on (the site URL or a registered alias); Cognito accepts only registered ones. */
  private redirectUri(): string { return `${location.origin}/`; }

  async startCognito(): Promise<void> {
    const c = this.config()!;
    const verifier = randomString(48);
    const state = randomString(16);
    sessionStorage.setItem(PKCE, JSON.stringify({ verifier, state }));
    const challenge = b64url(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier)));
    const q = new URLSearchParams({ response_type: 'code', client_id: c.clientId!, redirect_uri: this.redirectUri(),
      scope: 'openid profile email aws.cognito.signin.user.admin', state, code_challenge: challenge, code_challenge_method: 'S256' });
    location.assign(`${c.domain}/oauth2/authorize?${q}`);
  }

  private async completeRedirect(): Promise<void> {
    const u = new URL(location.href);
    const code = u.searchParams.get('code');
    if (!code) return;
    const p = JSON.parse(sessionStorage.getItem(PKCE) || '{}');
    history.replaceState(null, '', u.pathname);
    if (!p.verifier || u.searchParams.get('state') !== p.state) throw new Error('Sign-in expired. Please sign in again.');
    const t = await this.tokenRequest({ grant_type: 'authorization_code', code, redirect_uri: this.redirectUri(),
      code_verifier: p.verifier });
    sessionStorage.removeItem(PKCE);
    this.save({ idToken: t.id_token, accessToken: t.access_token, refreshToken: t.refresh_token, exp: Number(claims(t.id_token)['exp']) });
  }

  private async tokenRequest(params: Record<string, string>): Promise<{ id_token: string; access_token?: string; refresh_token?: string }> {
    const c = this.config()!;
    const r = await fetch(`${c.domain}/oauth2/token`, { method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ client_id: c.clientId!, ...params }).toString() });
    if (!r.ok) throw new Error('Sign-in failed. Please try again.');
    return r.json();
  }

  async localLogin(username: string): Promise<void> {
    const r = await fetch('/api/auth/local/login', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username }) });
    const j = await r.json();
    if (!r.ok) throw new Error(j?.error?.message || 'Sign-in failed');
    this.save({ idToken: j.token, exp: Number(claims(j.token)['exp']) });
  }

  /** A valid ID token, refreshing it when close to expiry. */
  async token(): Promise<string | null> {
    const s = this.load();
    if (!s) return null;
    if (s.exp - Date.now() / 1000 > 60) return s.idToken;
    if (this.config()?.mode === 'cognito' && s.refreshToken) {
      try {
        const t = await this.tokenRequest({ grant_type: 'refresh_token', refresh_token: s.refreshToken });
        this.save({ idToken: t.id_token, accessToken: t.access_token, refreshToken: s.refreshToken, exp: Number(claims(t.id_token)['exp']) });
        return t.id_token;
      } catch { /* fall through */ }
    }
    this.clear();
    return null;
  }

  /** Access token (Cognito mode) for the user's own account operations, e.g. registering an authenticator app. */
  async accessToken(): Promise<string | null> {
    await this.token();
    return this.load()?.accessToken || null;
  }

  signOut(): void {
    const c = this.config();
    this.clear();
    if (c?.mode === 'cognito') {
      location.assign(`${c.domain}/logout?${new URLSearchParams({ client_id: c.clientId!, logout_uri: this.redirectUri() })}`);
    } else {
      location.assign('/login');
    }
  }
}
