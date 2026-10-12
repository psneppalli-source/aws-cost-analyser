import { Component, computed, effect, inject, input, signal, untracked } from '@angular/core';
import { AiHub, AiTool } from '../shared/ai-hub';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Api, ApiError } from '../core/api.service';
import { Session } from '../core/session.service';
import { COMPONENTS, IV_CATEGORIES, OUTCOMES, SEGMENTS, pct, when } from '../shared/labels';
import { message } from '../shared/page';
import { RiskBadge, StateView, StatusChip } from '../shared/ui';
import { Line, MultiLine, Pair, PairedBars, SERIES } from '../shared/charts';

interface Flag { rule: string; label: string; indicator: string; observed: number; operator: string; threshold: number; level: string;
  observed_period: string; suggested_intervention: { key: string; title: string; category: string; owner_role: string }; }
interface Risk { kind: string; level: string; flags?: Flag[]; missing?: string[]; explanation: string; assumption_notice: string;
  calculated_at: string; period: string; suggested_intervention?: { key: string; title: string; category: string; owner_role: string }; }
interface ScoreRow { component: string; label: string; configured_weight: number; status: string; value: number | null; applied_weight: number | null; contribution: number | null; }
interface Insight {
  name: string; period: string; score?: number | null; indicative_score?: number | null; status?: string; band?: string | null; coverage?: number;
  profile?: string; components?: Record<string, { value: number | null; indicators: Record<string, number | null> }>;
  risks?: { academic?: Risk; placement?: Risk }; segments?: { key: string; label: string; reasons: string[] }[] | string[];
  support_needs?: string[]; eligibility?: Record<string, number>; score_rows?: ScoreRow[]; indicators?: Record<string, number | null>;
  sources?: Record<string, string>; summary?: string; scoring_version?: string; calculated_at?: string; recalc_status?: string;
  trend?: { period: string; score: number | null; status: string; profile: string; comparable_with_current: boolean }[];
}
interface History { period: string; score: number | null; indicative_score: number | null; status: string; band: string | null; coverage: number;
  profile: string; rows: ScoreRow[]; scoring_version: string; missing: string[]; }
interface Recommendation { key: string; title: string; category: string; owner_role: string; risk: string; level: string;
  evidence: { rule: string; label: string; observed: number | null; threshold: number | null; operator: string | null; period: string }[]; }
interface Snapshot { period?: string; score?: number | null; status?: string; profile?: string; academic?: string; placement?: string; }
interface Intervention {
  intervention_id: string; title: string; category: string; status: string; owner_sub: string; owner_name: string; due_date: string; review_date: string;
  detail?: string; evidence?: Recommendation['evidence']; outcome?: { result: string; note: string; recorded_at: string; after: Snapshot } | null;
  overdue: boolean; review_due: boolean; days_overdue: number; version: number; created_at: string; created_by_name?: string; baseline?: Snapshot;
  comparison?: { before: Snapshot; after: Snapshot; comparable: boolean; change: number | null; note: string };
}
interface Note { note_id: string; intervention_id: string; visibility: string; text: string; author_name: string; created_at: string; }
interface Rec { record_key: string; category: string; period: string; verification?: string; version: number; source?: string;
  updated_at: string; [k: string]: unknown; }
interface Profile {
  student: { student_id: string; name: string; department: string; year: number; programme?: string; email?: string; date_of_birth?: string; status?: string;
    mentor_name?: string; mentor_sub?: string; version: number; dataset: string; };
  insight: Insight | null; history: History[]; recommendations: Recommendation[]; interventions: Intervention[]; notes: Note[];
  corrections: { correction_id: string; category: string; period: string; status: string; proposed: Record<string, unknown>; current: Record<string, unknown>; requested_by_name: string; requested_at: string }[];
  permissions: Record<string, boolean>;
  cohort?: { label: string; students: number; score: number | null; components: Record<string, number | null> };
}
interface Staff { sub: string; display_name: string; roles: string[]; }

const RECORD_COLS: Record<string, string[]> = {
  academic_result: ['semester', 'sgpa', 'cgpa', 'backlogs'], marks: ['subject', 'assessment', 'score', 'max_score'],
  attendance: ['subject', 'classes_held', 'classes_attended'], lms: ['assignments_due', 'assignments_submitted', 'logins'],
  engagement: ['activity_type', 'name', 'role'], certification: ['name', 'issuer', 'evidence_ref'],
  placement_assessment: ['assessment_type', 'score', 'readiness_note'], skills: ['technical', 'communication'],
  feedback: ['satisfaction', 'stress', 'support_needed', 'comment'],
};

