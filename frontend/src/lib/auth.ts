/**
 * Auth helpers — token storage/validation only. The actual login UI lives
 * in pages/LoginPage.tsx, which calls login() below with real credentials
 * a person typed in. There is no hardcoded username/password anywhere in
 * this file (or anywhere in the frontend).
 */

import { API_BASE, getToken, setToken, clearToken } from "./api";

export class LoginError extends Error {}

export async function login(username: string, password: string): Promise<void> {
  const form = new URLSearchParams();
  form.set("username", username);
  form.set("password", password);

  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form.toString(),
  });

  if (!res.ok) {
    if (res.status === 401) {
      throw new LoginError("Incorrect email or password.");
    }
    throw new LoginError(`Couldn't reach the MosAIc API at ${API_BASE}.`);
  }

  const data = await res.json();
  setToken(data.access_token);
}

export function logout(): void {
  clearToken();
}

async function isTokenValid(token: string): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    return res.ok;
  } catch {
    return false;
  }
}

/**
 * Returns true if there's a currently-valid cached token, false otherwise.
 * Never attempts to log in automatically — that now requires a person to
 * submit the login form.
 */
export async function hasValidSession(): Promise<boolean> {
  const cached = getToken();
  if (!cached) return false;

  // A cached token can go stale if the API restarted with a different
  // SECRET_KEY (e.g. .env wasn't loaded before, now it is) — verify it
  // actually still works rather than trusting its mere presence.
  if (await isTokenValid(cached)) return true;

  clearToken();
  return false;
}
