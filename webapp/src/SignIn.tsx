import { useState } from "react";
import {
  signInWithGoogle,
  signInWithPassword,
  signUpWithPassword,
  type SessionUser,
} from "./auth";

/**
 * The way in.
 *
 * Split layout: the form on the left, the picture on the right, because this
 * is a tool for looking at film and the sign-in should say so before you are
 * inside it.
 *
 * Both halves of the promise are here — Google for a reviewer who just wants
 * in, email and password for a production that does not use Google accounts.
 * Whichever is used, the server verifies the token and decides the role; this
 * screen never asserts one.
 */
export function SignIn({ onSignedIn }: { onSignedIn: (u: SessionUser) => void }) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (work: () => Promise<SessionUser>) => {
    setBusy(true);
    setError(null);
    try {
      onSignedIn(await work());
    } catch (e) {
      setError(e instanceof Error ? e.message : "That did not work.");
    } finally {
      setBusy(false);
    }
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (mode === "signup" && password !== confirm) {
      setError("Those two passwords are not the same.");
      return;
    }
    void run(() =>
      mode === "login"
        ? signInWithPassword(email, password)
        : signUpWithPassword(email, password, name || undefined),
    );
  };

  return (
    <div className="auth-screen">
      <div className="auth-panel">
        <div className="auth-form">
          <div className="brand auth-brand">
            CLEAR<b>FRAME</b>
          </div>
          <h1 className="auth-title">Welcome</h1>
          <p className="auth-sub">
            Every frame, cleared — before you ship.
          </p>

          <div className="auth-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={mode === "login"}
              className={mode === "login" ? "on" : ""}
              onClick={() => setMode("login")}
            >
              LOGIN
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "signup"}
              className={mode === "signup" ? "on" : ""}
              onClick={() => setMode("signup")}
            >
              SIGNUP
            </button>
          </div>

          <form className="auth-fields" onSubmit={submit}>
            {mode === "signup" && (
              <input
                className="auth-input"
                placeholder="Your name"
                value={name}
                autoComplete="name"
                onChange={(e) => setName(e.target.value)}
              />
            )}
            <input
              className="auth-input"
              type="email"
              required
              placeholder="you@studio.com"
              value={email}
              autoComplete="email"
              onChange={(e) => setEmail(e.target.value)}
            />
            <input
              className="auth-input"
              type="password"
              required
              minLength={6}
              placeholder="Password"
              value={password}
              autoComplete={
                mode === "login" ? "current-password" : "new-password"
              }
              onChange={(e) => setPassword(e.target.value)}
            />
            {mode === "signup" && (
              <input
                className="auth-input"
                type="password"
                required
                minLength={6}
                placeholder="Confirm password"
                value={confirm}
                autoComplete="new-password"
                onChange={(e) => setConfirm(e.target.value)}
              />
            )}

            {error && <div className="auth-error">{error}</div>}

            <button className="auth-primary" type="submit" disabled={busy}>
              {busy ? "…" : mode === "login" ? "Sign in" : "Create account"}
            </button>
          </form>

          <div className="auth-or">
            <span>or</span>
          </div>

          <button
            type="button"
            className="auth-google"
            disabled={busy}
            onClick={() => void run(signInWithGoogle)}
          >
            Continue with Google
          </button>

          <p className="auth-note">
            New accounts can read every finding and record no decisions. Ask
            your clearance lead to be added as legal or producer.
          </p>
        </div>

        <div className="auth-art" aria-hidden="true">
          {/* No stock photography in the repo, so the panel is drawn: a
              frame being measured, which is what the product does. */}
          <svg viewBox="0 0 400 520" preserveAspectRatio="xMidYMid slice">
            <defs>
              <linearGradient id="ag" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.55" />
                <stop offset="55%" stopColor="var(--accent-2)" stopOpacity="0.30" />
                <stop offset="100%" stopColor="var(--bg)" stopOpacity="0.95" />
              </linearGradient>
            </defs>
            <rect width="400" height="520" fill="url(#ag)" />
            {[...Array(13)].map((_, i) => (
              <rect
                key={i}
                x={14}
                y={12 + i * 40}
                width={26}
                height={26}
                rx={4}
                fill="var(--bg)"
                opacity="0.55"
              />
            ))}
            {[...Array(13)].map((_, i) => (
              <rect
                key={`r${i}`}
                x={360}
                y={12 + i * 40}
                width={26}
                height={26}
                rx={4}
                fill="var(--bg)"
                opacity="0.55"
              />
            ))}
            <rect
              x={120}
              y={150}
              width={160}
              height={110}
              fill="none"
              stroke="var(--ink)"
              strokeWidth={2}
              rx={3}
            />
            <rect
              x={148}
              y={300}
              width={104}
              height={64}
              fill="none"
              stroke="var(--accent-2)"
              strokeWidth={2}
              strokeDasharray="6 5"
              rx={3}
            />
          </svg>
        </div>
      </div>
    </div>
  );
}
