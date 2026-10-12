import { Injectable, signal } from '@angular/core';

/** Runtime configuration served at /config.json by the Web Lambda (or the local server). */
export interface AppConfig {
  mode: 'cognito' | 'local-demo';
  domain?: string;        // Cognito domain (sign-in emails and recovery use it; the app signs in through its own form)
  clientId?: string;      // public SPA client (no secret)
  redirectUri?: string;   // the site URL
  region?: string;        // AWS region of the user pool (authenticator setup calls Cognito directly)
}

interface Session { idToken: string; accessToken?: string; refreshToken?: string; exp: number; }

const KEY = 'ssp.session';

export function claims(jwt: string): Record<string, unknown> {
  try {
    return JSON.parse(atob(jwt.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
  } catch {
    return {};
  }
}

/** A step the user still has to complete after the password (Cognito challenges). */
export interface Challenge { name: 'SOFTWARE_TOKEN_MFA' | 'NEW_PASSWORD_REQUIRED' | string; session: string; username: string; }

/** Cognito error with its type, e.g. NotAuthorizedException. */
export class CognitoError extends Error {
  constructor(public type: string, message: string) { super(message); }
}

/**
 * Sign-in for both modes. Cognito: the app's own sign-in form talks to the Cognito user-pool API directly
 * (public client, no secret; password, then the authenticator code), so there is no redirect to a hosted page and
 * any address of the site works. Tokens are kept in sessionStorage only, so closing the tab signs the user out.
 * Local demo mode is for development only and is refused by the backend in AWS.
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
    try { sessionStorage.removeItem(KEY); } catch { /* ignore */ }
    this.signedIn.set(false);
  }

  /** Call the Cognito user-pool API (unauthenticated operations and the user's own token operations). */
  async cognito<T>(target: string, body: Record<string, unknown>): Promise<T> {
    const region = this.config()?.region || 'eu-west-2';
    let r: Response;
    try {
      r = await fetch(`https://cognito-idp.${region}.amazonaws.com/`, { method: 'POST',
        headers: { 'Content-Type': 'application/x-amz-json-1.1', 'X-Amz-Target': `AWSCognitoIdentityProviderService.${target}` },
        body: JSON.stringify(body) });
    } catch { throw new CognitoError('Network', 'The sign-in service could not be reached. Check your connection and try again.'); }
    const j = await r.json().catch(() => ({}));
    if (!r.ok) {
      const type = String((j as { __type?: string }).__type || '').split('#').pop() || 'Error';
      throw new CognitoError(type, (j as { message?: string }).message || 'Something went wrong. Please try again.');
    }
    return j as T;
  }

  private store(r: { IdToken: string; AccessToken: string; RefreshToken?: string }, refresh?: string): void {
    this.save({ idToken: r.IdToken, accessToken: r.AccessToken, refreshToken: r.RefreshToken || refresh, exp: Number(claims(r.IdToken)['exp']) });
  }

  private async finish(username: string, r: { AuthenticationResult?: { IdToken: string; AccessToken: string; RefreshToken?: string };
    ChallengeName?: string; Session?: string }): Promise<Challenge | null> {
    if (r.AuthenticationResult) { this.store(r.AuthenticationResult); return null; }
    if (r.ChallengeName && r.Session) return { name: r.ChallengeName, session: r.Session, username };
    throw new CognitoError('Unexpected', 'Sign-in could not be completed. Please try again.');
  }

  /** Step 1: user ID and password. Returns a challenge when an authenticator code or new password is needed. */
  async signIn(username: string, password: string): Promise<Challenge | null> {
    const u = username.trim().toLowerCase();
    const r = await this.cognito<{ AuthenticationResult?: { IdToken: string; AccessToken: string; RefreshToken?: string };
      ChallengeName?: string; Session?: string }>('InitiateAuth', { AuthFlow: 'USER_PASSWORD_AUTH', ClientId: this.config()!.clientId,
      AuthParameters: { USERNAME: u, PASSWORD: password } });
    return this.finish(u, r);
  }

  /** Step 2: answer a challenge (authenticator code, or a new password for a first sign-in). */
  async answer(c: Challenge, value: string): Promise<Challenge | null> {
    const responses: Record<string, string> = { USERNAME: c.username };
    if (c.name === 'SOFTWARE_TOKEN_MFA') responses['SOFTWARE_TOKEN_MFA_CODE'] = value.trim();
    else if (c.name === 'NEW_PASSWORD_REQUIRED') responses['NEW_PASSWORD'] = value;
    else throw new CognitoError('Unsupported', 'This account needs a sign-in step the app does not support. Contact the college office.');
    const r = await this.cognito<{ AuthenticationResult?: { IdToken: string; AccessToken: string; RefreshToken?: string };
      ChallengeName?: string; Session?: string }>('RespondToAuthChallenge', { ChallengeName: c.name, ClientId: this.config()!.clientId,
      Session: c.session, ChallengeResponses: responses });
    return this.finish(c.username, r);
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
        const r = await this.cognito<{ AuthenticationResult: { IdToken: string; AccessToken: string } }>('InitiateAuth', {
          AuthFlow: 'REFRESH_TOKEN_AUTH', ClientId: this.config()!.clientId, AuthParameters: { REFRESH_TOKEN: s.refreshToken } });
        this.store(r.AuthenticationResult, s.refreshToken);
        return r.AuthenticationResult.IdToken;
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
    const refresh = this.load()?.refreshToken;
    this.clear();
    if (c?.mode === 'cognito' && refresh) {
      // end the session on the server too; the page moves on whether or not this completes
      this.cognito('RevokeToken', { Token: refresh, ClientId: c.clientId }).catch(() => undefined);
    }
    setTimeout(() => location.assign('/login'), 150);
  }
}
