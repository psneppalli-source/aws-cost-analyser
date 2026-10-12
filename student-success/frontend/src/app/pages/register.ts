import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Api, ApiError } from '../core/api.service';
import { AuthService } from '../core/auth.service';
import { message } from '../shared/page';

/**
 * Student self-registration: details must match the student's record; the emailed code proves the address;
 * only then are a user ID and password chosen. An authenticator app is set up at first sign-in.
 */
@Component({
  selector: 'app-register-page',
  imports: [FormsModule, RouterLink],
  styles: [`.steps{display:flex;gap:8px;margin:0 0 16px;font-size:12.5px;color:var(--muted)} .steps span{flex:1;border-top:3px solid var(--line);padding-top:6px}
    .steps span.on{border-color:var(--teal-500);color:var(--navy-900);font-weight:600} .rules{font-size:12.5px;color:var(--muted);margin:4px 0 0;padding-left:18px}
    .rules li.ok{color:#006300}`],
  template: `
    <div class="login-wrap">
      <main class="login-card" aria-labelledby="t" style="width:min(520px,100%)">
        <div class="brand" style="color:var(--navy-900);padding:0 0 10px"><div class="brand-mark" aria-hidden="true">SC</div>
          <div><strong id="t">Create your student account</strong><small style="color:var(--muted)">Smart Campus</small></div></div>
        <div class="steps" aria-hidden="true"><span [class.on]="step() === 1">1. Your details</span><span [class.on]="step() === 2">2. Verify email &amp; choose login</span><span [class.on]="step() === 3">3. Sign in &amp; secure</span></div>
        @if (error()) { <p class="banner danger" role="alert">{{ error() }}</p> }

        @switch (step()) {
          @case (1) {
            <p class="small">Enter the details the college holds for you. We'll email a verification code to that address.</p>
            <form class="stack" (submit)="$event.preventDefault(); start()">
              <label class="field">Student ID<input name="sid" [(ngModel)]="sid" required autocomplete="off" placeholder="e.g. CSE24007" [attr.aria-invalid]="!!fields()['student_id']"></label>
              @if (fields()['student_id']) { <span class="error-text">{{ fields()['student_id'] }}</span> }
              <label class="field">Date of birth<input name="dob" type="date" [(ngModel)]="dob" required [attr.aria-invalid]="!!fields()['date_of_birth']"></label>
              @if (fields()['date_of_birth']) { <span class="error-text">{{ fields()['date_of_birth'] }}</span> }
              <label class="field">College email address<input name="em" type="email" [(ngModel)]="email" required autocomplete="email" [attr.aria-invalid]="!!fields()['email']"></label>
              @if (fields()['email']) { <span class="error-text">{{ fields()['email'] }}</span> }
              <button class="btn primary" type="submit" [disabled]="busy()">Send verification code</button>
            </form>
          }
          @case (2) {
            <p class="banner small" role="status">{{ notice() }}</p>
            @if (devCode()) { <p class="banner warn small">Local development: no email is sent. Your code is <strong class="mono">{{ devCode() }}</strong></p> }
            <form class="stack" (submit)="$event.preventDefault(); complete()">
              <label class="field">Verification code from the email<input name="code" [(ngModel)]="code" required autocomplete="one-time-code" class="mono" [attr.aria-invalid]="!!fields()['code']"></label>
              @if (fields()['code']) { <span class="error-text">{{ fields()['code'] }}</span> }
              <label class="field">Choose a user ID<input name="u" [(ngModel)]="username" required autocomplete="username" [attr.aria-invalid]="!!fields()['username']"></label>
              <span class="small muted">3–40 characters: lower-case letters, digits, dot, dash or underscore.</span>
              @if (fields()['username']) { <span class="error-text">{{ fields()['username'] }}</span> }
              <label class="field">Choose a password<input name="p" type="password" [(ngModel)]="password" (ngModelChange)="pw.set($event)" required autocomplete="new-password" [attr.aria-invalid]="!!fields()['password']"></label>
              <ul class="rules">@for (r of rules(); track r.text) { <li [class.ok]="r.ok">{{ r.ok ? '✓' : '•' }} {{ r.text }}</li> }</ul>
              @if (fields()['password']) { <span class="error-text">{{ fields()['password'] }}</span> }
              <label class="field">Confirm password<input name="p2" type="password" [(ngModel)]="password2" required autocomplete="new-password"></label>
              @if (password2 && password2 !== password) { <span class="error-text">The passwords don't match.</span> }
              <div class="row" style="gap:8px"><button class="btn primary" type="submit" [disabled]="busy() || password !== password2">Create account</button>
                <button class="btn" type="button" (click)="start()" [disabled]="busy()">Send a new code</button></div>
            </form>
          }
          @case (3) {
            <p class="banner" role="status">Your account <strong>{{ username }}</strong> is ready.</p>
            <ol class="small"><li>Sign in with your new user ID and password.</li>
              <li>You'll then be asked to link an authenticator app (Google Authenticator, Microsoft Authenticator or similar). It's required for student accounts.</li></ol>
            <a class="btn primary" routerLink="/login" style="width:100%;justify-content:center">Go to sign in</a>
          }
        }
        <p class="small muted" style="margin-top:16px">Already registered? <a routerLink="/login">Sign in</a>. Staff accounts are created by the college.</p>
      </main>
    </div>`,
})
export class RegisterPage {
  private api = inject(Api);
  auth = inject(AuthService);
  step = signal(1);
  busy = signal(false);
  error = signal<string | null>(null);
  fields = signal<Record<string, string>>({});
  notice = signal('');
  devCode = signal<string | null>(null);
  sid = ''; dob = ''; email = ''; code = ''; username = ''; password = ''; password2 = '';
  pw = signal('');
  rules = computed(() => this.check(this.pw()));

  check(p: string) {
    return [
      { text: 'At least 12 characters', ok: p.length >= 12 },
      { text: 'An upper-case and a lower-case letter', ok: /[A-Z]/.test(p) && /[a-z]/.test(p) },
      { text: 'A number', ok: /\d/.test(p) },
      { text: 'A symbol, e.g. ! @ # %', ok: /[^A-Za-z0-9]/.test(p) },
    ];
  }

  private fail(e: unknown) {
    if (e instanceof ApiError && Object.keys(e.fields).length) { this.fields.set(e.fields); this.error.set(null); }
    else { this.error.set(message(e)); }
  }

  async start() {
    this.busy.set(true); this.error.set(null); this.fields.set({});
    try {
      const r = await this.api.post<{ message: string; dev_code?: string }>('/register/start', { student_id: this.sid, date_of_birth: this.dob, email: this.email });
      this.notice.set(r.message); this.devCode.set(r.dev_code || null); this.step.set(2);
    } catch (e) { this.fail(e); }
    finally { this.busy.set(false); }
  }

  async complete() {
    this.busy.set(true); this.error.set(null); this.fields.set({});
    try {
      await this.api.post('/register/complete', { student_id: this.sid, email: this.email, code: this.code, username: this.username, password: this.password });
      this.password = this.password2 = this.code = ''; this.pw.set('');
      this.step.set(3);
    } catch (e) { this.fail(e); }
    finally { this.busy.set(false); }
  }
}
