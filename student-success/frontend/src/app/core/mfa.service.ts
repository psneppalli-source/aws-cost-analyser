import { Injectable, inject } from '@angular/core';
import { AuthService } from './auth.service';

/**
 * Authenticator-app (TOTP) setup against Cognito, called from the browser with the user's own access token
 * (scope aws.cognito.signin.user.admin). The secret goes straight from Cognito to the browser; the API only
 * learns whether MFA is enabled. After setup, the college sign-in page asks for the 6-digit code.
 */
@Injectable({ providedIn: 'root' })
export class MfaService {
  private auth = inject(AuthService);

  private async call<T>(target: string, body: Record<string, unknown>): Promise<T> {
    const region = this.auth.config()?.region || 'eu-west-2';
    const r = await fetch(`https://cognito-idp.${region}.amazonaws.com/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-amz-json-1.1', 'X-Amz-Target': `AWSCognitoIdentityProviderService.${target}` },
      body: JSON.stringify(body),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) {
      const msg = (j as { message?: string }).message || '';
      const type = (j as { __type?: string }).__type || '';
      if (/CodeMismatch|EnableSoftwareTokenMFA/.test(type)) throw new Error('That code is not correct. Check the time on your phone and try the newest code.');
      if (/scope|not authorized|access token/i.test(msg)) throw new Error('Please sign out and sign in again, then retry.');
      throw new Error(msg || 'The authenticator could not be set up. Please try again.');
    }
    return j as T;
  }

  /** Start setup: returns the secret and an otpauth:// link for the QR code. */
  async begin(account: string): Promise<{ secret: string; uri: string }> {
    const token = await this.auth.accessToken();
    if (!token) throw new Error('Please sign out and sign in again, then retry.');
    const r = await this.call<{ SecretCode: string }>('AssociateSoftwareToken', { AccessToken: token });
    const issuer = 'Smart Campus';
    const uri = `otpauth://totp/${encodeURIComponent(issuer)}:${encodeURIComponent(account)}?secret=${r.SecretCode}&issuer=${encodeURIComponent(issuer)}`;
    return { secret: r.SecretCode, uri };
  }

  /** Confirm with a code from the app and make the authenticator the sign-in method. */
  async confirm(code: string): Promise<void> {
    const token = await this.auth.accessToken();
    if (!token) throw new Error('Please sign out and sign in again, then retry.');
    const v = await this.call<{ Status: string }>('VerifySoftwareToken', { AccessToken: token, UserCode: code.trim(), FriendlyDeviceName: 'Authenticator app' });
    if (v.Status !== 'SUCCESS') throw new Error('That code is not correct. Try the newest code.');
    await this.call('SetUserMFAPreference', { AccessToken: token, SoftwareTokenMfaSettings: { Enabled: true, PreferredMfa: true } });
  }
}
