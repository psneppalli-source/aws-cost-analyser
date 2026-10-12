import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';

export interface ApiErrorBody { code: string; message: string; details?: Record<string, unknown> | null; }

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: Record<string, unknown> | null = null) {
    super(message);
  }
  /** Field-level validation messages, e.g. {score: "must be between 0 and 500"}. */
  get fields(): Record<string, string> {
    const d = this.details || {};
    return Object.fromEntries(Object.entries(d).filter(([, v]) => typeof v === 'string')) as Record<string, string>;
  }
}

type Params = Record<string, string | number | boolean | null | undefined>;

/** Thin typed wrapper over the API. All calls return promises and throw ApiError. */
@Injectable({ providedIn: 'root' })
export class Api {
  private http = inject(HttpClient);

  private params(p?: Params): HttpParams {
    let hp = new HttpParams();
    Object.entries(p || {}).forEach(([k, v]) => {
      if (v !== null && v !== undefined && v !== '') hp = hp.set(k, String(v));
    });
    return hp;
  }

  private async run<T>(o: Promise<T>): Promise<T> {
    try {
      return await o;
    } catch (e) {
      if (e instanceof HttpErrorResponse) {
        const b = (e.error && e.error.error) as ApiErrorBody | undefined;
        const msg = b?.message || (e.status === 0 ? 'The server could not be reached.' : `Request failed (${e.status})`);
        throw new ApiError(e.status, b?.code || 'error', msg, (b?.details as Record<string, unknown>) || null);
      }
      throw e;
    }
  }

  get<T>(path: string, params?: Params): Promise<T> {
    return this.run(firstValueFrom(this.http.get<T>(`/api${path}`, { params: this.params(params) })));
  }
  post<T>(path: string, body: unknown = {}, params?: Params): Promise<T> {
    return this.run(firstValueFrom(this.http.post<T>(`/api${path}`, body, { params: this.params(params) })));
  }
  put<T>(path: string, body: unknown): Promise<T> {
    return this.run(firstValueFrom(this.http.put<T>(`/api${path}`, body)));
  }
  patch<T>(path: string, body: unknown): Promise<T> {
    return this.run(firstValueFrom(this.http.patch<T>(`/api${path}`, body)));
  }
  text(path: string): Promise<string> {
    return this.run(firstValueFrom(this.http.get(`/api${path}`, { responseType: 'text' })));
  }
  upload<T>(path: string, data: ArrayBuffer, params?: Params): Promise<T> {
    return this.run(firstValueFrom(this.http.post<T>(`/api${path}`, data, {
      params: this.params(params), headers: { 'Content-Type': 'application/octet-stream' } })));
  }
}