@Component({
  selector: 'app-profile-page',
  imports: [AiHub, FormsModule, RouterLink, StateView, RiskBadge, StatusChip, MultiLine, PairedBars],
  styles: [`.tabs{display:flex;gap:4px;border-bottom:1px solid var(--line);margin:8px 0 16px;flex-wrap:wrap}
    .tabs button{background:none;border:0;padding:10px 14px;font:inherit;cursor:pointer;color:var(--muted);border-bottom:3px solid transparent}
    .tabs button[aria-selected=true]{color:var(--navy-900);border-color:var(--teal-500);font-weight:600}
    .bigscore{font-size:44px;font-weight:700;color:var(--navy-900);line-height:1}
    dl.facts{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;margin:0;font-size:14px} dl.facts dt{color:var(--muted)} dl.facts dd{margin:0}`],
  template: `
    <app-state [loading]="loading() && !p()" [error]="error()" (retry)="load()" />
    @if (p(); as p) {
      <div class="page-head">
        <div><h1 style="margin-bottom:2px">{{ p.student.name }}</h1>
          <span class="mono muted">{{ p.student.student_id }}</span> · {{ p.student.department }} · Year {{ p.student.year }} · {{ p.student.programme }}
</div>
        <span class="spacer"></span>
        <button class="btn small" type="button" (click)="load()" [disabled]="loading()">Refresh</button>
        @if (!isOwn()) { <a class="btn small" routerLink="/students">Back to students</a> }
      </div>
      @if (ins()?.recalc_status === 'stale' || ins()?.recalc_status === 'failed') {
        <p class="banner warn">Recent changes are waiting to be included in this student's score.
          @if (session.can('insight', 'recompute')) { An administrator can run <em>Recalculate</em> on the Configuration page. }</p>
      }
      <app-ai-hub [tools]="aiTools()" [studentId]="p.student.student_id" />
      <div class="tabs" role="tablist">
        @for (t of tabs(); track t[0]) {
          <button role="tab" type="button" [attr.aria-selected]="tab() === t[0]" (click)="tab.set(t[0])">{{ t[1] }}</button>
        }
      </div>

      @switch (tab()) {
      @case ('summary') {
        <div class="grid g3">
          <section class="card" aria-labelledby="sc">
            <h2 id="sc">Success Score</h2>
            @if (ins(); as i) {
              @if (i.score !== undefined) {
                <div class="row" style="align-items:baseline;gap:8px"><span class="bigscore">{{ i.score ?? '–' }}</span><span class="muted">/ 100</span></div>
                <div class="row" style="gap:6px;margin:6px 0 10px"><app-status [status]="i.status" />@if (i.band) { <span class="chip teal">{{ i.band }}</span> }</div>
                @if (i.score === null) { <p class="small">Not enough data for a Success Score (coverage {{ pct(i.coverage) }}, minimum {{ threshold() }}).
                  @if (i.indicative_score !== null && i.indicative_score !== undefined) { Indicative value from available data: <strong>{{ i.indicative_score }}</strong>. } </p> }
                <dl class="facts"><dt>Period</dt><dd>{{ i.period }}</dd><dt>Coverage</dt><dd>{{ pct(i.coverage) }}</dd>
                  <dt>Profile</dt><dd>{{ profileLabel(i.profile) }}</dd><dt>Scoring</dt><dd>v{{ i.scoring_version }}</dd>
                  <dt>Calculated</dt><dd>{{ when(i.calculated_at) }}</dd></dl>
              } @else { <p class="muted">Your role sees selected components only.</p> }
            } @else { <p class="muted">No calculated insight yet.</p> }
          </section>
          <section class="card"><h2>Risks</h2>
            <p>Academic <app-risk [level]="ins()?.risks?.academic?.level" /></p>
            <p>Placement <app-risk [level]="ins()?.risks?.placement?.level" /></p>
            <p class="small muted">Academic and placement risk are assessed separately. Thresholds are assumptions to validate with the college.</p>
            <button class="btn small" type="button" (click)="tab.set('risks')">See evidence</button>
          </section>
          <section class="card"><h2>About</h2>
            <dl class="facts"><dt>Mentor</dt><dd>{{ p.student.mentor_name || 'Not assigned' }}</dd>
              @if (p.student.email) { <dt>Email</dt><dd>{{ p.student.email }}</dd> }
              @if (p.student.date_of_birth) { <dt>Date of birth</dt><dd>{{ p.student.date_of_birth }}</dd> }
              <dt>Status</dt><dd>{{ p.student.status }}</dd></dl>
            @if (p.permissions['assign_mentor']) {
              <form class="row" style="margin-top:10px;gap:6px" (submit)="$event.preventDefault(); assignMentor()">
                <select [(ngModel)]="mentorSub" name="m" aria-label="Mentor"><option value="">No mentor</option>
                  @for (s of mentors(); track s.sub) { <option [value]="s.sub">{{ s.display_name }}</option> }</select>
                <button class="btn small" type="submit" [disabled]="busy()">Assign mentor</button></form>
            }
          </section>
        </div>
        @if (p.cohort && pairs().length) {
          <section class="card" style="margin-top:16px"><div class="card-head"><h2>Compared with classmates</h2>
            <span class="desc">Average of {{ p.cohort.students }} other students in {{ p.cohort.label }}. Averages only; no individual is shown.</span></div>
            <p class="insight">{{ cohortText() }}</p>
            <app-paired-bars [data]="pairs()" [nameA]="isOwn() ? 'You' : 'This student'" nameB="Class average" label="Component values compared with the class average" />
          </section>
        }
        @if (ins()?.summary) {
          <section class="card" style="margin-top:16px"><h2>Rules-based summary</h2><p>{{ ins()!.summary }}</p>
            <p class="small muted">Generated by transparent rules from recorded data. Not AI, and not a prediction.</p></section>
        }
        @if (segs().length) {
          <section class="card" style="margin-top:16px"><h2>Segments</h2>
            @for (s of segs(); track s.key) { <p><span class="chip teal">{{ s.label }}</span> <span class="small">{{ s.reasons.join('; ') }}</span></p> }</section>
        }
        @if (ins()?.support_needs?.length) {
          <section class="card" style="margin-top:16px"><h2>Support needs from feedback</h2>
            <ul>@for (n of ins()!.support_needs!; track n) { <li>{{ n }}</li> }</ul>
            <p class="small muted">Feedback gives context for support. It never lowers the Success Score.</p></section>
        }
      }

      @case ('score') {
        @if (ins()?.score_rows; as rows) {
          <section class="card"><div class="card-head"><h2>How the score is calculated</h2>
            <span class="desc">Each component is normalised to 0–100. Missing components are excluded and the remaining weights re-normalised; they are never counted as zero.</span></div>
            <div class="table-wrap"><table><thead><tr><th>Component</th><th class="num">Value</th><th class="num">Configured weight</th><th class="num">Applied weight</th><th class="num">Contribution</th><th>Status</th></tr></thead>
              <tbody>@for (r of rows; track r.component) {
                <tr><td>{{ r.label }}</td><td class="num">{{ r.value ?? '–' }}</td><td class="num">{{ pct(r.configured_weight) }}</td>
                  <td class="num">{{ r.applied_weight !== null ? pct(r.applied_weight) : '–' }}</td><td class="num">{{ r.contribution ?? '–' }}</td>
                  <td class="small">{{ rowStatus(r.status) }}</td></tr> }
                <tr><th>Final score</th><th class="num" colspan="4">{{ ins()!.score ?? 'Insufficient data' }}</th><th><app-status [status]="ins()!.status" /></th></tr>
              </tbody></table></div>
            <p class="small muted">Profile {{ profileLabel(ins()!.profile) }} · coverage {{ pct(ins()!.coverage) }} · scoring v{{ ins()!.scoring_version }} · calculated {{ when(ins()!.calculated_at) }}</p>
          </section>
        }
        @if (ins()?.components; as comps) {
          <section class="card" style="margin-top:16px"><div class="card-head"><h2>Indicators</h2><span class="desc">Raw values, their source period, and normalised points.</span></div>
            <div class="table-wrap"><table><thead><tr><th>Component</th><th>Indicator</th><th class="num">Recorded value</th><th>From period(s)</th><th class="num">Points (0–100)</th></tr></thead>
              <tbody>@for (c of compKeys(comps); track c) { @for (k of keys(comps[c].indicators); track k) {
                <tr><td>{{ compLabel(c) }}</td><td>{{ k }}</td><td class="num">{{ ins()?.indicators?.[k] ?? '–' }}</td>
                  <td class="small">{{ ins()?.sources?.[k] || '–' }}</td><td class="num">{{ comps[c].indicators[k] ?? 'missing' }}</td></tr> } }</tbody></table></div></section>
        }
        @if (p.history.length) {
          <section class="card" style="margin-top:16px"><div class="card-head"><h2>Trend</h2>
            <span class="desc">Periods are compared only when calculated under the same cohort profile. Gaps mean insufficient data.</span></div>
            <h3>Success Score</h3>
            <app-multiline [labels]="histLabels()" [series]="histSeries()" label="Success Score by reporting period" [ref]="60" refLabel="On track (60)" />
            <h3 style="margin-top:14px">Components</h3>
            <app-multiline [labels]="histLabels()" [series]="compSeries()" label="Component values by reporting period" seriesName="Component" />
            <div class="table-wrap"><table><thead><tr><th>Period</th><th class="num">Score</th><th>Status</th><th class="num">Coverage</th><th>Profile</th><th>Missing</th></tr></thead>
              <tbody>@for (h of p.history; track h.period) {
                <tr><td>{{ h.period }}</td><td class="num">{{ h.score ?? '–' }}@if (h.score === null && h.indicative_score !== null) { <span class="small muted"> (indicative {{ h.indicative_score }})</span> }</td>
                  <td><app-status [status]="h.status" /></td><td class="num">{{ pct(h.coverage) }}</td><td>{{ profileLabel(h.profile) }}</td>
                  <td class="small">{{ (h.missing || []).join(', ') || '–' }}</td></tr> }</tbody></table></div>
          </section>
        }
      }

      @case ('risks') {
        <div class="grid g2">
          @for (k of riskKinds; track k) {
            <section class="card">
              <div class="card-head"><h2>{{ k === 'academic' ? 'Academic risk' : 'Placement risk' }} <app-risk [level]="ins()?.risks?.[k]?.level" /></h2></div>
              @if (ins()?.risks?.[k]; as r) {
                <p class="small">{{ r.explanation }}</p>
                @if (r.flags?.length) {
                  <div class="table-wrap"><table><thead><tr><th>Rule</th><th>Evidence</th><th class="num">Observed</th><th class="num">Threshold</th><th>Period</th><th>Level</th></tr></thead>
                    <tbody>@for (f of r.flags; track f.rule) {
                      <tr><td class="mono">{{ f.rule }}</td><td>{{ f.label }}<br><span class="small muted">Suggested: {{ f.suggested_intervention.title }}</span></td>
                        <td class="num">{{ f.observed }}</td><td class="num">{{ f.operator }} {{ f.threshold }}</td><td>{{ f.observed_period }}</td><td><app-risk [level]="f.level" /></td></tr> }</tbody></table></div>
                }
                @if (r.missing?.length) { <p class="small">Missing: {{ r.missing!.join(', ') }}</p> }
                <p class="small muted">{{ r.assumption_notice }} Calculated {{ when(r.calculated_at) }} for {{ r.period }}.</p>
              } @else { <p class="muted">Not visible to your role.</p> }
            </section>
          }
        </div>
        @if (p.recommendations.length) {
          <section class="card" style="margin-top:16px"><div class="card-head"><h2>Recommended actions</h2>
            <span class="desc">Rules-based suggestions. Review the evidence; nothing is assigned until you confirm.</span></div>
            <div class="table-wrap"><table><thead><tr><th>Recommendation</th><th>Because</th><th>Usual owner</th><th></th></tr></thead>
              <tbody>@for (r of p.recommendations; track r.key) {
                <tr><td><strong>{{ r.title }}</strong><br><app-risk [level]="r.level" [prefix]="r.risk + ': '" /></td>
                  <td class="small">@for (e of r.evidence; track $index) { <div>{{ e.label }}@if (e.observed !== null) { — {{ e.observed }} ({{ e.operator }} {{ e.threshold }}, {{ e.period }})}</div> }</td>
                  <td>{{ r.owner_role }}</td>
                  <td>@if (p.permissions['create_intervention']) { <button class="btn small primary" type="button" (click)="startAssign(r)">Review and assign</button> }</td></tr> }
              </tbody></table></div></section>
        }
        @if (draft(); as d) {
          <section class="card" style="margin-top:16px" aria-labelledby="assign-h">
            <div class="card-head"><h2 id="assign-h">Assign intervention</h2><span class="spacer"></span>
              @if (session.me()?.ai) { <button class="btn small ai-draft" type="button" (click)="aiDraft()" [disabled]="drafting()">
                {{ drafting() ? 'Drafting…' : '✨ Draft with AI' }}</button> }</div>
            @if (aiNote()) { <p class="banner small" role="status">{{ aiNote() }}</p> }
            <form class="form-grid" (submit)="$event.preventDefault(); createIntervention()">
              <label class="field">Title<input name="t" [(ngModel)]="d.title" required maxlength="120"></label>
              <label class="field">Category<select name="c" [(ngModel)]="d.category">@for (c of ivCats(); track c[0]) { <option [value]="c[0]">{{ c[1] }}</option> }</select></label>
              <label class="field">Owner<select name="o" [(ngModel)]="d.owner_sub"><option value="">Me</option>
                @for (s of owners(d.category); track s.sub) { <option [value]="s.sub">{{ s.display_name }}</option> }</select></label>
              <label class="field">Due date<input name="dd" type="date" [(ngModel)]="d.due_date" required></label>
              <label class="field">Review date<input name="rd" type="date" [(ngModel)]="d.review_date" required></label>
              <label class="field" style="grid-column:1/-1">Details<textarea name="de" [(ngModel)]="d.detail" maxlength="1000" rows="5"></textarea></label>
              @if (d.evidence.length) { <div style="grid-column:1/-1" class="small"><strong>Evidence:</strong>
                @for (e of d.evidence; track $index) { <div>{{ e.rule }} · {{ e.label }}@if (e.observed !== null) { — observed {{ e.observed }}, threshold {{ e.operator }} {{ e.threshold }} ({{ e.period }}) }</div> }</div> }
              <label style="grid-column:1/-1" class="row"><input type="checkbox" name="rv" [(ngModel)]="d.reviewed" style="width:auto">
                I have reviewed this recommendation and its evidence, and I judge this intervention appropriate.</label>
              @if (formError()) { <p class="error-text" role="alert" style="grid-column:1/-1">{{ formError() }}</p> }
              <div class="row" style="grid-column:1/-1"><button class="btn primary" type="submit" [disabled]="busy() || !d.reviewed">Assign</button>
                <button class="btn" type="button" (click)="draft.set(null); aiNote.set(null)">Cancel</button></div>
            </form></section>
        }
        @if (p.permissions['create_intervention'] && !draft()) {
          <p style="margin-top:12px"><button class="btn small" type="button" (click)="startAssign(null)">Create an intervention without a recommendation</button></p>
        }
      }

      @case ('interventions') {
        @for (i of p.interventions; track i.intervention_id) {
          <section class="card" style="margin-bottom:14px">
            <div class="card-head"><h2>{{ i.title }}</h2>
              <span class="chip">{{ i.status }}</span> <span class="chip">{{ ivCat(i.category) }}</span>
              @if (i.overdue) { <span class="badge high">▲ Overdue {{ i.days_overdue }} day(s)</span> } @else if (i.review_due) { <span class="badge medium">■ Review due</span> }</div>
            <dl class="facts"><dt>Owner</dt><dd>{{ i.owner_name }}</dd><dt>Due</dt><dd>{{ i.due_date }}</dd><dt>Review</dt><dd>{{ i.review_date }}</dd>
              @if (i.detail) { <dt>Details</dt><dd>{{ i.detail }}</dd> }
              @if (i.outcome) { <dt>Outcome</dt><dd>{{ outcomeLabel(i.outcome.result) }}@if (i.outcome.note) { — {{ i.outcome.note }} } <span class="small muted">({{ when(i.outcome.recorded_at) }})</span></dd> }</dl>
            @if (i.comparison; as c) {
              <div class="banner" style="margin-top:10px"><strong>Before / after:</strong>
                {{ c.before.period || '–' }}: {{ c.before.score ?? '–' }} → {{ c.after.period || '–' }}: {{ c.after.score ?? '–' }}
                @if (c.comparable && c.change !== null) { ({{ c.change > 0 ? '+' : '' }}{{ c.change }}) }
                · academic {{ c.before.academic || '–' }} → {{ c.after.academic || '–' }}<br><span class="small">{{ c.note }}</span></div>
            }
            @if (p.permissions['update_intervention'] && i.status !== 'Completed' && canManage(i)) {
              <details style="margin-top:10px"><summary>Update</summary>
                <form class="form-grid" style="margin-top:8px" (submit)="$event.preventDefault(); updateIntervention(i)">
                  <label class="field">Status<select name="s" [(ngModel)]="upd(i).status"><option>Open</option><option>In Progress</option><option>Completed</option></select></label>
                  <label class="field">Due date<input type="date" name="d" [(ngModel)]="upd(i).due_date"></label>
                  <label class="field">Review date<input type="date" name="r" [(ngModel)]="upd(i).review_date"></label>
                  <label class="field">Outcome<select name="o" [(ngModel)]="upd(i).result"><option value="">Not recorded yet</option>
                    @for (o of outcomeKeys; track o) { <option [value]="o">{{ outcomeLabel(o) }}</option> }</select></label>
                  <label class="field" style="grid-column:1/-1">Outcome note<textarea name="n" [(ngModel)]="upd(i).note" maxlength="1000" rows="3"></textarea></label>
                  @if (session.me()?.ai) { <div class="row" style="grid-column:1/-1;gap:8px">
                    <button class="btn small" type="button" (click)="draftReview(i)" [disabled]="aiBusy()">{{ aiBusy() === 'review' + i.intervention_id ? 'Drafting…' : '✨ Draft review' }}</button>
                    @if (aiMsg()[i.intervention_id]) { <span class="small muted">{{ aiMsg()[i.intervention_id] }}</span> }</div> }
                  <p class="small muted" style="grid-column:1/-1">Completing requires an outcome. The current score is recorded for the before/after view.</p>
                  <div class="row" style="grid-column:1/-1"><button class="btn primary" type="submit" [disabled]="busy()">Save</button></div>
                </form></details>
            }
            @if (notesFor(i).length || p.permissions['staff_note']) {
              <h3 style="margin-top:14px">Notes</h3>
              @for (n of notesFor(i); track n.note_id) {
                <p class="small"><span class="chip" [class.teal]="n.visibility === 'staff'">{{ n.visibility === 'confidential' ? 'Confidential' : 'Staff' }}</span>
                  {{ n.text }} <span class="muted">— {{ n.author_name }}, {{ when(n.created_at) }}</span></p>
              }
              @if (p.permissions['staff_note']) {
                <form class="row" style="gap:6px;align-items:flex-start" (submit)="$event.preventDefault(); addNote(i)">
                  <textarea [(ngModel)]="noteText[i.intervention_id]" [name]="'n' + i.intervention_id" placeholder="Add a note" maxlength="2000" rows="2" style="flex:1" aria-label="Note"></textarea>
                  <select [(ngModel)]="noteVis[i.intervention_id]" [name]="'v' + i.intervention_id" aria-label="Visibility">
                    <option value="staff">Staff</option>@if (p.permissions['confidential_note']) { <option value="confidential">Confidential (mentor, HOD)</option> }</select>
                  @if (session.me()?.ai) { <button class="btn small" type="button" (click)="tidyNote(i)" [disabled]="!!aiBusy()"
                    title="Rewrites the note clearly. Names, IDs, emails and phone numbers are hidden from the AI.">{{ aiBusy() === 'tidy' + i.intervention_id ? 'Tidying…' : '✨ Tidy' }}</button> }
                  <button class="btn small" type="submit" [disabled]="busy()">Add</button></form>
              }
            }
          </section>
        } @empty { <p class="muted">No interventions.</p> }
      }

      @case ('records') {
        @for (c of recordCats(); track c) {
          <section class="card" style="margin-bottom:14px"><div class="card-head"><h2>{{ catLabel(c) }}</h2></div>
            <div class="table-wrap"><table><thead><tr><th>Period</th>@for (col of cols(c); track col) { <th>{{ col }}</th> }<th>Source</th><th>Updated</th>
              @if (c === 'certification' || c === 'engagement') { <th>Verification</th> }</tr></thead>
              <tbody>@for (r of byCat(c); track r.record_key) {
                <tr><td>{{ r.period }}</td>@for (col of cols(c); track col) { <td>{{ show(r[col]) }}</td> }<td class="small">{{ r.source || 'manual' }}</td>
                  <td class="small">{{ when(r.updated_at) }}</td>
                  @if (c === 'certification' || c === 'engagement') {
                    <td>{{ r.verification }}@if (r.verification === 'pending' && p.permissions['verify']) {
                      <button class="btn small" type="button" (click)="verify(r, 'verified')">Verify</button> <button class="btn small" type="button" (click)="verify(r, 'rejected')">Reject</button> }</td>
                  }</tr> }</tbody></table></div></section>
        } @empty { <app-state [loading]="recLoading()" [empty]="!recLoading()" emptyText="No records visible to your role." /> }
        @if (p.corrections.length) {
          <section class="card"><h2>Correction requests</h2>
            <div class="table-wrap"><table><thead><tr><th>Category</th><th>Period</th><th>Current</th><th>Proposed</th><th>Requested by</th><th>Status</th></tr></thead>
              <tbody>@for (c of p.corrections; track c.correction_id) {
                <tr><td>{{ catLabel(c.category) }}</td><td>{{ c.period }}</td><td class="small mono">{{ json(c.current) }}</td><td class="small mono">{{ json(c.proposed) }}</td>
                  <td>{{ c.requested_by_name }}</td><td>{{ c.status }}</td></tr> }</tbody></table></div></section>
        }
      }
      }
      @if (notice()) { <p class="banner" role="status" style="margin-top:14px">{{ notice() }}</p> }
    }`,
})
export class ProfilePage {
  aiTools = computed<AiTool[]>(() => this.isOwn()
    ? [{ kind: 'student', label: 'Summary', action: 'Summarise my progress' }, { kind: 'explain', label: 'Explain my score', action: 'Explain my score' }]
    : [{ kind: 'student', label: 'Summary', action: 'Summarise this student' },
       { kind: 'brief', label: 'Meeting brief', action: 'Prepare meeting brief', printable: true },
       { kind: 'explain', label: 'Explain the score change', action: 'Explain the change' }]);
  private api = inject(Api);
  session = inject(Session);
  dataset = input.required<string>();
  sid = input.required<string>();
  pct = pct; when = when;
  riskKinds = ['academic', 'placement'] as const;
  outcomeKeys = Object.keys(OUTCOMES);
  p = signal<Profile | null>(null);
  records = signal<Rec[]>([]);
  recLoading = signal(false);
  staff = signal<Staff[]>([]);
  loading = signal(true);
  busy = signal(false);
  error = signal<string | null>(null);
  formError = signal<string | null>(null);
  notice = signal<string | null>(null);
  tab = signal('summary');
  draft = signal<{ title: string; category: string; owner_sub: string; due_date: string; review_date: string; detail: string;
    reviewed: boolean; evidence: Recommendation['evidence']; recommendation_key: string | null } | null>(null);
  updates: Record<string, { status: string; due_date: string; review_date: string; result: string; note: string }> = {};
  noteText: Record<string, string> = {};
  noteVis: Record<string, string> = {};
  mentorSub = '';
  threshold = signal('80%');

