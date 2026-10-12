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
    .ai.embedded{padding:0;background:none;margin:0} .ai.embedded .in{padding:0;background:none}
    .ai.embedded .hint{order:0;flex-basis:auto;flex:1;margin:0;min-width:200px}
    .in{border-radius:13px;background:linear-gradient(180deg,#ffffff,#f7f9fc);padding:14px 16px}
    .head{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
    .head h2{margin:0;font-size:15px;display:flex;align-items:center;gap:8px;color:var(--navy-900)}
    .spark{width:26px;height:26px;border-radius:8px;display:grid;place-items:center;color:#fff;background:linear-gradient(135deg,#14a3a3,#6f5bd6)}
    .hint{color:var(--muted);font-size:12.5px;order:3;flex-basis:100%;margin-top:-2px}
    .head h2{flex:1}
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
      <section class="ai" [class.embedded]="embedded()" [attr.aria-label]="heading()">
        <div class="in">
          <div class="head">
            <h2 [class.sr-only]="embedded()"><span class="spark" aria-hidden="true"><svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l1.9 5.6L19.5 9.5l-5.6 1.9L12 17l-1.9-5.6L4.5 9.5l5.6-1.9zM19 14l.9 2.6 2.6.9-2.6.9L19 21l-.9-2.6-2.6-.9 2.6-.9z"/></svg></span>
              {{ heading() }}</h2>
            <span class="hint">{{ hint() }}</span>
            @if (printable() && result()) { <button class="btn small" type="button" (click)="print()">Print</button> }
            <button class="go" type="button" (click)="run()" [disabled]="busy()">
              @if (busy()) { Working… } @else if (result()) { Refresh } @else { {{ action() || 'Summarise ' + subject() }} }</button>
          </div>
          @if (busy() && !result()) { <div class="skel" style="width:70%"></div><div class="skel"></div><div class="skel" style="width:85%"></div> }
          @if (error()) { <p class="err" role="alert">{{ error() }}</p> }
          @if (result(); as r) {
            @if (headline()) { <p class="headline">{{ headline() }}</p> }
            @for (t of paras(); track $index) { <p class="para">{{ t }}</p> }
            @if (bullets().length) { <ul>@for (b of bullets(); track $index) { <li>{{ b }}</li> }</ul> }
            <p class="foot">AI-generated from {{ kind() === 'coach' ? 'your own records' : 'the figures on this page' }} (no names or IDs are shared) · {{ r.model }}{{ r.cached ? ' · saved summary' : '' }}.
              It can be wrong: check the figures before acting.</p>
          }
        </div>
      </section>
    }`,
})
export class AiSummary {
  private api = inject(Api);
  private session = inject(Session);
  kind = input.required<'student' | 'overview' | 'insights' | 'academic' | 'placement' | 'coach' | 'brief' | 'explain' | 'digest' | 'outcomes'>();
  printable = input(false);
  embedded = input(false);
  heading = input('AI summary');
  action = input<string | null>(null);
  studentId = input<string | null>(null);
  department = input<string | null>(null);
  year = input<string | number | null>(null);
  subject = input('this page');
  result = signal<Summary | null>(null);
  busy = signal(false);
  error = signal<string | null>(null);

  available = computed(() => !!this.session.me()?.ai);
  private static HINTS: Record<string, string> = {
    coach: 'A practical plan for the coming week, based on your own marks, attendance and focus areas.',
    student: 'A short, plain-language read of the progress and risks shown here, with next steps.',
    brief: 'One page for your next meeting: what changed, plans due, and questions to ask.',
    explain: 'Why the Success Score moved, component by component. The figures are calculated by the system.',
    digest: "What changed this week: new early warnings, overdue plans and the biggest movers.",
    outcomes: 'How completed support plans went, by category. Figures are calculated by the system.',
  };
  hint = computed(() => AiSummary.HINTS[this.kind()] || 'Key patterns in these figures and suggested next steps, in plain language.');
  headline = computed(() => (this.result()?.lines || []).find((l) => !l.startsWith('- ')) || '');
  paras = computed(() => (this.result()?.lines || []).filter((l) => !l.startsWith('- ')).slice(1));
  bullets = computed(() => (this.result()?.lines || []).filter((l) => l.startsWith('- ')).map((l) => l.slice(2)));

  /** Print just this panel's text in a clean window. */
  print() {
    const r = this.result(); if (!r) return;
    const w = window.open('', '_blank', 'width=720,height=800'); if (!w) return;
    const esc = (t: string) => t.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]!));
    w.document.write(`<!doctype html><meta charset="utf-8"><title>${esc(this.heading())}</title><body style="font:15px/1.5 Segoe UI,Arial,sans-serif;margin:32px;color:#13263f">`
      + `<h2 style="margin:0 0 4px">${esc(this.heading())}</h2><p style="color:#5f7189;margin:0 0 16px">${new Date().toLocaleDateString()}</p>`
      + `<p><strong>${esc(this.headline())}</strong></p>` + this.paras().map((x) => `<p>${esc(x)}</p>`).join('')
      + `<ul>${this.bullets().map((b) => `<li style="margin:6px 0">${esc(b)}</li>`).join('')}</ul>`
      + `<p style="color:#5f7189;font-size:12px;margin-top:24px">AI-generated draft from recorded figures; check before relying on it.</p></body>`);
    w.document.close(); w.focus(); w.print();
  }

  async run() {
    this.busy.set(true); this.error.set(null);
    try {
      const tool = ['brief', 'explain', 'digest', 'outcomes'].includes(this.kind());
      const body = { kind: this.kind(), tool: this.kind(), student_id: this.studentId(), department: this.department() || null, year: this.year() || null };
      this.result.set(await this.api.post<Summary>(tool ? '/ai/tool' : '/ai/summary', body));
    } catch (e) { this.error.set(message(e)); }
    finally { this.busy.set(false); }
  }
}
