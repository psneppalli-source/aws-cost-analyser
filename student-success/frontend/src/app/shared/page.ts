import { Component, inject, input, output } from '@angular/core';
import { ApiError } from '../core/api.service';
import { Session } from '../core/session.service';
import { Filters } from './ui';

export function blankFilters(over: Partial<Filters> = {}): Filters {
  return { department: '', year: '', period: '', risk: '', segment: '', q: '', ...over };
}

export function message(e: unknown): string {
  if (e instanceof ApiError) {
    const f = Object.entries(e.fields).map(([k, v]) => `${k}: ${v}`).join('; ');
    return f ? `${e.message} ${f}` : e.message;
  }
  return (e as Error)?.message || 'Something went wrong.';
}

/** Shown when the real dataset has no records yet, so a new deployment doesn't look broken. */
@Component({
  selector: 'app-real-empty',
  template: `
    @if (show()) {
      <div class="banner" style="margin-bottom:14px">
        No student records yet. Add students and data with <strong>Enter data</strong> or <strong>Import</strong>.
      </div>
    }`,
})
export class RealEmpty {
  show = input(false);
}
