import { useState } from "react";
import { signOut, type SessionUser } from "./auth";

/**
 * The way out. One button, top right, on every screen behind the gate.
 *
 * This began as a name, a role chip and a button in a glass pill, and the pill
 * was doing the work of a header on screens that have no header. The identity
 * did not need to be pinned to the layout to be true: it moved into the
 * button's tooltip, where a reviewer can still check who the app thinks they
 * are without it occupying the corner of every page.
 *
 * What is NOT lost with the chip: the sign-in role picker still labels a
 * self-selected role as such, and the audit trail still records the verified
 * email rather than the job title. Those are the two places the honesty
 * actually has to live — a decision is recorded against a person, and the
 * person was told how they got their role when they chose it.
 *
 * The pending state matters more than it looks. `signOut()` swallows Firebase
 * SDK failures internally, but the `POST /api/auth/signout` that clears the
 * cookie can still reject — and then `onSignedOut` never fires and the button
 * silently does nothing. Better to say so.
 */
export function WhoAmI({
  user,
  openRoles,
  onSignedOut,
}: {
  user: SessionUser | null;
  openRoles: boolean;
  onSignedOut: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  if (!user) return null;

  const who = user.name || user.email || user.uid;
  const how = openRoles ? `${user.role} (chosen)` : user.role;

  return (
    <button
      type="button"
      className="signout"
      disabled={busy}
      title={
        failed
          ? "Sign-out failed — check your connection and try again"
          : `Signed in as ${who} · role: ${how}`
      }
      onClick={() => {
        setBusy(true);
        setFailed(false);
        void signOut()
          .then(onSignedOut)
          .catch(() => setFailed(true))
          .finally(() => setBusy(false));
      }}
    >
      {failed ? "Retry sign out" : busy ? "Signing out…" : "Sign out"}
    </button>
  );
}
