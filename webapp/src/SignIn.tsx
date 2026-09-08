import { useState } from "react";
import { PosterWall } from "./PosterWall";
import {
  signInWithGoogle,
  signInWithPassword,
  signUpWithPassword,
  type SessionUser,
} from "./auth";

/**
 * The way in — the front of house.
 *
 * A streaming service signs you in over its own library: a wall of posters
 * dimmed behind one dark card. This screen borrows exactly that grammar,
 * except every poster is drawn (see PosterWall.tsx for why a clearance
 * product must not decorate itself with other people's one-sheets), and a
 * projector beam falls across the wall from above, which is the one warm
 * light in the app.
 *
 * Both halves of the promise are here — Google for a reviewer who just wants
 * in, email and password for a production that does not use Google accounts.
 * Whichever is used, the server verifies the token and decides the role; this
 * screen never asserts one.
 */
export function SignIn({
  onSignedIn,
  openRoles = false,
  onPickRole,
}: {
  onSignedIn: (u: SessionUser) => void;
  /** This deployment lets a visitor choose how to explore. */
  openRoles?: boolean;
  onPickRole?: (role: string) => void;
}) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [role, setRole] = useState("legal");
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
      const user = await work();
      if (openRoles) onPickRole?.(role);
      onSignedIn(user);
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

  const swap = () => {
    setMode(mode === "login" ? "signup" : "login");
    setError(null);
  };

  return (
    <div className="auth-screen">
      {/* The house: posters, then the light that dims them, then the beam. */}
      <div className="auth-house" aria-hidden="true">
        <PosterWall />
        <div className="auth-dim" />
        <div className="auth-beam" />
      </div>

      <div className="auth-marquee brand">
        CLEAR<b>FRAME</b>
      </div>

      <div className="auth-card">
        <h1 className="auth-title">
          {mode === "login" ? "Sign in" : "Create your account"}
        </h1>
        <p className="auth-sub">
          Every frame of your footage, cleared before you ship.
        </p>

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
            {busy ? "One moment…" : mode === "login" ? "Sign in" : "Create account"}
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
          <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
            <path
              fill="currentColor"
              d="M21.6 12.2c0-.7-.06-1.4-.18-2H12v3.9h5.4a4.6 4.6 0 0 1-2 3v2.5h3.2c1.9-1.7 3-4.3 3-7.4z"
              opacity=".9"
            />
            <path
              fill="currentColor"
              d="M12 22c2.7 0 5-.9 6.6-2.4l-3.2-2.5c-.9.6-2 1-3.4 1-2.6 0-4.8-1.8-5.6-4.1H3.1v2.6A10 10 0 0 0 12 22z"
              opacity=".7"
            />
            <path
              fill="currentColor"
              d="M6.4 14a6 6 0 0 1 0-3.9V7.5H3.1a10 10 0 0 0 0 9z"
              opacity=".5"
            />
            <path
              fill="currentColor"
              d="M12 6c1.5 0 2.8.5 3.8 1.5L18.7 5A10 10 0 0 0 3.1 7.5l3.3 2.6C7.2 7.8 9.4 6 12 6z"
              opacity=".8"
            />
          </svg>
          Continue with Google
        </button>

        {openRoles && (
          <div className="auth-roles">
            <div className="auth-roles-label">Explore as</div>
            <div className="auth-roles-pills">
              {["legal", "producer", "editor"].map((r) => (
                <button
                  key={r}
                  type="button"
                  className={role === r ? "on" : ""}
                  onClick={() => {
                    setRole(r);
                    onPickRole?.(r);
                  }}
                >
                  {r}
                </button>
              ))}
            </div>
            <p className="auth-roles-note">
              Roles are open on this deployment so you can try every control.
              Decisions are still recorded against your email.
            </p>
          </div>
        )}

        <p className="auth-swap">
          {mode === "login" ? (
            <>
              New to ClearFrame?{" "}
              <button type="button" onClick={swap}>
                Create an account
              </button>
            </>
          ) : (
            <>
              Already have an account?{" "}
              <button type="button" onClick={swap}>
                Sign in
              </button>
            </>
          )}
        </p>
      </div>

      <p className="auth-strapline">
        Gemini watches the footage · Parallel researches the rights · you make
        the call, with evidence attached
      </p>
    </div>
  );
}
