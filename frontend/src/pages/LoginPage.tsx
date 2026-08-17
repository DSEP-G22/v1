import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, api, clearToken, setToken } from "../api/client";
import type { CurrentUser } from "../api/types";

// UI-1. v1 authenticates with the static per-role bearer tokens described in
// libs/platform/auth.py, there is no password store yet, so the form takes the token as the
// credential. The error message is deliberately identical for "no such user" and "wrong token".
//
// The role buttons below sign in with those same tokens in one click. They are not a second auth
// path: they call exactly the same endpoint with the same credential, they only remove the
// opportunity to mistype it or to paste in trailing whitespace.

const DEV_ROLES = [
  { token: "dev-agent-token", label: "Agent", blurb: "Queue and ticket workspace" },
  { token: "dev-lead-token", label: "Lead", blurb: "Adds the metrics dashboard" },
  { token: "dev-admin-token", label: "Admin", blurb: "Adds administration and onboarding" },
];

export function LoginPage() {
  const navigate = useNavigate();
  const [token, setTokenValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  /** Shared by the form and the role buttons: store the credential, prove it works, then route. */
  const signInWith = async (candidate: string) => {
    setBusy(candidate);
    setError(null);
    setToken(candidate);
    try {
      await api.get<CurrentUser>("/workspace/me");
      navigate("/queue", { replace: true });
    } catch (caught) {
      // The request wrapper clears the token on a 401, but not on a transport failure; clearing
      // here too means a failed attempt never leaves a half-signed-in state behind for the next
      // page load to trip over.
      clearToken();
      const unreachable = caught instanceof ApiError && caught.status === 0;
      setError(
        unreachable
          ? "Cannot reach the server. Check that the API is running on port 8000."
          : "Sign-in failed. Check your credentials and try again.",
      );
    } finally {
      setBusy(null);
    }
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!token.trim()) {
      setError("Enter your access token.");
      return;
    }
    void signInWith(token.trim());
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100 px-4">
      <div className="card w-full max-w-md p-8">
        <h1 className="text-lg font-semibold">Support Triage</h1>
        <p className="mt-1 text-sm text-slate-600">Sign in to the agent workspace.</p>

        <div className="mt-6">
          <span className="label">Development sign-in</span>
          <div className="mt-2 space-y-2">
            {DEV_ROLES.map((role) => (
              <button
                key={role.token}
                type="button"
                className="btn-secondary w-full justify-between text-left"
                disabled={busy !== null}
                onClick={() => void signInWith(role.token)}
              >
                <span className="font-semibold">
                  {busy === role.token ? `Signing in as ${role.label}…` : `Continue as ${role.label}`}
                </span>
                <span className="ml-3 text-xs font-normal text-slate-500">{role.blurb}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="mt-6 flex items-center gap-3">
          <span className="h-px flex-1 bg-slate-200" />
          <span className="text-xs uppercase tracking-wide text-slate-400">or enter a token</span>
          <span className="h-px flex-1 bg-slate-200" />
        </div>

        <form onSubmit={submit} className="mt-4 space-y-4" noValidate>
          <div>
            <label htmlFor="token" className="label">
              Access token
            </label>
            <input
              id="token"
              type="password"
              autoComplete="current-password"
              className="input mt-1"
              value={token}
              onChange={(event) => setTokenValue(event.target.value)}
              aria-describedby={error ? "login-error" : undefined}
              aria-invalid={error ? true : undefined}
            />
          </div>

          {error ? (
            <p id="login-error" role="alert" className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900">
              {error}
            </p>
          ) : null}

          <button type="submit" className="btn-primary w-full justify-center" disabled={busy !== null}>
            {busy !== null ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <p className="mt-6 border-t border-slate-200 pt-4 text-xs text-slate-500">
          Development tokens: <code className="font-mono">dev-agent-token</code>,{" "}
          <code className="font-mono">dev-lead-token</code>, <code className="font-mono">dev-admin-token</code>.
          Single sign-on is out of scope for v1.
        </p>
      </div>
    </div>
  );
}
