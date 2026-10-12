import { HttpErrorResponse, HttpInterceptorFn, HttpRequest } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, from, switchMap, throwError } from 'rxjs';
import { AuthService } from './auth.service';

/** Hex SHA-256 of the exact bytes sent. CloudFront OAC needs it for IAM-protected Function URL writes. */
export async function sha256Hex(data: string | ArrayBuffer): Promise<string> {
  const bytes: Uint8Array<ArrayBuffer> = typeof data === 'string' ? new TextEncoder().encode(data) : new Uint8Array(data);
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, '0')).join('');
}

/** Realm-safe check (an ArrayBuffer from another frame or test environment fails instanceof). */
function isBuffer(v: unknown): v is ArrayBuffer {
  return v instanceof ArrayBuffer || Object.prototype.toString.call(v) === '[object ArrayBuffer]';
}

/** Serialise the body ourselves so the hash matches byte-for-byte what goes on the wire. */
export async function prepare(req: HttpRequest<unknown>, token: string | null): Promise<HttpRequest<unknown>> {
  const headers: Record<string, string> = {};
  if (token) headers['X-App-Authorization'] = `Bearer ${token}`; // Authorization is reserved for CloudFront's SigV4
  if (['POST', 'PUT', 'PATCH'].includes(req.method)) {
    let body: string | ArrayBuffer;
    if (isBuffer(req.body)) {
      body = req.body;
    } else if (req.body === null || req.body === undefined) {
      body = '';
    } else if (typeof req.body === 'string') {
      body = req.body;
    } else {
      body = JSON.stringify(req.body);
      headers['Content-Type'] = 'application/json';
    }
    headers['x-amz-content-sha256'] = await sha256Hex(body);
    return req.clone({ setHeaders: headers, body });
  }
  return req.clone({ setHeaders: headers });
}

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  if (!req.url.startsWith('/api/')) return next(req);
  const auth = inject(AuthService);
  const router = inject(Router);
  return from(auth.token().then((t) => prepare(req, t))).pipe(
    switchMap((r) => next(r)),
    catchError((e: HttpErrorResponse) => {
      if (e.status === 401 && !req.url.includes('/auth/')) {
        auth.clear();
        router.navigateByUrl('/login');
      }
      return throwError(() => e);
    }),
  );
};
