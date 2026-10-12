import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { AuthService, Challenge, CognitoError } from '../core/auth.service';
import { Session } from '../core/session.service';

interface Persona { username: string; display_name: string; }

@Component({
  selector: 'app-login-page',
  imports: [RouterLink, FormsModule],
  styles: [`
    :host{display:block}
    .split{min-height:100vh;display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);background:var(--page)}
    .si-hero{position:relative;overflow:hidden;color:#e8f1f8;padding:48px 56px;display:flex;flex-direction:column;gap:36px;
      background:radial-gradient(900px 500px at 10% 0%,rgba(20,163,163,.35),transparent 60%),
                 radial-gradient(700px 500px at 100% 100%,rgba(42,74,115,.9),transparent 60%),
                 linear-gradient(160deg,#0d1b2e 0%,#13263f 55%,#0b3b4a 100%)}
    .si-hero::before{content:"";position:absolute;inset:0;opacity:.07;pointer-events:none;
      background-image:linear-gradient(#fff 1px,transparent 1px),linear-gradient(90deg,#fff 1px,transparent 1px);background-size:44px 44px}
    .si-hero>*{position:relative}
    .logo{display:flex;align-items:center;gap:12px} .logo strong{display:block;font-size:17px;color:#fff} .logo small{color:#9fb4c9;font-size:12.5px}
    .mark{width:42px;height:42px;border-radius:12px;display:grid;place-items:center;font-weight:800;color:#0d1b2e;
      background:linear-gradient(135deg,#5fd3cf,#14a3a3);box-shadow:0 6px 18px rgba(20,163,163,.45)}
    h1.headline{font-size:clamp(28px,3.2vw,40px);line-height:1.15;margin:0;color:#fff;letter-spacing:-.01em;max-width:520px}
    h1.headline span{background:linear-gradient(90deg,#7fe0dc,#c9f3f1);-webkit-background-clip:text;background-clip:text;color:transparent}
    .lede{color:#b8c8d8;font-size:15.5px;max-width:470px;margin:12px 0 0;line-height:1.55}
    .feats{list-style:none;margin:0;padding:0;display:grid;gap:14px;max-width:470px}
    .feats li{display:flex;gap:12px;align-items:flex-start;color:#d6e2ee;font-size:14px}
    .feats svg{flex:none;margin-top:1px} .feats strong{color:#fff;display:block;font-size:14.5px}
    .preview{margin-top:auto;max-width:440px;border-radius:16px;padding:16px 18px;background:rgba(255,255,255,.07);
      border:1px solid rgba(255,255,255,.14);backdrop-filter:blur(6px);box-shadow:0 20px 50px rgba(0,0,0,.25)}
    .preview .top{display:flex;justify-content:space-between;align-items:baseline;font-size:12px;color:#9fb4c9}
    .preview .si-num{font-size:30px;font-weight:700;color:#fff} .preview .up{color:#7fe0a0;font-size:12.5px;font-weight:600}
    .pills{display:flex;gap:6px;margin-top:8px} .pills span{font-size:11px;padding:2px 8px;border-radius:999px;background:rgba(127,224,220,.16);color:#bdeeea}
    .si-side{display:grid;place-items:center;padding:40px 24px;background:radial-gradient(600px 300px at 100% 0%,rgba(20,163,163,.08),transparent 70%),var(--page)}
    .panel{width:min(420px,100%);animation:rise .35s ease-out} @keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
    .panel h2{font-size:28px;margin:0 0 6px;color:var(--navy-900);letter-spacing:-.01em} .panel .si-sub{color:var(--muted);margin:0 0 24px}
    .go{width:100%;justify-content:center;padding:13px 16px;font-size:15.5px;border-radius:12px;gap:10px;
      background:linear-gradient(135deg,#14a3a3,#0b6e6e);border:0;color:#fff;box-shadow:0 8px 20px rgba(15,138,138,.28);transition:transform .15s,box-shadow .15s}
    .go:hover:not(:disabled){transform:translateY(-1px);box-shadow:0 12px 26px rgba(15,138,138,.34)}
    .secure{display:flex;gap:8px;align-items:center;justify-content:center;color:var(--muted);font-size:12.5px;margin-top:10px}
    .help{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:22px}
    .tile{display:flex;gap:10px;align-items:center;padding:12px;border:1px solid var(--line);border-radius:12px;background:#fff;
      color:var(--ink);text-decoration:none;font-size:13.5px;transition:border-color .15s,box-shadow .15s}
    .tile:hover{border-color:var(--teal-500);box-shadow:0 4px 14px rgba(13,27,46,.07)} .tile svg{flex:none;color:var(--teal-700)}
    .tile small{display:block;color:var(--muted);font-size:12px}
    .newbie{margin-top:22px;padding:16px;border-radius:14px;background:linear-gradient(135deg,#def3f2,#eef6fb);border:1px solid #cfe7e6;
      display:flex;gap:14px;align-items:center;justify-content:space-between;flex-wrap:wrap}
    .newbie strong{display:block;color:var(--navy-900)} .newbie span{font-size:13px;color:var(--ink-2)}
    .foot{margin-top:26px;font-size:12px;color:var(--muted);text-align:center}
    .form{display:grid;gap:14px}
    .fl{display:grid;gap:6px;font-size:13px;font-weight:600;color:var(--ink-2)}
    .input{display:flex;align-items:center;gap:10px;border:1.5px solid var(--line);border-radius:12px;padding:0 12px;background:#fff;
      transition:border-color .15s,box-shadow .15s;color:var(--muted)}
    .input:focus-within{border-color:var(--teal-500);box-shadow:0 0 0 4px rgba(20,163,163,.15);color:var(--teal-700)}
    .input input{border:0;outline:0;box-shadow:none;padding:12px 0;font-size:15px;flex:1;min-width:0;background:transparent;color:var(--ink)}
    .eye{border:0;background:none;color:var(--teal-700);font-size:12.5px;font-weight:600;cursor:pointer;padding:6px}
    .otp{font-size:28px;letter-spacing:.5em;text-align:center;font-variant-numeric:tabular-nums;padding:12px;border-radius:12px;border:1.5px solid var(--line)}
    .otp:focus{border-color:var(--teal-500);box-shadow:0 0 0 4px rgba(20,163,163,.15);outline:0}
    .spin{width:16px;height:16px;border-radius:50%;border:2px solid rgba(255,255,255,.4);border-top-color:#fff;animation:sp .8s linear infinite}
    @keyframes sp{to{transform:rotate(360deg)}}
    .stepper{display:flex;gap:6px;margin:-4px 0 14px} .stepper span{height:4px;flex:1;border-radius:4px;background:var(--line)}
    .stepper .done{background:var(--teal-500)} .stepper .on{background:linear-gradient(90deg,var(--teal-500),#7fe0dc)}
    .rules{font-size:12.5px;color:var(--muted);margin:-6px 0 0;padding:0;list-style:none} .rules li.ok{color:#006300}
    .personas{display:grid;gap:8px;max-height:46vh;overflow:auto;padding-right:2px}
    .personas .btn{justify-content:flex-start;text-align:left;border-radius:10px}
    @media (max-width:900px){
      .split{grid-template-columns:1fr} .si-hero{padding:28px 20px;gap:18px} .feats,.preview,.lede{display:none}
      h1.headline{font-size:24px} .si-side{padding:28px 16px 40px;align-items:start}}
    @media (max-width:420px){.help{grid-template-columns:1fr}}
  `],
  template: `
    <div class="split">
      <section class="si-hero" aria-label="About Smart Campus">
        <div class="logo"><div class="mark" aria-hidden="true">SC</div><div><strong>Smart Campus</strong><small>Student success analytics</small></div></div>
        <div>
          <h1 class="headline">Every student's progress, <span>in one clear view.</span></h1>
          <p class="lede">Marks, attendance, skills and placement readiness come together in one Success Score, so support reaches students early.</p>
        </div>
        <ul class="feats">
          <li><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#7fe0dc" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M3 17l5-5 4 4 8-8"/><path d="M14 8h6v6"/></svg>
            <div><strong>See improvement over time</strong>Monthly scores, subject marks and trends for every student.</div></li>
          <li><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#7fe0dc" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z"/></svg>
            <div><strong>Early warning</strong>Clear reasons when a student needs attention, never a black box.</div></li>
          <li><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#7fe0dc" stroke-width="2" stroke-linecap="round" aria-hidden="true"><rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 018 0v3"/></svg>
            <div><strong>Private and secure</strong>Each person sees only what their role allows, with two-step sign-in.</div></li>
        </ul>
        <div class="preview" aria-hidden="true">
          <div class="top"><span>Success Score · Sep 2026</span><span class="up">▲ +6.2 since April</span></div>
          <div style="display:flex;align-items:flex-end;justify-content:space-between;gap:12px">
            <div><div class="si-num">72.4</div><div class="pills"><span>On track</span><span>Complete</span></div></div>
            <svg width="190" height="64" viewBox="0 0 190 64">
              <defs><linearGradient id="lg" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#7fe0dc" stop-opacity=".45"/><stop offset="1" stop-color="#7fe0dc" stop-opacity="0"/></linearGradient></defs>
              <path d="M2 50 L38 44 L74 47 L110 34 L146 28 L186 14 L186 62 L2 62 Z" fill="url(#lg)"/>
              <path d="M2 50 L38 44 L74 47 L110 34 L146 28 L186 14" fill="none" stroke="#7fe0dc" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>
              <circle cx="186" cy="14" r="4" fill="#fff" stroke="#14a3a3" stroke-width="2"/></svg>
          </div>
        </div>
      </section>

      <main class="si-side" aria-labelledby="t">
        <div class="panel">
          <h2 id="t">{{ step() === 'mfa' ? 'Two-step verification' : step() === 'newpw' ? 'Set your password' : 'Welcome back' }}</h2>
          @if (auth.config()?.mode === 'cognito') {
            @switch (step()) {
              @case ('password') {
                <p class="si-sub">Sign in to your Smart Campus account.</p>
                @if (error()) { <p class="banner danger" role="alert">{{ error() }}</p> }
                <form class="form" (submit)="$event.preventDefault(); submitPassword()" autocomplete="on">
                  <label class="fl">User ID
                    <span class="input"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0116 0"/></svg>
                      <input name="u" [(ngModel)]="username" autocomplete="username" autocapitalize="none" spellcheck="false" required placeholder="e.g. user.admin"></span></label>
                  <label class="fl">Password
                    <span class="input"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 018 0v3"/></svg>
                      <input name="p" [type]="show() ? 'text' : 'password'" [(ngModel)]="password" autocomplete="current-password" required placeholder="Your password">
                      <button type="button" class="eye" (click)="show.set(!show())" [attr.aria-label]="show() ? 'Hide password' : 'Show password'">{{ show() ? 'Hide' : 'Show' }}</button></span></label>
                  <button class="btn primary go" type="submit" [disabled]="busy() || !username.trim() || !password">
                    @if (busy()) { <span class="spin" aria-hidden="true"></span> Signing in… } @else { Sign in
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg> }</button>
                </form>
                <div class="secure"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 2l8 4v6c0 5-3.5 9-8 10-4.5-1-8-5-8-10V6z"/></svg>
                  Protected by two-step verification</div>
                <nav class="help" aria-label="Account help">
                  <a class="tile" routerLink="/recover"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="8" cy="15" r="4"/><path d="M10.8 12.2L20 3M16 7l3 3"/></svg>
                    <span>Forgot password?<small>Reset it by email</small></span></a>
                  <a class="tile" routerLink="/recover" [queryParams]="{ mode: 'mfa' }"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/></svg>
                    <span>Lost your phone?<small>Reset authenticator</small></span></a>
                </nav>
              }
              @case ('mfa') {
                <div class="stepper" aria-hidden="true"><span class="done"></span><span class="on"></span></div>
                <p class="si-sub">Open your authenticator app and enter the 6-digit code for <strong>Smart Campus</strong>.</p>
                @if (error()) { <p class="banner danger" role="alert">{{ error() }}</p> }
                <form class="form" (submit)="$event.preventDefault(); submitCode()">
                  <label class="fl">Authenticator code
                    <input class="otp" name="c" [(ngModel)]="code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" pattern="[0-9]{6}" placeholder="••••••" required autofocus></label>
                  <button class="btn primary go" type="submit" [disabled]="busy() || !codeOk()">
                    @if (busy()) { <span class="spin" aria-hidden="true"></span> Checking… } @else { Verify and continue }</button>
                </form>
                <div class="row small" style="justify-content:space-between;margin-top:14px">
                  <a href="" (click)="$event.preventDefault(); back()">← Use a different account</a>
                  <a routerLink="/recover" [queryParams]="{ mode: 'mfa' }">Lost your phone?</a></div>
              }
              @case ('newpw') {
                <p class="si-sub">Welcome! Choose a new password to finish setting up your account.</p>
                @if (error()) { <p class="banner danger" role="alert">{{ error() }}</p> }
                <form class="form" (submit)="$event.preventDefault(); submitNewPassword()">
                  <label class="fl">New password<span class="input"><input name="np" type="password" [(ngModel)]="newPassword" (ngModelChange)="pw.set($event)" autocomplete="new-password" required></span></label>
                  <ul class="rules">@for (r of rules(); track r.text) { <li [class.ok]="r.ok">{{ r.ok ? '✓' : '•' }} {{ r.text }}</li> }</ul>
                  <label class="fl">Confirm new password<span class="input"><input name="np2" type="password" [(ngModel)]="newPassword2" autocomplete="new-password" required></span></label>
                  @if (newPassword2 && newPassword2 !== newPassword) { <span class="error-text">The passwords don't match.</span> }
                  <button class="btn primary go" type="submit" [disabled]="busy() || newPassword !== newPassword2 || !allOk()">Save and sign in</button>
                </form>
              }
            }
          } @else {
            <p class="si-sub">Local development: choose a persona to sign in.</p>
            @if (error()) { <p class="banner danger" role="alert">{{ error() }}</p> }
            <div class="personas" role="list">
              @for (p of personas(); track p.username) {
                <button class="btn" role="listitem" type="button" [disabled]="busy()" (click)="local(p.username)">
                  <span><strong>{{ p.display_name }}</strong><br><span class="small muted mono">{{ p.username }}</span></span></button>
              }
              @if (!personas().length) { <p class="muted">No personas yet. Run <span class="mono">python -m app.seed</span> in backend/ first.</p> }
            </div>
            <form class="row" style="gap:6px;margin-top:10px" (submit)="$event.preventDefault(); local(other)">
              <input name="o" [(ngModel)]="other" placeholder="or another local user ID" aria-label="Local user ID" style="flex:1">
              <button class="btn" type="submit" [disabled]="busy() || !other">Sign in</button></form>
          }
          @if (step() === 'password') {
          <div class="newbie">
            <div><strong>New student?</strong><span>Create your account with your student ID and date of birth.</span></div>
            <a class="btn" routerLink="/register">Create account</a>
          </div>
          }
          <p class="foot">Staff accounts are created by the college office.</p>
        </div>
      </main>
    </div>`,
})
export class LoginPage implements OnInit {
  auth = inject(AuthService);
  private session = inject(Session);
  private router = inject(Router);
  personas = signal<Persona[]>([]);
  other = '';
  busy = signal(false);
  error = signal<string | null>(null);

