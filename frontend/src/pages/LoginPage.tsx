import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, api, setToken } from "../api/client";
import type { CurrentUser } from "../api/types";

// UI-1. v1 authenticates with the static per-role bearer tokens described in
// libs/platform/auth.py — there is no password store yet, so the form takes the token as the
// credential. The error message is deliberately identical for "no such user" and "wrong token".

export function LoginPage() {
  const navigate = useNavigate();
  const [token, setTokenValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!token.trim()) {
      setError("Enter your access token.");
      return;
    }
    setBusy(true);
    setError(null);
    setToken(token.trim());
    try {
      const user = await api.get<CurrentUser>("/workspace/me");
      navigate(user.role === "agent" ? "/queue" : "/queue", { replace: true });
    } catch (caught) {
      const message =
        caught instanceof ApiError && caught.status === 0
          ? "Cannot reach the server. Check that the API is running."
          : "Sign-in failed. Check your credentials and try again.";
      setError(message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100 px-4">
      <div className="card w-full max-w-md p-8">
        <h1 className="text-lg font-semibold">Support Triage</h1>
        <p className="mt-1 text-sm text-slate-600">Sign in to the agent workspace.</p>

        <form onSubmit={submit} className="mt-6 space-y-4" noValidate>
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

          <button type="submit" className="btn-primary w-full justify-center" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
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
