import { Injectable, computed, inject, signal } from '@angular/core';
import { Api } from './api.service';

export interface Me {
  user: { sub: string; username: string; display_name: string; roles: string[]; role_labels: string[]; departments: string[];
    subjects: { department: string; year: number; subject: string }[]; student: { dataset: string; student_id: string } | null; };
  permissions: string[];
  periods: string[];
  current_period: string;
  departments: Record<string, { name: string; subjects: Record<string, string[]> }>;
  scoring_version: string | null;
  datasets: string[];
}

/** Signed-in user, their permissions, and the dataset/period being viewed. */
@Injectable({ providedIn: 'root' })
export class Session {
  private api = inject(Api);
  readonly me = signal<Me | null>(null);
  /** Real records by default; demo data is shown only when chosen (never mixed into real aggregates). */
  readonly dataset = signal<'real' | 'demo'>((sessionStorage.getItem('ssp.dataset') as 'real' | 'demo') || 'real');
  readonly roles = computed(() => new Set(this.me()?.user.roles || []));
  readonly isStudent = computed(() => this.roles().has('student') && this.roles().size === 1);
  readonly isSysAdmin = computed(() => this.roles().has('system_admin'));

  async load(): Promise<Me> {
    const me = await this.api.get<Me>('/me');
    this.me.set(me);
    if (me.user.student) this.setDataset(me.user.student.dataset as 'real' | 'demo');
    return me;
  }

  can(resource: string, action: string): boolean {
    return (this.me()?.permissions || []).includes(`${resource}:${action}`);
  }

  setDataset(d: 'real' | 'demo'): void {
    this.dataset.set(d);
    try { sessionStorage.setItem('ssp.dataset', d); } catch { /* ignore */ }
  }

  clear(): void {
    this.me.set(null);
  }
}
