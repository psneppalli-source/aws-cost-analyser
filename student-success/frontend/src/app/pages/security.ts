import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import qrcode from 'qrcode-generator';
import { Api } from '../core/api.service';
import { AuthService } from '../core/auth.service';
import { MfaService } from '../core/mfa.service';
import { Session } from '../core/session.service';
import { message } from '../shared/page';

@Component({
  selector: 'app-security-page',
  imports: [FormsModule],
  styles: [`.qr{display:flex;gap:20px;align-items:flex-start;flex-wrap:wrap} .qr img{width:200px;height:200px;image-rendering:pixelated;border:1px solid var(--line);border-radius:8px}
    .rules{font-size:12.5px;color:var(--muted);margin:4px 0 0;padding-left:0;list-style:none} .rules li.ok{color:#006300}
    .secret{font-family:ui-monospace,monospace;letter-spacing:.08em;word-break:break-all;background:#f0efec;padding:6px 8px;border-radius:6px;font-size:13px}`],
  template: `
    <div class="page-head"><h1>Security</h1>
      <p class="sub">Two-step sign-in with an authenticator app protects your account even if your password is known.</p></div>

    @if (session.mfaPending()) {
      <p class="banner warn" role="alert"><strong>One more step.</strong> Student accounts must link an authenticator app before continuing.</p>
    }

    <section class="card">
      <div class="card-head"><h2>Authenticator app</h2><span class="spacer"></span>
        @if (enabled()) { <span class="chip teal">✓ On</span> } @else if (!local()) { <span class="badge medium">■ Not set up</span> }</div>

      @if (local()) {
        <p class="small">Authenticator apps are used with the college sign-in on the hosted site. In local development there is nothing to set up.</p>
      } @else if (enabled() && !secret()) {
        <p>Your account asks for a 6-digit code from your authenticator app each time you sign in.</p>
        <button class="btn" type="button" (click)="begin()" [disabled]="busy()">Move to a new phone</button>
        <p class="small muted" style="margin-top:8px">Scan a new QR code with your new phone; the old phone stops working once you confirm.
          Lost your phone and can't sign in? Use “Lost your authenticator app?” on the sign-in page.</p>
      } @else if (!secret()) {
        <ol class="small"><li>Install Google Authenticator, Microsoft Authenticator or another authenticator app on your phone.</li>
          <li>Select <strong>Set up</strong> and scan the QR code with the app.</li>
          <li>Enter the 6-digit code the app shows.</li></ol>
        <button class="btn primary" type="button" (click)="begin()" [disabled]="busy()">Set up authenticator app</button>
      } @else {
        <div class="qr">
          <img [src]="qr()" alt="QR code to add Smart Campus to your authenticator app" />
          <div style="flex:1;min-width:240px" class="stack">
            <p class="small">Scan the code with your authenticator app. Can't scan? Enter this key in the app instead:</p>
            <div class="secret" aria-label="Setup key">{{ grouped() }}</div>
            <form class="stack" (submit)="$event.preventDefault(); confirm()">
              <label class="field">6-digit code from the app<input name="c" [(ngModel)]="code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" required class="mono"></label>
              <button class="btn primary" type="submit" [disabled]="busy() || code.length !== 6">Turn on</button>
            </form>
          </div>
        </div>
      }
      @if (error()) { <p class="error-text" role="alert" style="margin-top:10px">{{ error() }}</p> }
      @if (notice()) { <p class="banner" role="status" style="margin-top:10px">{{ notice() }}</p> }
    </section>

    <section class="card" style="margin-top:16px"><h2>Account</h2>
      <dl class="small" style="display:grid;grid-template-columns:auto 1fr;gap:4px 14px;margin:0">
        <dt class="muted">User ID</dt><dd style="margin:0">{{ session.me()?.user?.username }}</dd>
        <dt class="muted">Name</dt><dd style="margin:0">{{ session.me()?.user?.display_name }}</dd>
        <dt class="muted">Role</dt><dd style="margin:0">{{ session.me()?.user?.role_labels?.join(', ') }}</dd></dl>
    </section>

    @if (!local()) {
      <section class="card" style="margin-top:16px"><h2>Change password</h2>
        <form class="stack" style="max-width:420px" (submit)="$event.preventDefault(); changePassword()">
          <label class="field">Current password<input name="cur" type="password" [(ngModel)]="cur" required autocomplete="current-password"></label>
          <label class="field">New password<input name="np" type="password" [(ngModel)]="np" (ngModelChange)="pw.set($event)" required autocomplete="new-password"></label>
          <ul class="rules">@for (r of rules(); track r.text) { <li [class.ok]="r.ok">{{ r.ok ? '✓' : '•' }} {{ r.text }}</li> }</ul>
          <label class="field">Confirm new password<input name="np2" type="password" [(ngModel)]="np2" required autocomplete="new-password"></label>
          @if (np2 && np2 !== np) { <span class="error-text">The passwords don't match.</span> }
          <button class="btn primary" type="submit" [disabled]="pwBusy() || !cur || np !== np2 || !allOk()">Change password</button>
        </form>
        @if (pwError()) { <p class="error-text" role="alert" style="margin-top:10px">{{ pwError() }}</p> }
        @if (pwNotice()) { <p class="banner" role="status" style="margin-top:10px">{{ pwNotice() }}</p> }
        <p class="small muted" style="margin-top:10px">Forgotten your current password? Sign out and use “Forgot password?” on the sign-in page.</p>
      </section>
    }`,
})
export class SecurityPage {
  private api = inject(Api);
  private mfa = inject(MfaService);
  private router = inject(Router);
  auth = inject(AuthService);
  session = inject(Session);
  secret = signal<string | null>(null);
  uri = signal('');
  busy = signal(false);
  error = signal<string | null>(null);
  notice = signal<string | null>(null);
  code = '';
  cur = ''; np = ''; np2 = '';
  pw = signal('');
  pwBusy = signal(false);
  pwError = signal<string | null>(null);
  pwNotice = signal<string | null>(null);
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
  local = computed(() => this.auth.config()?.mode !== 'cognito');
  enabled = computed(() => !!this.session.me()?.user.mfa?.enabled);
  grouped = computed(() => (this.secret() || '').replace(/(.{4})/g, '$1 ').trim());
  qr = computed(() => {
    if (!this.uri()) return '';
    const q = qrcode(0, 'M');
    q.addData(this.uri());
    q.make();
    return q.createDataURL(5, 8);
  });

