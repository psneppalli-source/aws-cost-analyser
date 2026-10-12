import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { Api, ApiError } from '../core/api.service';
import { AuthService } from '../core/auth.service';
import { message } from '../shared/page';

/**
 * Forgotten password and lost authenticator app. A 6-digit code is emailed to the account's verified address;
 * with it the user sets a new password and, for a lost phone, resets the authenticator (students also confirm
 * their date of birth). Every existing session is signed out.
 */
@Component({
  selector: 'app-recover-page',
  imports: [FormsModule, RouterLink],
  styles: [`.rules{font-size:12.5px;color:var(--muted);margin:4px 0 0;padding-left:0;list-style:none} .rules li.ok{color:#006300}
    .choice{display:flex;gap:8px;align-items:flex-start;padding:10px;border:1px solid var(--line);border-radius:8px}
    .choice input{width:auto;margin-top:3px}`],
  template: `
    <div class="login-wrap">
      <main class="login-card" aria-labelledby="t" style="width:min(520px,100%)">
        <div class="brand" style="color:var(--navy-900);padding:0 0 10px"><div class="brand-mark" aria-hidden="true">SC</div>
          <div><strong id="t">{{ resetMfa ? 'Lost your authenticator app?' : 'Forgot your password?' }}</strong><small style="color:var(--muted)">Smart Campus</small></div></div>
        @if (error()) { <p class="banner danger" role="alert">{{ error() }}</p> }

        @if (local()) {
          <p class="small">Password and authenticator recovery are used with the college sign-in on the hosted site. Local development has no passwords.</p>
        } @else {
          @switch (step()) {
            @case (1) {
              <p class="small">Enter your user ID. We'll email a 6-digit code to the address on your account.</p>
              <form class="stack" (submit)="$event.preventDefault(); start()">
                <label class="field">User ID<input name="u" [(ngModel)]="username" required autocomplete="username" [attr.aria-invalid]="!!fields()['username']"></label>
                @if (fields()['username']) { <span class="error-text">{{ fields()['username'] }}</span> }
                <button class="btn primary" type="submit" [disabled]="busy() || !username.trim()">Send code</button>
              </form>
            }
            @case (2) {
              <p class="banner small" role="status">{{ notice() }}</p>
              <form class="stack" (submit)="$event.preventDefault(); complete()">
                <label class="field">6-digit code from the email<input name="code" [(ngModel)]="code" required autocomplete="one-time-code" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" class="mono" [attr.aria-invalid]="!!fields()['code']"></label>
                @if (fields()['code']) { <span class="error-text">{{ fields()['code'] }}</span> }
                <label class="field">New password<input name="p" type="password" [(ngModel)]="password" (ngModelChange)="pw.set($event)" required autocomplete="new-password" [attr.aria-invalid]="!!fields()['password']"></label>
                <ul class="rules">@for (r of rules(); track r.text) { <li [class.ok]="r.ok">{{ r.ok ? '✓' : '•' }} {{ r.text }}</li> }</ul>
                @if (fields()['password']) { <span class="error-text">{{ fields()['password'] }}</span> }
                <label class="field">Confirm new password<input name="p2" type="password" [(ngModel)]="password2" required autocomplete="new-password"></label>
                @if (password2 && password2 !== password) { <span class="error-text">The passwords don't match.</span> }
                <label class="choice small"><input type="checkbox" name="m" [(ngModel)]="resetMfa">
                  <span><strong>Also reset my authenticator app</strong><br>For a lost or replaced phone. You'll scan a new QR code after signing in.</span></label>
                @if (resetMfa) {
                  <label class="field">Date of birth <span class="small muted">(students)</span><input name="dob" type="date" [(ngModel)]="dob" [attr.aria-invalid]="!!fields()['date_of_birth']"></label>
                  @if (fields()['date_of_birth']) { <span class="error-text">{{ fields()['date_of_birth'] }}</span> }
                }
                <div class="row" style="gap:8px"><button class="btn primary" type="submit" [disabled]="busy() || password !== password2 || !codeOk()">{{ resetMfa ? 'Reset password and authenticator' : 'Set new password' }}</button>
                  <button class="btn" type="button" (click)="start()" [disabled]="busy()">Send a new code</button></div>
              </form>
            }
            @case (3) {
              <p class="banner" role="status">{{ notice() }}</p>
              <a class="btn primary" routerLink="/login" style="width:100%;justify-content:center">Go to sign in</a>
            }
          }
        }
        <p class="small muted" style="margin-top:16px">Remembered it? <a routerLink="/login">Sign in</a>. No access to your email any more? Ask the college office to update it.</p>
      </main>
    </div>`,
})
export class RecoverPage {
  private api = inject(Api);
  private auth = inject(AuthService);
  step = signal(1);
  busy = signal(false);
  error = signal<string | null>(null);
  fields = signal<Record<string, string>>({});
  notice = signal('');
  local = computed(() => this.auth.config()?.mode !== 'cognito');
  username = ''; code = ''; password = ''; password2 = ''; dob = '';
  private q = inject(ActivatedRoute).snapshot.queryParamMap;
  resetMfa = this.q.get('mode') === 'mfa';

  constructor() {
    // sent=1: the college already emailed a reset code (an administrator reset the password)
    if (this.q.get('user')) this.username = this.q.get('user')!;
    if (this.q.get('sent')) { this.notice.set('Your password was reset by the college. Enter the 6-digit code from the email and choose a new password.'); this.step.set(2); }
  }
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
  codeOk() { return /^\d{6}$/.test(this.code.trim()); }

  private fail(e: unknown) {
    if (e instanceof ApiError && Object.keys(e.fields).length) { this.fields.set(e.fields); this.error.set(null); }
    else { this.error.set(message(e)); }
  }

  async start() {
    this.busy.set(true); this.error.set(null); this.fields.set({});
    try {
      const r = await this.api.post<{ message: string }>('/recovery/start', { username: this.username.trim() });
      this.notice.set(r.message); this.step.set(2);
    } catch (e) { this.fail(e); }
    finally { this.busy.set(false); }
  }

  async complete() {
    this.busy.set(true); this.error.set(null); this.fields.set({});
    try {
      const r = await this.api.post<{ message: string }>('/recovery/complete', { username: this.username.trim(), code: this.code.trim(),
        password: this.password, reset_authenticator: this.resetMfa, date_of_birth: this.resetMfa ? this.dob : null });
      this.password = this.password2 = this.code = ''; this.pw.set('');
      this.notice.set(r.message); this.step.set(3);
    } catch (e) { this.fail(e); }
    finally { this.busy.set(false); }
  }
}