  ins = computed(() => this.p()?.insight || null);
  isOwn = computed(() => { const s = this.session.me()?.user.student; return !!s && s.student_id === this.sid(); });
  tabs = computed(() => {
    const t: [string, string][] = [['summary', 'Summary']];
    if (this.ins()?.score_rows || this.p()?.history.length) t.push(['score', 'Score & trends']);
    if (this.ins()?.risks) t.push(['risks', this.p()?.recommendations.length ? 'Risks & actions' : 'Risks']);
    if (this.p()?.interventions.length || this.p()?.permissions['create_intervention']) t.push(['interventions', `Interventions (${this.p()?.interventions.length || 0})`]);
    t.push(['records', 'Records']);
    return t;
  });
  segs = computed(() => {
    const s = this.ins()?.segments || [];
    return (s as unknown[]).map((x) => typeof x === 'string' ? { key: x, label: SEGMENTS[x] || x, reasons: [] as string[] } : x as { key: string; label: string; reasons: string[] });
  });
  histLabels = computed(() => (this.p()?.history || []).map((h) => h.period));
  histSeries = computed<Line[]>(() => [{ name: 'Success Score', color: SERIES[0], values: (this.p()?.history || []).map((h) => h.score) }]);
  compSeries = computed<Line[]>(() => {
    // fixed order: each component keeps its colour on every profile
    const colors: Record<string, string> = { academic: SERIES[0], attendance: SERIES[1], lms: SERIES[2], placement: SERIES[3], skills: SERIES[4], engagement: SERIES[5] };
    const hist = this.p()?.history || [];
    return Object.keys(COMPONENTS).map((k) => ({ name: COMPONENTS[k], color: colors[k],
      values: hist.map((h) => h.rows?.find((r) => r.component === k)?.value ?? null) })).filter((s) => s.values.some((v) => v !== null));
  });
  pairs = computed<Pair[]>(() => {
    const c = this.p()?.cohort; const comps = this.ins()?.components; if (!c || !comps) return [];
    return Object.keys(COMPONENTS).filter((k) => k in comps || c.components[k] != null)
      .map((k) => ({ label: COMPONENTS[k], a: comps[k]?.value ?? null, b: c.components[k] ?? null }));
  });
  cohortText = computed(() => {
    const d = this.pairs().filter((x) => x.a !== null && x.b !== null).map((x) => ({ l: x.label, d: x.a! - x.b! })).sort((x, y) => y.d - x.d);
    if (!d.length) return '';
    const best = d[0], worst = d[d.length - 1];
    const s = (x: { l: string; d: number }) => `${x.l} (${x.d > 0 ? '+' : ''}${x.d.toFixed(0)})`;
    if (d.length === 1) return `${s(best)} versus the class average.`;
    if (worst.d >= 0) return `At or above the class average on every component; furthest ahead: ${s(best)}.`;
    if (best.d < 0) return `Below the class average on every component; closest: ${s(best)}, furthest behind: ${s(worst)}.`;
    return `Furthest ahead of the class: ${s(best)}. Furthest behind: ${s(worst)}.`;
  });
  mentors = computed(() => this.staff().filter((s) => s.roles.includes('mentor')));
  recordCats = computed(() => Object.keys(RECORD_COLS).filter((c) => this.records().some((r) => r.category === c)));