  async ngOnInit() {
    if (await this.auth.token()) { await this.enter(); return; }
    if (this.auth.config()?.mode !== 'cognito') {
      try {
        const r = await fetch('/api/auth/config');
        const j = await r.json();
        this.personas.set(j.demo_personas || []);
      } catch { this.error.set('The server could not be reached.'); }
    }
  }

  async local(username: string) {
    this.busy.set(true); this.error.set(null);
    try { await this.auth.localLogin(username); await this.enter(); }
    catch (e) { this.error.set((e as Error).message); }
    finally { this.busy.set(false); }
  }

  // Cognito sign-in steps
  step = signal<'password' | 'mfa' | 'newpw'>('password');
  show = signal(false);
  username = ''; password = ''; code = ''; newPassword = ''; newPassword2 = '';
  private challenge: Challenge | null = null;
  pw = signal('');
  rules = computed(() => {
    const p = this.pw();
    return [
      { text: 'At least 12 characters', ok: p.length >= 12 },
      { text: 'An upper-case and a lower-case letter', ok: /[A-Z]/.test(p) && /[a-z]/.test(p) },
      { text: 'A number', ok: /\d/.test(p) },
      { text: 'A symbol, e.g. ! @ # %', ok: /[^A-Za-z0-9]/.test(p) },
    ];
  });
  allOk() { return this.rules().every((r) => r.ok); }
  codeOk() { return /^\d{6}$/.test(this.code.trim()); }

