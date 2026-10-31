// Whether this page load is the launch of the installed app, for the brand splash. It is the one place the
// splash touches browser storage, and it is `sessionStorage` on purpose: the flag must last for this tab's
// session and no longer (a launch the next day shows the splash again), it holds the constant '1' and
// nothing personal, and sign-out wipes it with the rest of the device (lib/session/signOut.ts). The
// tenant store (lib/storage/tenantStore.ts) is persistent storage and would outlive the session, so it is not
// used here; this file is named in the storage guards like the telemetry session id, which is per tab too.

export const SPLASH_FLAG = 'overwatch:splash-shown';

export type LaunchEnv = {
  matchMedia?: Window['matchMedia'];
  navigator?: { standalone?: boolean };
  sessionStorage?: Storage;
};

/** True once per session, when the page is the installed app. Marks the session as having shown it. */
export function takeLaunchSplash(env: LaunchEnv): boolean {
  try {
    const standalone =
      env.navigator?.standalone === true || env.matchMedia?.('(display-mode: standalone)').matches === true;
    if (!standalone || env.sessionStorage === undefined) return false;
    if (env.sessionStorage.getItem(SPLASH_FLAG) !== null) return false;
    env.sessionStorage.setItem(SPLASH_FLAG, '1');
    return true;
  } catch {
    // Storage that throws (a private window, blocked site data) is "do not show": the app just opens.
    return false;
  }
}

/** What the browser gives the launch check. Reading `sessionStorage` can throw; then there is none. */
export function browserLaunchEnv(): LaunchEnv {
  let storage: Storage | undefined;
  try {
    storage = window.sessionStorage;
  } catch {
    storage = undefined;
  }
  return {
    matchMedia: window.matchMedia?.bind(window),
    navigator: navigator as { standalone?: boolean },
    sessionStorage: storage,
  };
}