  constructor() {
    effect(() => { this.dataset(); this.sid(); untracked(() => this.load()); });
    effect(() => { if (this.tab() === 'records') untracked(() => this.loadRecords()); });
  }

  async load() {
    this.loading.set(true); this.error.set(null);
    try {
      const p = await this.api.get<Profile>(`/students/${this.dataset()}/${this.sid()}`);
      this.p.set(p);
      this.mentorSub = p.student.mentor_sub || '';
      for (const i of p.interventions) this.noteVis[i.intervention_id] ||= 'staff';
      if (!this.tabs().some((t) => t[0] === this.tab())) this.tab.set('summary');
      if (!this.session.isStudent() && !this.staff().length && !this.session.isSysAdmin()) {
        this.api.get<{ items: Staff[] }>('/staff').then((r) => this.staff.set(r.items)).catch(() => undefined);
      }
      if (this.tab() === 'records') this.loadRecords();
    } catch (e) { this.error.set(message(e)); }
    finally { this.loading.set(false); }
  }

  async loadRecords() {
    this.recLoading.set(true);
    try { this.records.set((await this.api.get<{ items: Rec[] }>(`/students/${this.dataset()}/${this.sid()}/records`)).items); }
    catch (e) { this.notice.set(message(e)); }
    finally { this.recLoading.set(false); }
  }

