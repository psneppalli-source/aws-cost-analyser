/* Sign-in for both deployment modes.
 * cognito: OAuth 2.0 authorization code + PKCE against the Cognito hosted login
 *          (password + optional TOTP MFA live there; the app never sees passwords).
 * local:   username/password to /api/auth/login (development and offline demos).
 * Tokens live in sessionStorage only, so closing the tab signs out. */
(function () {
  const C = window.SSP_CONFIG || { mode: "local" };
  const KEY = "ssp.session";

  function b64url(bytes) {
    return btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  function rand(n) { const a = new Uint8Array(n); crypto.getRandomValues(a); return b64url(a); }
  async function sha256(s) { return b64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s))); }
  function claims(jwt) {
    try { return JSON.parse(atob(jwt.split(".")[1].replace(/-/g, "+").replace(/_/g, "/"))); } catch (e) { return {}; }
  }
  function load() { try { return JSON.parse(sessionStorage.getItem(KEY) || "null"); } catch (e) { return null; } }
  function save(s) { try { sessionStorage.setItem(KEY, JSON.stringify(s)); } catch (e) { /* private mode */ } }
  function clear() { try { sessionStorage.removeItem(KEY); sessionStorage.removeItem("ssp.pkce"); } catch (e) { /* ignore */ } }

  async function tokenRequest(params) {
    const r = await fetch(C.domain + "/oauth2/token", {
      method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ client_id: C.clientId, ...params }).toString(),
    });
    if (!r.ok) throw new Error("Sign-in failed. Please try again.");
    return r.json();
  }

  const Auth = {
    mode: C.mode,
    async startCognito() {
      const verifier = rand(48), state = rand(16);
      sessionStorage.setItem("ssp.pkce", JSON.stringify({ verifier, state }));
      const q = new URLSearchParams({
        response_type: "code", client_id: C.clientId, redirect_uri: C.redirectUri, scope: "openid profile email",
        state, code_challenge: await sha256(verifier), code_challenge_method: "S256",
      });
      location.assign(C.domain + "/oauth2/authorize?" + q.toString());
    },
    /* Called on page load: completes a Cognito redirect if one is in progress. */
    async init() {
      if (C.mode !== "cognito") return;
      const u = new URL(location.href);
      const code = u.searchParams.get("code");
      if (!code) return;
      const p = JSON.parse(sessionStorage.getItem("ssp.pkce") || "{}");
      history.replaceState(null, "", u.pathname + (u.hash || ""));
      if (!p.verifier || u.searchParams.get("state") !== p.state) throw new Error("Sign-in expired. Please sign in again.");
      const t = await tokenRequest({ grant_type: "authorization_code", code, redirect_uri: C.redirectUri, code_verifier: p.verifier });
      sessionStorage.removeItem("ssp.pkce");
      save({ id: t.id_token, refresh: t.refresh_token, exp: claims(t.id_token).exp });
    },
    async localLogin(username, password) {
      const r = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }) });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || "Sign-in failed");
      save({ id: j.token, exp: claims(j.token).exp });
    },
    async token() {
      const s = load();
      if (!s) return null;
      const now = Date.now() / 1000;
      if (s.exp - now > 60) return s.id;
      if (C.mode === "cognito" && s.refresh) {
        try {
          const t = await tokenRequest({ grant_type: "refresh_token", refresh_token: s.refresh });
          save({ id: t.id_token, refresh: s.refresh, exp: claims(t.id_token).exp });
          return t.id_token;
        } catch (e) { clear(); return null; }
      }
      clear();
      return null;
    },
    signedIn() { const s = load(); return !!s && s.exp > Date.now() / 1000; },
    signOut() {
      clear();
      if (C.mode === "cognito") {
        location.assign(C.domain + "/logout?" + new URLSearchParams({ client_id: C.clientId, logout_uri: C.redirectUri }).toString());
      } else {
        location.hash = "";
        location.reload();
      }
    },
  };
  window.Auth = Auth;
})();