  private explain(e: unknown): string {
    const t = e instanceof CognitoError ? e.type : '';
    if (t === 'NotAuthorizedException') {
      return /expired|session/i.test((e as Error).message) ? 'That took too long. Please sign in again.' : 'The user ID or password is not correct.';
    }
    if (t === 'UserNotFoundException') return 'The user ID or password is not correct.';
    if (t === 'CodeMismatchException') return 'That code is not correct. Use the newest code from your app.';
    if (t === 'ExpiredCodeException') return 'That code has expired. Use the newest code from your app.';
    if (t === 'InvalidPasswordException') return (e as Error).message.split(':').pop()!.trim();
    if (t === 'TooManyRequestsException' || t === 'LimitExceededException') return 'Too many attempts. Please wait a few minutes and try again.';
    if (t === 'UserNotConfirmedException') return 'This account is not active yet. Contact the college office.';
    return (e as Error).message || 'Sign-in failed. Please try again.';
  }

  private async next(c: Challenge | null) {
    this.challenge = c;
    if (!c) { this.password = this.code = this.newPassword = this.newPassword2 = ''; await this.enter(); return; }
    if (c.name === 'SOFTWARE_TOKEN_MFA') { this.code = ''; this.step.set('mfa'); return; }
    if (c.name === 'NEW_PASSWORD_REQUIRED') { this.step.set('newpw'); return; }
    this.error.set('This account needs a sign-in step the app does not support. Contact the college office.');
  }

  private async run(fn: () => Promise<void>) {
    this.busy.set(true); this.error.set(null);
    try { await fn(); }
    catch (e) {
      if (e instanceof CognitoError && e.type === 'PasswordResetRequiredException') {
        await this.router.navigate(['/recover'], { queryParams: { user: this.username.trim().toLowerCase(), sent: 1 } });
        return;
      }
      if (e instanceof CognitoError && e.type === 'NotAuthorizedException' && this.step() !== 'password') this.back();
      this.error.set(this.explain(e));
    }
    finally { this.busy.set(false); }
  }

  submitPassword() { return this.run(async () => this.next(await this.auth.signIn(this.username, this.password))); }
  submitCode() { return this.run(async () => this.next(await this.auth.answer(this.challenge!, this.code))); }
  submitNewPassword() { return this.run(async () => this.next(await this.auth.answer(this.challenge!, this.newPassword))); }
  back() { this.step.set('password'); this.challenge = null; this.code = ''; this.password = ''; }

  private async enter() {
    try {
      await this.session.load();
      await this.router.navigateByUrl('/');
    } catch (e) {
      this.auth.clear();
      this.error.set((e as Error).message || 'Your account is not active. Contact the System Administrator.');
    }
  }
}