  // --- helpers
  keys(o: object) { return Object.keys(o || {}); }
  compKeys(o: object) { return Object.keys(COMPONENTS).filter((k) => k in (o || {})); }
  compLabel(k: string) { return COMPONENTS[k] || k; }
  profileLabel(p?: string) { return p === 'placement_years' ? 'Years 3–4 (with placement)' : p === 'early_years' ? 'Years 1–2' : p || '–'; }
  rowStatus(s: string) { return ({ included: 'Included', missing: 'Missing — excluded, weights re-normalised', not_applicable: 'Not applicable to this year' } as Record<string, string>)[s] || s; }
  ivCat(c: string) { return IV_CATEGORIES[c] || c; }
  outcomeLabel(o: string) { return OUTCOMES[o] || o; }
  catLabel(c: string) { return ({ academic_result: 'Academic results', marks: 'Subject marks', attendance: 'Attendance', lms: 'LMS activity',
    engagement: 'Events, clubs and projects', certification: 'Certifications', placement_assessment: 'Placement assessments', skills: 'Skills',
    feedback: 'Feedback' } as Record<string, string>)[c] || c; }
  cols(c: string) { return RECORD_COLS[c] || []; }
  byCat(c: string) { return this.records().filter((r) => r.category === c).sort((a, b) => b.period.localeCompare(a.period)); }
  show(v: unknown) { return v === undefined || v === null || v === '' ? '–' : Array.isArray(v) ? v.join(', ') : String(v); }
  json(o: unknown) { return JSON.stringify(o); }
  notesFor(i: Intervention) { return (this.p()?.notes || []).filter((n) => n.intervention_id === i.intervention_id); }
  ivCats() {
    const pl = this.session.roles().has('placement_officer') && !['mentor', 'hod', 'college_admin'].some((r) => this.session.roles().has(r));
    return Object.entries(IV_CATEGORIES).filter(([k]) => !pl || k === 'placement_training');
  }
  owners(category: string) {
    return this.staff().filter((s) => category === 'placement_training' ? s.roles.includes('placement_officer') || s.roles.includes('mentor')
      : s.roles.some((r) => ['mentor', 'hod', 'college_admin'].includes(r)));
  }
  canManage(i: Intervention) {
    const pl = this.session.roles().has('placement_officer') && this.session.roles().size === 1;
    return !pl || i.category === 'placement_training';
  }
  upd(i: Intervention) {
    return this.updates[i.intervention_id] ||= { status: i.status, due_date: i.due_date, review_date: i.review_date, result: i.outcome?.result || '', note: i.outcome?.note || '' };
  }

