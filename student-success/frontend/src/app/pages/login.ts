import { Component, OnInit, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../core/auth.service';
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
    .si-side{display:grid;place-items:center;padding:40px 24px}
    .panel{width:min(420px,100%)}
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
          <h2 id="t">Welcome back</h2>
          @if (auth.config()?.mode === 'cognito') {
            <p class="si-sub">Sign in with your user ID, password and authenticator app code.</p>
            @if (error()) { <p class="banner danger" role="alert">{{ error() }}</p> }
            <button class="btn primary go" type="button" (click)="cognito()" [disabled]="busy()">
              {{ busy() ? 'Opening secure sign-in…' : 'Sign in' }}
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg></button>
            <div class="secure"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 2l8 4v6c0 5-3.5 9-8 10-4.5-1-8-5-8-10V6z"/></svg>
              Protected by two-step verification</div>
            <nav class="help" aria-label="Account help">
              <a class="tile" routerLink="/recover"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="8" cy="15" r="4"/><path d="M10.8 12.2L20 3M16 7l3 3"/></svg>
                <span>Forgot password?<small>Reset it by email</small></span></a>
              <a class="tile" routerLink="/recover" [queryParams]="{ mode: 'mfa' }"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/></svg>
                <span>Lost your phone?<small>Reset authenticator</small></span></a>
            </nav>
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
          <div class="newbie">
            <div><strong>New student?</strong><span>Create your account with your student ID and date of birth.</span></div>
            <a class="btn" routerLink="/register">Create account</a>
          </div>
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
