import { Injectable, computed, inject, signal } from '@angular/core';
import { Api } from './api.service';

export interface Me {
  user: { sub: string; username: string; display_name: string; roles: string[]; role_labels: string[]; departments: string[];
    subjects: { department: string; year: number; subject: string }[]; student: { dataset: string; student_id: string } | null;
    mfa: { enabled: boolean | null; required: boolean }; };
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
  /** All records live in one dataset; the key stays in API paths so another dataset could be added later. */
  readonly dataset = signal<'real'>('real');
  readonly roles = computed(() => new Set(this.me()?.user.roles || []));
  readonly isStudent = computed(() => this.roles().has('student') && this.roles().size === 1);
  readonly isSysAdmin = computed(() => this.roles().has('system_admin'));
  /** Students must set up an authenticator app before seeing any data (enforced by the API too). */
  readonly mfaPending = computed(() => !!this.me()?.user.mfa?.required && !this.me()?.user.mfa?.enabled);

  async load(): Promise<Me> {
    const me = await this.api.get<Me>('/me');
    this.me.set(me);
    return me;
  }

  can(resource: string, action: string): boolean {
    return (this.me()?.permissions || []).includes(`${resource}:${action}`);
  }

  clear(): void {
    this.me.set(null);
  }
}