  // --- actions
  startAssign(r: Recommendation | null) {
    const d = new Date();
    const iso = (n: number) => new Date(d.getTime() + n * 864e5).toISOString().slice(0, 10);
    this.formError.set(null);
    this.draft.set({ title: r?.title || '', category: r?.category || (this.ivCats()[0]?.[0] ?? 'academic'), owner_sub: '', due_date: iso(28), review_date: iso(42),
      detail: '', reviewed: false, evidence: r?.evidence || [], recommendation_key: r?.key || null });
  }

  drafting = signal(false);
  aiNote = signal<string | null>(null);

  /** AI drafts the title and steps from this student's evidence; staff edit everything before assigning. */
  async aiDraft() {
    const d = this.draft();
    if (!d) return;
    this.drafting.set(true); this.aiNote.set(null); this.formError.set(null);
    try {
      const r = await this.api.post<{ title: string; steps: string[]; review_weeks: number; model: string }>('/ai/plan-draft', {
        student_id: this.sid(), category: d.category, recommendation: d.title || null, evidence: d.evidence });
      const iso = (days: number) => { const t = new Date(); t.setDate(t.getDate() + days); return t.toISOString().slice(0, 10); };
      this.draft.set({ ...d, title: r.title.slice(0, 120), detail: r.steps.map((s) => '- ' + s).join('\n').slice(0, 1000),
        due_date: iso(Math.max(7, r.review_weeks * 7 - 7)), review_date: iso(r.review_weeks * 7), reviewed: false });
      this.aiNote.set(`Drafted by AI (${r.model}). Check and edit every field, then confirm the review box before assigning.`);
    } catch (e) { this.formError.set(message(e)); }
    finally { this.drafting.set(false); }
  }

