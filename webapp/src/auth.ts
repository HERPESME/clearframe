/**
 * Sign-in, and turning a Firebase token into a ClearFrame session.
 *
 * The server verifies the ID token and hands back a cookie, because three
 * things this app depends on cannot send an Authorization header at all:
 * `EventSource` for the pipeline stream, `<video src>` for the footage, and
 * the `<a href>` that downloads the dossier. A header-only scheme would sign
 * you in and then lock you out of the video.
 *
 * The SDK is imported dynamically so a build with authentication switched off
 * never pays for it, and so a project with no Firebase config still loads.
 */

export type AuthConfig = {
  enabled: boolean;
  firebase: {
    apiKey: string;
    authDomain: string;
    projectId: string;
    appId: string;
  };
};

export type SessionUser = {
  uid: string;
  email: string | null;
  name: string | null;
  role: string;
};

let cachedConfig: AuthConfig | null = null;

export async function loadAuthConfig(): Promise<AuthConfig> {
  if (cachedConfig) return cachedConfig;
  const resp = await fetch("/api/auth/config");
  cachedConfig = (await resp.json()) as AuthConfig;
  return cachedConfig;
}

/** The Firebase Auth instance, created once, only when actually needed. */
async function firebaseAuth() {
  const config = await loadAuthConfig();
  if (!config.firebase.apiKey) {
    throw new Error(
      "Firebase is not configured on the server. Set FIREBASE_API_KEY, " +
        "FIREBASE_AUTH_DOMAIN, FIREBASE_PROJECT_ID and FIREBASE_APP_ID.",
    );
  }
  const { initializeApp, getApps } = await import("firebase/app");
  const { getAuth } = await import("firebase/auth");
  const app = getApps()[0] ?? initializeApp(config.firebase);
  return getAuth(app);
}

/** Exchange a fresh ID token for the server cookie. */
async function openSession(idToken: string): Promise<SessionUser> {
  const resp = await fetch("/api/auth/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ idToken }),
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body?.detail ?? "Could not verify that sign-in.");
  }
  return (await resp.json()) as SessionUser;
}

export async function signInWithGoogle(): Promise<SessionUser> {
  const auth = await firebaseAuth();
  const { GoogleAuthProvider, signInWithPopup } = await import("firebase/auth");
  const cred = await signInWithPopup(auth, new GoogleAuthProvider());
  return openSession(await cred.user.getIdToken());
}

export async function signInWithPassword(
  email: string,
  password: string,
): Promise<SessionUser> {
  const auth = await firebaseAuth();
  const { signInWithEmailAndPassword } = await import("firebase/auth");
  const cred = await signInWithEmailAndPassword(auth, email, password);
  return openSession(await cred.user.getIdToken());
}

export async function signUpWithPassword(
  email: string,
  password: string,
  displayName?: string,
): Promise<SessionUser> {
  const auth = await firebaseAuth();
  const { createUserWithEmailAndPassword, updateProfile } = await import(
    "firebase/auth"
  );
  const cred = await createUserWithEmailAndPassword(auth, email, password);
  if (displayName) await updateProfile(cred.user, { displayName });
  return openSession(await cred.user.getIdToken());
}

export async function signOut(): Promise<void> {
  await fetch("/api/auth/signout", { method: "POST" });
  try {
    const auth = await firebaseAuth();
    const { signOut: fbSignOut } = await import("firebase/auth");
    await fbSignOut(auth);
  } catch {
    /* the server session is gone either way, which is what gates access */
  }
}

/**
 * Keep the cookie fresh.
 *
 * An ID token lasts an hour. The SDK refreshes it on its own schedule and
 * fires this every time it does, so the cookie is replaced before it expires
 * rather than after a request has already failed.
 */
export async function keepSessionFresh(onUser: (u: SessionUser | null) => void) {
  const auth = await firebaseAuth();
  const { onIdTokenChanged } = await import("firebase/auth");
  return onIdTokenChanged(auth, async (user) => {
    if (!user) return; // signing out is handled where it is asked for
    try {
      onUser(await openSession(await user.getIdToken()));
    } catch {
      onUser(null);
    }
  });
}

/** Who the server thinks we are, or null. */
export async function currentUser(): Promise<SessionUser | null> {
  const resp = await fetch("/api/auth/me");
  return resp.ok ? ((await resp.json()) as SessionUser) : null;
}
