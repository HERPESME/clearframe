import { signOut, type SessionUser } from "./auth";

/**
 * Who you are signed in as, and the way out.
 *
 * This lived inline in the review topbar and nowhere else, so the two screens
 * you actually land on — the dashboard you arrive at after signing in, and
 * Mission Control while a run executes — offered no way to sign out at all.
 * The only exit was to open a production and find the button in its header,
 * which is not a thing anyone would guess.
 *
 * The role chip says how the role was arrived at, not just what it is. A role
 * the server granted is stated plainly; one the visitor chose for themselves on
 * an open-roles deployment is labelled `chosen`, because self-selection
 * presented as governance is worse than no governance at all.
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
  if (!user) return null;
  return (
    <div className="whoami" title={user.email ?? user.uid}>
      <span className="whoami-name">{user.name || user.email || user.uid}</span>
      {openRoles ? (
        <span
          className="whoami-role open"
          title="Roles are open on this deployment so anyone can try every control. Your decisions are still recorded against your email."
        >
          chosen
        </span>
      ) : (
        <span className="whoami-role">{user.role}</span>
      )}
      <button
        type="button"
        className="topbtn"
        onClick={() => void signOut().then(onSignedOut)}
      >
        sign out
      </button>
    </div>
  );
}