  async createIntervention() {
    const d = this.draft();
    if (!d) return;
    this.busy.set(true); this.formError.set(null);
    try {
      await this.api.post(`/students/${this.dataset()}/${this.sid()}/interventions`, { ...d, owner_sub: d.owner_sub || undefined });
      this.draft.set(null);
      this.aiNote.set(null);
      this.notice.set('Intervention assigned.');
      await this.load();
      this.tab.set('interventions');
    } catch (e) { this.formError.set(message(e)); }
    finally { this.busy.set(false); }
  }

  async updateIntervention(i: Intervention) {
    const u = this.upd(i);
    const body: Record<string, unknown> = { version: i.version };
    if (u.status !== i.status) body['status'] = u.status;
    if (u.due_date !== i.due_date) body['due_date'] = u.due_date;
    if (u.review_date !== i.review_date) body['review_date'] = u.review_date;
    if (u.result && (u.result !== i.outcome?.result || u.note !== (i.outcome?.note || ''))) body['outcome'] = { result: u.result, note: u.note };
    await this.act(async () => {
      await this.api.patch(`/students/${this.dataset()}/${this.sid()}/interventions/${i.intervention_id}`, body);
      delete this.updates[i.intervention_id];
      return 'Intervention updated.';
    });
  }

  aiBusy = signal<string | null>(null);
  aiMsg = signal<Record<string, string>>({});
  private setMsg(id: string, m: string) { this.aiMsg.update((x) => ({ ...x, [id]: m })); }

