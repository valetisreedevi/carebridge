import { api } from "./client";
import { firebaseConfig, getAppOrNull } from "./firebase";

const VAPID_KEY = import.meta.env.VITE_FIREBASE_VAPID_KEY;

/**
 * Push needs three values sign-in does not: the sender id, the app id (the
 * installations service will not issue a token without it) and the VAPID key.
 * Any one missing and the reminder screen simply keeps polling, which is what
 * it did before notifications existed.
 */
export const pushConfigured = Boolean(
  VAPID_KEY && firebaseConfig.messagingSenderId && firebaseConfig.appId,
);

export type PushState =
  /** No Notification API — an old browser, or an iOS home screen app not yet added. */
  | "unsupported"
  /** No VAPID key in this build. */
  | "unconfigured"
  /** The person said no. Only they can undo it, in browser settings. */
  | "blocked"
  /** Available, not asked for yet. */
  | "off"
  | "on";

export function pushState(): PushState {
  if (typeof Notification === "undefined" || !("serviceWorker" in navigator)) {
    return "unsupported";
  }
  if (!pushConfigured) return "unconfigured";
  if (Notification.permission === "denied") return "blocked";
  return Notification.permission === "granted" ? "on" : "off";
}

/**
 * A reminder arriving while the elder is looking at the screen.
 *
 * Firebase delivers a push two ways: to the service worker when the page is
 * in the background, and to the page itself when it is open. Only the first
 * was handled, so a phone sitting on the side table with CareBridge open —
 * the state the whole screen is designed around — received the push and threw
 * it away, then caught up on its next poll up to fifteen seconds later.
 *
 * Fifteen seconds is a long time to hold a tablet and wonder. Worse, it is
 * fifteen seconds of silence where her family's voice should be.
 *
 * Returns a function that stops listening, or a no-op when the phone cannot.
 */
export function watchForegroundReminders(onReminder: () => void): () => void {
  const app = getAppOrNull();
  if (!pushConfigured || !app) return () => {};

  let stop = () => {};
  let cancelled = false;

  void (async () => {
    try {
      const { getMessaging, isSupported, onMessage } = await import(
        "firebase/messaging"
      );
      if (!(await isSupported()) || cancelled) return;

      // The payload is deliberately not trusted for content. It says
      // something arrived; the screen then asks the API what is true.
      const unsubscribe = onMessage(getMessaging(app), () => onReminder());
      if (cancelled) unsubscribe();
      else stop = unsubscribe;
    } catch {
      // No foreground channel on this phone. Polling still covers it.
    }
  })();

  return () => {
    cancelled = true;
    stop();
  };
}

/** The worker is in public/, so its URL is stable and its scope is the site. */
function serviceWorkerUrl(): string {
  const params = new URLSearchParams(
    Object.entries(firebaseConfig).filter(
      (entry): entry is [string, string] => typeof entry[1] === "string",
    ),
  );
  return `/firebase-messaging-sw.js?${params}`;
}

/** Enough for a family to tell two phones apart in the dashboard list. */
function deviceLabel(): string {
  const agent = navigator.userAgent;
  if (/iPad|Tablet/i.test(agent)) return "Tablet";
  if (/Android|iPhone|Mobile/i.test(agent)) return "Phone";
  return "Computer";
}

/**
 * Puts this device's notification address on file for everyone it is paired to.
 *
 * `prompt` is the difference between the button and the page load. Asking on
 * load would put a permission dialog in front of a reminder, so the silent
 * path only ever runs once permission is already granted — which it still has
 * to do, because a registration token is not permanent and the phone that
 * registered last week may be addressing nobody today.
 *
 * Never throws. A phone that cannot register notifications is a phone that
 * polls, and that has to keep being true whatever FCM says.
 */
export async function registerForPush(
  elderIds: string[],
  { prompt }: { prompt: boolean },
): Promise<boolean> {
  const app = getAppOrNull();
  if (!pushConfigured || !app || !elderIds.length) return false;

  try {
    // Loaded here rather than imported: the messaging SDK is a large part of
    // the bundle, and a phone that never turns notifications on — or a build
    // with no VAPID key — should not pay to download it.
    const { getMessaging, getToken, isSupported } = await import(
      "firebase/messaging"
    );

    if (!(await isSupported())) return false;

    const permission = prompt
      ? await Notification.requestPermission()
      : Notification.permission;
    if (permission !== "granted") return false;

    const registration = await navigator.serviceWorker.register(
      serviceWorkerUrl(),
      { scope: "/" },
    );

    const token = await getToken(getMessaging(app), {
      vapidKey: VAPID_KEY,
      serviceWorkerRegistration: registration,
    });
    if (!token) return false;

    // One token, filed once per person on this phone: a couple sharing a
    // device each need their own reminders to reach it.
    const label = deviceLabel();
    await Promise.all(
      elderIds.map((elderId) => api.registerMyDevice(elderId, token, label)),
    );
    return true;
  } catch (error) {
    console.warn("Notifications are not available on this device", error);
    return false;
  }
}
