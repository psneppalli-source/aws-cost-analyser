import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../core/api.service';
import { Session } from '../core/session.service';
import { message } from './page';

/** "How do I…?" assistant: answers only from the app's own help text (backend HELP_TEXT). */
@Component({
  selector: 'app-help-widget',
  imports: [FormsModule],
  styles: [`
    .fab{position:fixed;right:20px;bottom:20px;z-index:40;display:inline-flex;align-items:center;gap:8px;border:0;border-radius:999px;
      padding:11px 16px;font:inherit;font-weight:600;color:#fff;cursor:pointer;background:linear-gradient(135deg,#14a3a3,#6f5bd6);
      box-shadow:0 8px 24px rgba(15,60,90,.3)}
    .panel{position:fixed;right:20px;bottom:76px;z-index:41;width:min(380px,calc(100vw - 32px));max-height:min(560px,calc(100vh - 110px));
      display:flex;flex-direction:column;background:#fff;border:1px solid var(--line);border-radius:16px;box-shadow:0 18px 48px rgba(16,32,56,.22);overflow:hidden}
    .ph{display:flex;align-items:center;gap:8px;padding:12px 14px;color:#fff;background:linear-gradient(135deg,#0d1b2e,#13263f)}
    .ph strong{flex:1} .x{border:0;background:rgba(255,255,255,.12);color:#fff;width:28px;height:28px;border-radius:8px;cursor:pointer}
    .body{padding:12px 14px;overflow-y:auto;flex:1}
    .chips{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0 10px}
    .chips button{border:1px solid var(--line);background:#f6f8fb;border-radius:999px;padding:4px 10px;font-size:12.5px;color:var(--ink-2);cursor:pointer}
    form{display:flex;gap:6px;padding:10px 12px;border-top:1px solid var(--line)} form input{flex:1}
    .a p{margin:0 0 6px;font-weight:600} .a ul{margin:0;padding-left:18px} .a li{margin:4px 0;font-size:14px}
    .q{font-size:13px;color:var(--muted);margin:10px 0 4px}
    @media (max-width:860px){ .fab{bottom:14px;right:14px;padding:10px 14px} .panel{right:12px;bottom:66px} }
  `],
  template: `
    @if (session.me()?.ai) {
      @if (open()) {
        <section class="panel" role="dialog" aria-label="Help">
          <div class="ph"><strong>✨ How can I help?</strong><button class="x" type="button" (click)="open.set(false)" aria-label="Close help">✕</button></div>
          <div class="body" aria-live="polite">
            @if (!history().length) {
              <p class="small muted">Ask how to do something in Smart Campus. Answers come from the app's help pages.</p>
              <div class="chips">@for (ex of examples(); track ex) { <button type="button" (click)="q = ex; ask()">{{ ex }}</button> }</div>
            }
            @for (h of history(); track $index) {
              <p class="q">You asked: {{ h.q }}</p>
              <div class="a">@if (h.lines[0] && !h.lines[0].startsWith('- ')) { <p>{{ h.lines[0] }}</p> }
                <ul>@for (l of h.lines; track $index) { @if (l.startsWith('- ')) { <li>{{ l.slice(2) }}</li> } }</ul></div>
            }
            @if (busy()) { <p class="small muted">Looking that up…</p> }
            @if (error()) { <p class="error-text">{{ error() }}</p> }
          </div>
          <form (submit)="$event.preventDefault(); ask()">
            <input name="hq" [(ngModel)]="q" placeholder="e.g. How do I reset my password?" maxlength="300" aria-label="Your question">
            <button class="btn primary small" type="submit" [disabled]="busy() || q.trim().length < 4">Ask</button>
          </form>
        </section>
      }
      <button class="fab" type="button" (click)="open.set(!open())" [attr.aria-expanded]="open()">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 015.8 1c0 2-3 3-3 3M12 17h.01"/></svg>
        Help</button>
    }`,
})
export class HelpWidget {
  private api = inject(Api);
  session = inject(Session);
  open = signal(false);
  busy = signal(false);
  error = signal<string | null>(null);
  history = signal<{ q: string; lines: string[] }[]>([]);
  q = '';
  examples() {
    return this.session.isStudent()
      ? ['How do I add a certificate?', 'How do I set up my authenticator?', 'What is the Success Score?']
      : ['How do I create a support plan?', 'How do I import a CSV?', 'How do I reset a user’s password?'];
  }
  async ask() {
    const q = this.q.trim();
    if (q.length < 4) return;
    this.busy.set(true); this.error.set(null);
    try {
      const r = await this.api.post<{ lines: string[] }>('/ai/tool', { tool: 'help', question: q });
      this.history.update((h) => [...h, { q, lines: r.lines }].slice(-5)); this.q = '';
    } catch (e) { this.error.set(message(e)); }
    finally { this.busy.set(false); }
  }
}
