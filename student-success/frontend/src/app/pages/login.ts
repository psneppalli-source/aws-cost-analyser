import { Component, OnInit, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../core/auth.service';
import { Session } from '../core/session.service';

interface Persona { username: string; display_name: string; }

@Component({
  selector: 'app-login-page',
  imports: [RouterLink, FormsModule],
  template: `
    <div class="login-wrap">
      <main class="login-card" aria-labelledby="t">
        <div class="brand" style="color:var(--navy-900);padding:0 0 12px"><div class="brand-mark" aria-hidden="true">SC</div>
          <div><strong id="t">Smart Campus Analytics</strong><small style="color:var(--muted)">Predict, optimise and improve student success</small></div></div>
        @if (error()) { <p class="banner danger" role="alert">{{ error() }}</p> }
        @if (auth.config()?.mode === 'cognito') {
          <p>Sign in with the account your college administrator created for you. There is no public registration.</p>
          <button class="btn primary" type="button" style="width:100%" (click)="cognito()" [disabled]="busy()">Sign in</button>
          <p class="small muted" style="margin-top:14px">Staff accounts are created by the college. Forgotten your password? Use “Forgot your password?” on the sign-in page.</p>
        } @else {
          <p class="banner warn small"><strong>Local demonstration sign-in.</strong> Choose a persona. This mode is for local development only and is refused by AWS deployments.</p>
          <div class="stack" role="list">
            @for (p of personas(); track p.username) {
              <button class="btn" role="listitem" type="button" style="justify-content:flex-start;text-align:left" [disabled]="busy()" (click)="local(p.username)">
                <span><strong>{{ p.display_name }}</strong><br><span class="small muted mono">{{ p.username }}</span></span></button>
            }
            <form class="row" style="gap:6px;margin-top:6px" (submit)="$event.preventDefault(); local(other)">
              <input name="o" [(ngModel)]="other" placeholder="or another local user ID" aria-label="Local user ID" style="flex:1">
              <button class="btn" type="submit" [disabled]="busy() || !other">Sign in</button></form>
            @if (!personas().length) { <p class="muted">No personas yet. Run <span class="mono">python -m app.seed</span> in backend/ first.</p> }
          </div>
        }
        <p class="small" style="margin-top:16px;border-top:1px solid var(--line);padding-top:12px">New student? <a routerLink="/register">Create your account</a> using your student ID, date of birth and college email.</p>
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

  async cognito() {
    this.busy.set(true);
    try { await this.auth.startCognito(); } catch (e) { this.error.set((e as Error).message); this.busy.set(false); }
  }

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
