import { Component, computed, inject, input, signal } from '@angular/core';
import { Api } from '../core/api.service';
import { Session } from '../core/session.service';
import { message } from './page';

interface Summary { lines: string[]; model: string; generated_at: string; cached: boolean; }

/**
 * "AI summary" panel. The server builds the facts from what this user may already see (no names or IDs are sent
 * to the model), so the panel only says which page it summarises. Hidden when AI is not configured.
 */
@Component({
  selector: 'app-ai-summary',
  styles: [`
    :host{display:block}
    .ai{position:relative;border-radius:14px;padding:1px;background:linear-gradient(135deg,#14a3a3,#6f5bd6 55%,#2a4a73);margin:0 0 16px}
    .in{border-radius:13px;background:linear-gradient(180deg,#ffffff,#f7f9fc);padding:14px 16px}
    .head{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
    .head h2{margin:0;font-size:15px;display:flex;align-items:center;gap:8px;color:var(--navy-900)}
    .spark{width:26px;height:26px;border-radius:8px;display:grid;place-items:center;color:#fff;background:linear-gradient(135deg,#14a3a3,#6f5bd6)}
    .hint{color:var(--muted);font-size:12.5px;flex:1;min-width:180px}
    .go{display:inline-flex;align-items:center;gap:8px;border:0;border-radius:10px;padding:8px 14px;font-weight:600;font-size:13.5px;cursor:pointer;
      color:#fff;background:linear-gradient(135deg,#14a3a3,#0b6e6e);box-shadow:0 4px 12px rgba(15,138,138,.25)}
    .go[disabled]{opacity:.65;cursor:default}
    .headline{font-weight:600;color:var(--navy-900);margin:12px 0 6px;font-size:14.5px;line-height:1.45}
    .para{margin:0 0 8px;font-size:14px;line-height:1.5}
    ul{margin:0;padding-left:20px} li{margin:5px 0;line-height:1.45;font-size:14px}
    .foot{margin-top:10px;font-size:11.5px;color:var(--muted)}
    .skel{height:12px;border-radius:6px;margin:10px 0;background:linear-gradient(90deg,#eef1f5 25%,#e2e8f0 37%,#eef1f5 63%);background-size:400% 100%;animation:sh 1.2s ease infinite}
    @keyframes sh{0%{background-position:100% 50%}100%{background-position:0 50%}}
    .err{color:var(--high);font-size:13.5px;margin:10px 0 0}
  `],
  template: `
    @if (available()) {
      <section class="ai" aria-label="AI summary">
        <div class="in">
          <div class="head">
            <h2><span class="spark" aria-hidden="true"><svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l1.9 5.6L19.5 9.5l-5.6 1.9L12 17l-1.9-5.6L4.5 9.5l5.6-1.9zM19 14l.9 2.6 2.6.9-2.6.9L19 21l-.9-2.6-2.6-.9 2.6-.9z"/></svg></span>
              AI summary</h2>
            <span class="hint">{{ hint() }}</span>
            <button class="go" type="button" (click)="run()" [disabled]="busy()">
              @if (busy()) { Summarising… } @else if (result()) { Refresh } @else { Summarise {{ subject() }} }</button>
          </div>
          @if (busy() && !result()) { <div class="skel" style="width:70%"></div><div class="skel"></div><div class="skel" style="width:85%"></div> }
          @if (error()) { <p class="err" role="alert">{{ error() }}</p> }
          @if (result(); as r) {
            @if (headline()) { <p class="headline">{{ headline() }}</p> }
            @for (t of paras(); track $index) { <p class="para">{{ t }}</p> }
            @if (bullets().length) { <ul>@for (b of bullets(); track $index) { <li>{{ b }}</li> }</ul> }
            <p class="foot">AI-generated from the figures on this page (no names or IDs are shared) · {{ r.model }}{{ r.cached ? ' · saved summary' : '' }}.
              It can be wrong: check the figures before acting.</p>
          }
        </div>
      </section>
    }`,
})
export class AiSummary {
  private api = inject(Api);
  private session = inject(Session);
  kind = input.required<'student' | 'overview' | 'insights' | 'academic' | 'placement'>();
  studentId = input<string | null>(null);
  department = input<string | null>(null);
  year = input<string | number | null>(null);
  subject = input('this page');
  result = signal<Summary | null>(null);
  busy = signal(false);
  error = signal<string | null>(null);

  available = computed(() => !!this.session.me()?.ai);
  hint = computed(() => this.kind() === 'student'
    ? 'A short, plain-language read of the progress and risks shown here, with next steps.'
    : 'Key patterns in these figures and suggested next steps, in plain language.');
  headline = computed(() => (this.result()?.lines || []).find((l) => !l.startsWith('- ')) || '');
  paras = computed(() => (this.result()?.lines || []).filter((l) => !l.startsWith('- ')).slice(1));
  bullets = computed(() => (this.result()?.lines || []).filter((l) => l.startsWith('- ')).map((l) => l.slice(2)));

  async run() {
    this.busy.set(true); this.error.set(null);
    try {
      this.result.set(await this.api.post<Summary>('/ai/summary', { kind: this.kind(), student_id: this.studentId(),
        department: this.department() || null, year: this.year() || null }));
    } catch (e) { this.error.set(message(e)); }
    finally { this.busy.set(false); }
  }
}
