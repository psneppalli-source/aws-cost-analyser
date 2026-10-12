import { HttpRequest } from '@angular/common/http';
import { describe, expect, it } from 'vitest';
import { prepare, sha256Hex } from './auth.interceptor';

describe('prepare (CloudFront OAC payload hash + app token)', () => {
  it('hashes the exact JSON bytes sent and keeps Authorization free for SigV4', async () => {
    const req = new HttpRequest('PUT', '/api/students/real/CSE24001/records/lms/2026-09', { data: { logins: 4 }, version: 2 });
    const out = await prepare(req, 'tok');
    const body = out.body as string;
    expect(body).toBe('{"data":{"logins":4},"version":2}');
    expect(out.headers.get('x-amz-content-sha256')).toBe(await sha256Hex(body));
    expect(out.headers.get('X-App-Authorization')).toBe('Bearer tok');
    expect(out.headers.has('Authorization')).toBe(false);
  });

  it('hashes an empty body for POST without one', async () => {
    const out = await prepare(new HttpRequest('POST', '/api/imports/x/commit', null), null);
    expect(out.headers.get('x-amz-content-sha256')).toBe('e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855');
    expect(out.headers.has('X-App-Authorization')).toBe(false);
  });

  it('hashes binary uploads byte-for-byte and adds no hash to GET', async () => {
    const buf = new TextEncoder().encode('student_id,period\n').buffer as ArrayBuffer;
    const out = await prepare(new HttpRequest('POST', '/api/imports/preview', buf), 't');
    expect(out.headers.get('x-amz-content-sha256')).toBe(await sha256Hex(buf));
    const get = await prepare(new HttpRequest('GET', '/api/me'), 't');
    expect(get.headers.has('x-amz-content-sha256')).toBe(false);
  });
});
