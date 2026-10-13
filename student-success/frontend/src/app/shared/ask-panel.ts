import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Api } from '../core/api.service';
import { Session } from '../core/session.service';
import { HBar, HBars } from './charts';
import { message } from './page';

interface Answer {
  supported: boolean; question: string; message?: string; source: 'ai' | 'keywords'; model: string | null;
  title?: string; kind?: 'students' | 'groups' | 'risk' | 'bands'; columns?: string[];
  rows?: Record<string, string | number | null>[]; chart?: { label: string; value: number | null }[]; sentence?: string;
}

/**
 * "Ask about your students": AI turns the question into one of a few checked queries; the server runs it on the
 * rows this user may see and writes the answer, so every number on screen comes from the data, not the model.
 */
@Component({
  selector: 'app-ask-panel',
  imports: [FormsModule, RouterLink, HBars],
  styles: [`
    :host{display:block;margin:0 0 16px}
    .box{border:1px solid var(--line);border-radius:14px;background:#fff;padding:14px 16px}
    .head{display:flex;align-items:center;gap:10px;margin-bottom:10px}
    .head h2{margin:0;font-size:15px;color:var(--navy-900)}
    .spark{width:26px;height:26px;border-radius:8px;display:grid;place-items:center;color:#fff;background:linear-gradient(135deg,#14a3a3,#6f5bd6)}
    form{display:flex;gap:8px;flex-wrap:wrap}
    .q{flex:1;min-width:220px;display:flex;align-items:center;border:1.5px solid var(--line);border-radius:12px;padding:0 12px;background:#fff}
    .q:focus-within{border-color:var(--teal-500);box-shadow:0 0 0 4px rgba(20,163,163,.15)}
    .q input{border:0;outline:0;box-shadow:none;flex:1;padding:10px 0;font-size:14.5px;background:transparent}
    .go{border:0;border-radius:12px;padding:0 16px;min-height:42px;font-weight:600;color:#fff;cursor:pointer;background:linear-gradient(135deg,#14a3a3,#0b6e6e)}
    .go[disabled]{opacity:.6;cursor:default}
    .chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
    .chips button{border:1px solid var(--line);background:#f6f8fb;border-radius:999px;padding:4px 10px;font-size:12.5px;color:var(--ink-2);cursor:pointer}
    .chips button:hover{border-color:var(--teal-500);color:var(--teal-700)}
    .ans{margin-top:14px;border-top:1px solid var(--line);padding-top:12px}
    .ans h3{margin:0 0 4px;font-size:14.5px} .sentence{margin:0 0 10px;font-weight:600;color:var(--navy-900)}
    .meta{font-size:11.5px;color:var(--muted);margin-top:8px}
    td.num,th.num{text-align:right}
  `],
  template: `
    <section class="box" aria-labelledby="ask-h">
      <div class="head"><span class="spark" aria-hidden="true"><svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l1.9 5.6L19.5 9.5l-5.6 1.9L12 17l-1.9-5.6L4.5 9.5l5.6-1.9zM19 14l.9 2.6 2.6.9-2.6.9L19 21l-.9-2.6-2.6-.9 2.6-.9z"/></svg></span>
        <h2 id="ask-h">Ask about your students</h2></div>
      <form (submit)="$event.preventDefault(); ask()">
        <label class="q"><span class="sr-only">Question</span>
          <input name="q" [(ngModel)]="question" maxlength="300" autocomplete="off" placeholder="e.g. Which department has the lowest attendance?"></label>
        <button class="go" type="submit" [disabled]="busy() || question.trim().length < 4">{{ busy() ? 'Working…' : 'Ask' }}</button>
      </form>
      <div class="chips" aria-label="Example questions">
        @for (ex of examples; track ex) { <button type="button" (click)="question = ex; ask()" [disabled]="busy()">{{ ex }}</button> }
      </div>
      @if (error()) { <p class="error-text" role="alert" style="margin-top:10px">{{ error() }}</p> }
      @if (a(); as a) {
        <div class="ans" aria-live="polite">
          @if (!a.supported) { <p>{{ a.message }}</p> }
          @else {
            <h3>{{ a.title }}</h3>
            <p class="sentence">{{ a.sentence }}</p>
            @if (bars().length) { <app-hbars [data]="bars()" [label]="a.title || 'Answer'" [max]="a.kind === 'risk' || a.kind === 'bands' ? null : 100" /> }
            <div class="table-wrap" style="margin-top:8px"><table>
              <thead><tr>@for (c of a.columns; track c; let i = $index) { <th [class.num]="i > 0">{{ c }}</th> }</tr></thead>
              <tbody>@for (r of a.rows; track $index) {
                <tr>@if (a.kind === 'students') {
                    <td><a [routerLink]="['/students', 'real', r['student_id']]">{{ r['name'] || r['student_id'] }}</a></td>
                    <td class="num">{{ r['class'] }}</td><td class="num">{{ r['value'] }}</td>
                  } @else {
                    <td>{{ r['group'] }}</td>
                    @for (k of keys(); track k) { <td class="num">{{ r[k] ?? '–' }}</td> }
                  }</tr>
              }</tbody></table></div>
            <p class="meta">Figures are calculated from your students' records, not written by AI.
              {{ a.source === 'ai' ? 'AI interpreted the question.' : 'Question read by keywords.' }} Check the heading matches what you asked.</p>
          }
        </div>
      }
    </section>`,
})
export class AskPanel {
  private api = inject(Api);
  session = inject(Session);
  question = '';
  busy = signal(false);
  error = signal<string | null>(null);
  a = signal<Answer | null>(null);
  examples = ['Which department has the lowest attendance?', 'Average score by year', '5 students with the lowest LMS activity',
    'How many students are at placement risk by department?', 'Score bands in CSE'];
  bars = computed<HBar[]>(() => (this.a()?.chart || []).map((c) => ({ label: c.label, value: c.value })));
  keys = computed(() => {
    const k = this.a()?.kind;
    if (k === 'groups') return ['value', 'students'];
    if (k === 'risk') return ['high', 'medium', 'low', 'insufficient_data', 'students'];
    if (k === 'bands') return ['Strong', 'On track', 'Needs attention', 'At risk', 'Insufficient data', 'students'];
    return [];
  });

  async ask() {
    if (this.question.trim().length < 4) return;
    this.busy.set(true); this.error.set(null);
    try { this.a.set(await this.api.post<Answer>('/ai/ask', { question: this.question })); }
    catch (e) { this.error.set(message(e)); }
    finally { this.busy.set(false); }
  }
}
