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
        <p class="small muted">Lost your phone? Ask the system administrator to reset your authenticator, then set it up again here.</p>
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
      <p class="small muted" style="margin-top:10px">To change your password, sign out and use “Forgot your password?” on the sign-in page.</p>
    </section>`,
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