  async begin() {
    this.busy.set(true); this.error.set(null);
    try {
      const r = await this.mfa.begin(this.session.me()?.user.username || 'account');
      this.secret.set(r.secret); this.uri.set(r.uri);
    } catch (e) { this.error.set(message(e)); }
    finally { this.busy.set(false); }
  }

  async changePassword() {
    this.pwBusy.set(true); this.pwError.set(null); this.pwNotice.set(null);
    try {
      await this.mfa.changePassword(this.cur, this.np);
      this.cur = this.np = this.np2 = ''; this.pw.set('');
      this.pwNotice.set('Password changed. Use the new password next time you sign in.');
    } catch (e) { this.pwError.set(message(e)); }
    finally { this.pwBusy.set(false); }
  }

  async confirm() {
    this.busy.set(true); this.error.set(null);
    try {
      await this.mfa.confirm(this.code);
      await this.api.post('/me/mfa/refresh');
      await this.session.load();
      this.secret.set(null); this.code = '';
      this.notice.set('Authenticator app turned on. From now on, sign-in asks for a 6-digit code.');
      if (this.session.isStudent()) setTimeout(() => this.router.navigateByUrl('/my'), 1200);
    } catch (e) { this.error.set(message(e)); }
    finally { this.busy.set(false); }
  }
}