  /** AI suggests the outcome from the before/after figures; the mentor edits it and saves. */
  async draftReview(i: Intervention) {
    this.aiBusy.set('review' + i.intervention_id); this.setMsg(i.intervention_id, '');
    try {
      const r = await this.api.post<{ result: string; recommendation: string; note: string; model: string }>('/ai/tool',
        { tool: 'plan_review', student_id: this.sid(), intervention_id: i.intervention_id });
      const u = this.upd(i);
      u.result = r.result; u.note = r.note.slice(0, 1000);
      if (r.recommendation === 'close') u.status = 'Completed'; else if (u.status === 'Open') u.status = 'In Progress';
      this.setMsg(i.intervention_id, `Suggested: ${r.recommendation} the plan (AI, ${r.model}). Check before saving.`);
    } catch (e) { this.setMsg(i.intervention_id, message(e)); }
    finally { this.aiBusy.set(null); }
  }

  /** AI rewrites the note clearly; identities are masked before it leaves the platform. */
  async tidyNote(i: Intervention) {
    const text = (this.noteText[i.intervention_id] || '').trim();
    if (!text) return;
    this.aiBusy.set('tidy' + i.intervention_id);
    try {
      const r = await this.api.post<{ text: string }>('/ai/tool', { tool: 'tidy', student_id: this.sid(), text });
      if (r.text) this.noteText[i.intervention_id] = r.text;
    } catch (e) { this.setMsg(i.intervention_id, message(e)); }
    finally { this.aiBusy.set(null); }
  }

  async addNote(i: Intervention) {
    const text = (this.noteText[i.intervention_id] || '').trim();
    if (!text) return;
    await this.act(async () => {
      await this.api.post(`/students/${this.dataset()}/${this.sid()}/interventions/${i.intervention_id}/notes`,
        { text, visibility: this.noteVis[i.intervention_id] || 'staff' });
      this.noteText[i.intervention_id] = '';
      return 'Note added.';
    });
  }

  async assignMentor() {
    const p = this.p();
    if (!p) return;
    await this.act(async () => {
      await this.api.put(`/students/${this.dataset()}/${this.sid()}/mentor`, { mentor_sub: this.mentorSub || null, version: p.student.version });
      return 'Mentor updated.';
    });
  }

  async verify(r: Rec, decision: string) {
    await this.act(async () => {
      await this.api.post(`/students/${this.dataset()}/${this.sid()}/verify`, { category: r.category, record_key: r.record_key, decision, version: r.version });
      await this.loadRecords();
      return decision === 'verified' ? 'Verified.' : 'Rejected.';
    });
  }

  private async act(fn: () => Promise<string>) {
    this.busy.set(true); this.notice.set(null);
    try {
      const msg = await fn();
      await this.load();
      this.notice.set(msg);
    } catch (e) {
      this.notice.set(e instanceof ApiError && e.status === 409 ? `${e.message} The latest version has been loaded.` : message(e));
      if (e instanceof ApiError && e.status === 409) await this.load();
    } finally { this.busy.set(false); }
  }
}
