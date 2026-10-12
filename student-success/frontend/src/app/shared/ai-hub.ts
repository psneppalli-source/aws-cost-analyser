import { Component, computed, inject, input, signal } from '@angular/core';
import { Session } from '../core/session.service';
import { AiSummary } from './ai-summary';

export interface AiTool { kind: 'student' | 'overview' | 'insights' | 'academic' | 'placement' | 'coach' | 'brief' | 'explain' | 'digest' | 'outcomes';
  label: string; action: string; printable?: boolean; subject?: string; }

/**
 * One "AI assistant" card per page instead of several stacked panels: a row of tools, one visible at a time.
 * Every tool stays mounted, so switching back keeps its result.
 */
@Component({
  selector: 'app-ai-hub',
  imports: [AiSummary],
  styles: [`
    :host{display:block;margin:0 0 18px}
    .hub{position:relative;border-radius:16px;padding:1px;background:linear-gradient(135deg,#14a3a3,#6f5bd6 55%,#2a4a73)}
    .in{border-radius:15px;background:linear-gradient(180deg,#ffffff,#f8fafd);padding:14px 16px 16px}
    .top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px}
    .spark{width:30px;height:30px;border-radius:9px;display:grid;place-items:center;color:#fff;background:linear-gradient(135deg,#14a3a3,#6f5bd6);
      box-shadow:0 4px 12px rgba(111,91,214,.3)}
    h2{margin:0;font-size:15.5px;color:var(--navy-900)} .note{color:var(--muted);font-size:12px;margin-left:auto}
    .tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
    .tabs button{border:1px solid var(--line);background:#fff;border-radius:999px;padding:6px 13px;font:inherit;font-size:13px;font-weight:600;
      color:var(--ink-2);cursor:pointer;transition:all .15s}
    .tabs button:hover{border-color:#b8c5d5}
    .tabs button[aria-selected=true]{color:#fff;border-color:transparent;background:linear-gradient(135deg,#14a3a3,#0b6e6e);box-shadow:0 3px 10px rgba(15,138,138,.25)}
    @media (max-width:860px){ .note{display:none} }
  `],
  template: `
    @if (available()) {
      <section class="hub" aria-label="AI assistant">
        <div class="in">
          <div class="top"><span class="spark" aria-hidden="true"><svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l1.9 5.6L19.5 9.5l-5.6 1.9L12 17l-1.9-5.6L4.5 9.5l5.6-1.9zM19 14l.9 2.6 2.6.9-2.6.9L19 21l-.9-2.6-2.6-.9 2.6-.9z"/></svg></span>
            <h2>AI assistant</h2><span class="note">Free AI · no names or IDs shared · always check before acting</span></div>
          @if (tools().length > 1) {
            <div class="tabs" role="tablist" aria-label="AI tools">
              @for (t of tools(); track t.kind; let i = $index) {
                <button role="tab" type="button" [attr.aria-selected]="active() === i" (click)="active.set(i)">{{ t.label }}</button> }
            </div>
          }
          @for (t of tools(); track t.kind; let i = $index) {
            <div role="tabpanel" [hidden]="active() !== i">
              <app-ai-summary [kind]="t.kind" [heading]="t.label" [action]="t.action" [printable]="!!t.printable" [embedded]="true"
                [studentId]="studentId()" [department]="department()" [year]="year()" [subject]="t.subject || 'this page'" />
            </div>
          }
        </div>
      </section>
    }`,
})
export class AiHub {
  private session = inject(Session);
  tools = input.required<AiTool[]>();
  studentId = input<string | null>(null);
  department = input<string | null>(null);
  year = input<string | number | null>(null);
  active = signal(0);
  available = computed(() => !!this.session.me()?.ai && this.tools().length > 0);
}
