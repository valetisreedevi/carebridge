import { elderIdToken, firebaseConfigured, idToken } from "./firebase";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

// Until Firebase Auth is switched on, the backend identifies callers by these
// headers. The caregiver id is stable per browser; the elder id is whichever
// elder this device is paired to.
const CAREGIVER_KEY = "carebridge.caregiverId";
const ELDER_KEY = "carebridge.elderId";

export function caregiverId(): string {
  let id = localStorage.getItem(CAREGIVER_KEY);
  if (!id) {
    id = `caregiver-${crypto.randomUUID().slice(0, 8)}`;
    localStorage.setItem(CAREGIVER_KEY, id);
  }
  return id;
}

const ELDER_LIST_KEY = "carebridge.elderIds";

/**
 * Everyone this device is set up for.
 *
 * A phone on a shared side table belongs to a household, so this is a list.
 * The old single-id key is migrated on first read rather than dropped, which
 * would silently unpair a device already in use.
 */
export function pairedElderIds(): string[] {
  const stored = localStorage.getItem(ELDER_LIST_KEY);
  if (stored) {
    try {
      const parsed = JSON.parse(stored);
      if (Array.isArray(parsed)) return parsed.filter((id) => typeof id === "string");
    } catch {
      // Corrupt value; fall through to the legacy key.
    }
  }

  const legacy = localStorage.getItem(ELDER_KEY);
  return legacy ? [legacy] : [];
}

export function pairedElderId(): string | null {
  return pairedElderIds()[0] ?? null;
}

/**
 * Whoever just paired goes to the head of the list, and that ordering is load
 * bearing rather than cosmetic. The elder screen decides whether this device
 * has a credential at all by watching the FIRST id, so a phone that still
 * carried an older one appended the new person, kept watching the old one's
 * empty session, and sat on the pairing screen forever — with a correct
 * sign-in behind it and a Continue button that could not do anything, because
 * the first id never changed.
 *
 * The person who just typed a code is the one whose session was proven a
 * moment ago, so they are the right one to anchor to.
 */
export function pairElder(elderId: string): void {
  const ids = [elderId, ...pairedElderIds().filter((id) => id !== elderId)];

  localStorage.setItem(ELDER_LIST_KEY, JSON.stringify(ids));
  localStorage.setItem(ELDER_KEY, ids[0]);
}

export function unpairElder(elderId?: string): void {
  if (!elderId) {
    localStorage.removeItem(ELDER_LIST_KEY);
    localStorage.removeItem(ELDER_KEY);
    return;
  }

  const ids = pairedElderIds().filter((id) => id !== elderId);
  localStorage.setItem(ELDER_LIST_KEY, JSON.stringify(ids));

  if (ids.length) localStorage.setItem(ELDER_KEY, ids[0]);
  else localStorage.removeItem(ELDER_KEY);
}

export class ApiError extends Error {
  status: number;
  /** Structured detail, when the API sent one instead of a plain message. */
  detail: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

/** What the API returns when a medicine by this name already exists. */
export type DuplicateMedicine = {
  message: string;
  existing_id: string;
  existing_name: string;
  existing_times: string[];
};

export function duplicateMedicine(error: unknown): DuplicateMedicine | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;

  const detail = error.detail as DuplicateMedicine | undefined;
  return detail?.existing_id ? detail : null;
}

type Options = {
  method?: string;
  body?: unknown;
  as?: "caregiver" | "elder";
  elderId?: string;
};

async function request<T>(path: string, options: Options = {}): Promise<T> {
  const { method = "GET", body, as = "caregiver", elderId } = options;

  const headers: Record<string, string> = {};

  if (as === "caregiver") {
    // A signed-in caregiver is identified by their Firebase token. The header
    // is the fallback the backend accepts only when AUTH_ENABLED is false.
    const token = firebaseConfigured ? await idToken() : null;
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    } else if (firebaseConfigured) {
      throw new ApiError(401, "Please sign in again");
    } else {
      headers["X-Caregiver-Id"] = caregiverId();
    }
  } else {
    const id = elderId ?? pairedElderId();
    if (!id) throw new ApiError(401, "This device is not paired to anyone yet");

    const token = firebaseConfigured ? await elderIdToken(id) : null;
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    } else if (firebaseConfigured) {
      throw new ApiError(401, "This device needs to be paired again");
    } else {
      headers["X-Elder-Id"] = id;
    }
  }

  const init: RequestInit = { method, headers };

  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }

  const response = await fetch(`${API_URL}${path}`, init);

  if (!response.ok) {
    let detail = response.statusText;
    let structured: unknown;
    try {
      const parsed = await response.json();
      if (typeof parsed.detail === "string") {
        detail = parsed.detail;
      } else if (parsed.detail) {
        // A structured refusal the caller can act on rather than just report.
        structured = parsed.detail;
        detail = parsed.detail.message ?? detail;
      }
    } catch {
      // Non-JSON error body; the status text is the best we have.
    }
    throw new ApiError(response.status, detail, structured);
  }

  if (response.status === 204) return undefined as T;
  return response.json();
}

export type Elder = {
  id: string;
  name: string;
  timezone: string;
  preferred_language: string;
};

export type Medication = {
  id: string;
  elder_id: string;
  name: string;
  dose: string;
  food_instruction: string;
  schedule_times: string[];
  retry_after_minutes: number;
  max_attempts: number;
  active: boolean;
  photo_object_name?: string;
  caregiver_audio_object_name?: string;
  /** How long the doctor prescribed for. Absent or 0 means open-ended. */
  duration_days?: number | null;
  starts_on?: string | null;
  ends_on?: string | null;
};

/** The day as the elder's own phone is told it: the plan, and one word for
 *  where each dose stands. None of the family's working out. */
export type MyDayItem = {
  medication_id: string;
  medication_name: string;
  dose: string | null;
  food_instruction: string | null;
  local_time: string;
  state: "taken" | "now" | "later" | "missed" | "cancelled";
};

export type MyDay = {
  date: string;
  elder_name: string | null;
  language: string;
  items: MyDayItem[];
};

export type DayItem = {
  event_id: string | null;
  medication_id: string;
  medication_name: string;
  dose: string | null;
  food_instruction: string | null;
  /** Sent by the API all along; the dashboard simply never read it. */
  photo_object_name?: string | null;
  local_time: string;
  status: string;
  attempt: number;
  max_attempts: number | null;
  /** False when no reminder physically left the building. */
  reached_a_phone: boolean;
  /** "ELDER" when she answered on her own phone, "CAREGIVER" when the family
   *  recorded it on her behalf. A week that is only green because somebody
   *  ticked it off from another city is a different week. */
  confirmed_source: string | null;
  /** She answered and CareBridge could not tell what she meant. */
  unclear_count: number;
  last_unclear: string | null;
  confirmed_at: string | null;
  acknowledged_at: string | null;
  /** Where this dose falls in a prescribed course, or null for an open-ended
   *  medicine. Counted in days, because days are what the doctor said. */
  course: {
    day: number;
    of: number;
    ends_on: string;
    finished: boolean;
  } | null;
};

/** Doses counted along both axes: what we managed to ask about, and what she
 *  said. `scheduled === asked + unreachable + not_yet_due`, always — the
 *  numbers are shown to families precisely because they add up. */
export type Ledger = {
  scheduled: number;
  asked: number;
  unreachable: number;
  not_yet_due: number;
  taken: number;
  declined: number;
  no_answer: number;
  waiting: number;
  cancelled: number;
  taken_on_trust: number;
  unclear: number;
};

export type Insight = {
  week_starting: string;
  note: string;
  /** False when the note is the deterministic one. The weekly note is a
   *  feature of CareBridge, not of the model being up. */
  narrated: boolean;
  plain_note: string;
  this_week: Ledger & {
    adherence_of_asked: number | null;
    median_minutes_to_taken: number | null;
  };
  usual: Ledger & {
    adherence_of_asked: number | null;
    median_minutes_to_taken: number | null;
  };
  what_changed: {
    metric: string;
    now: number;
    usual: number;
    direction: "worse" | "better" | "ours_to_fix";
  }[];
};

export type SelfTest = {
  ok: boolean;
  checks: { check: string; ok: boolean; detail: string }[];
};

export type CareTeamMember = {
  caregiver_id: string;
  email: string | null;
  name: string | null;
  is_you: boolean;
};

export type HistoryDay = Ledger & { date: string };

/** A phone set up to receive someone's reminders. Never carries the
 *  notification token — the dashboard has no use for a phone's address. */
export type Device = {
  device_id: string;
  platform: string | null;
  label: string | null;
  paired_at: string | null;
  last_seen_at: string | null;
  /** How many other people on this device also get reminders here. */
  shared_with: number;
};

export type Alert = {
  id: string;
  reason: string;
  message: string;
  created_at: string;
};

export type Reminder = {
  event_id: string;
  elder_id: string;
  elder_name: string | null;
  /** Which language this reminder is read and spoken in. Per reminder, not per
   *  device: a shared phone can queue two people who do not share one. */
  elder_language: string;
  medication_id: string;
  medication_name: string;
  dose: string;
  /** The raw enum, translated on the client. `food_instruction_text` is the
   *  English rendering and is only used when nothing translates the enum. */
  food_instruction: string;
  food_instruction_text: string;
  notes: string | null;
  status: string;
  attempt: number;
  photo_url: string | null;
  caregiver_audio_url: string | null;
  has_photo: boolean;
  has_caregiver_audio: boolean;
};

export const api = {
  listElders: () => request<Elder[]>("/api/elders"),

  createElder: (body: {
    name: string;
    timezone: string;
    preferred_language: string;
  }) => request<Elder>("/api/elders", { method: "POST", body }),

  createInvite: (elderId: string) =>
    request<{ code: string; elder_name: string; expires_at: string }>(
      `/api/elders/${elderId}/invites`,
      { method: "POST" },
    ),

  acceptInvite: (code: string) =>
    request<{ elder_id: string; elder_name: string }>("/api/invites/accept", {
      method: "POST",
      body: { code },
    }),

  listCaregivers: (elderId: string) =>
    request<CareTeamMember[]>(`/api/elders/${elderId}/caregivers`),

  removeCaregiver: (elderId: string, memberId: string) =>
    request<void>(`/api/elders/${elderId}/caregivers/${memberId}`, {
      method: "DELETE",
    }),

  acknowledgeAlert: (eventId: string) =>
    request<{ acknowledged_at: string }>(
      `/api/medication-events/${eventId}/acknowledge`,
      { method: "POST" },
    ),

  updateElder: (id: string, body: Record<string, unknown>) =>
    request<Elder>(`/api/elders/${id}`, { method: "PATCH", body }),

  listMedications: (elderId: string) =>
    request<Medication[]>(`/api/elders/${elderId}/medications`),

  createMedication: (body: Record<string, unknown>) =>
    request<Medication>("/api/medications", { method: "POST", body }),

  updateMedication: (id: string, body: Record<string, unknown>) =>
    request<Medication>(`/api/medications/${id}`, { method: "PUT", body }),

  deleteMedication: (id: string) =>
    request<void>(`/api/medications/${id}`, { method: "DELETE" }),

  uploadImage: (id: string, file: Blob, filename: string) => {
    const form = new FormData();
    form.append("file", file, filename);
    return request<{ photo_object_name: string }>(
      `/api/medications/${id}/image-upload`,
      { method: "POST", body: form },
    );
  },

  uploadAudio: (id: string, file: Blob, filename: string) => {
    const form = new FormData();
    form.append("file", file, filename);
    return request<{ caregiver_audio_object_name: string }>(
      `/api/medications/${id}/audio-upload`,
      { method: "POST", body: form },
    );
  },

  today: (elderId: string) =>
    request<{
      elder: Elder;
      date: string;
      items: DayItem[];
      ledger: Ledger;
    }>(`/api/elders/${elderId}/today`),

  /** The week in a sentence, plus the figures behind it. */
  insight: (elderId: string) =>
    request<Insight>(`/api/elders/${elderId}/insight`),

  /** Rings the phone with nothing attached, and reports which link is broken.
   *  Creates no dose — pressing it must not invent a tablet. */
  selfTest: (elderId: string) =>
    request<SelfTest>(`/api/elders/${elderId}/self-test`, { method: "POST" }),

  alerts: () => request<Alert[]>("/api/caregivers/me/alerts"),

  pairingCode: (elderId: string) =>
    request<{
      code: string;
      elder_id: string;
      elder_name: string;
      expires_at: string;
    }>(`/api/elders/${elderId}/pairing-code`, { method: "POST" }),

  pairingToken: (elderId: string) =>
    request<{ elder_id: string; elder_name: string; pairing_token: string }>(
      `/api/elders/${elderId}/pairing-token`,
      { method: "POST" },
    ),

  markTakenByCaregiver: (medicationId: string, localTime: string) =>
    request<{ status: string; confirmed_source: string }>(
      `/api/medications/${medicationId}/mark-taken`,
      { method: "POST", body: { local_time: localTime } },
    ),

  history: (elderId: string, days = 7) =>
    request<{ elder: Elder; days: HistoryDay[] }>(
      `/api/elders/${elderId}/history?days=${days}`,
    ),

  /** Rings one of today's scheduled doses again. The time says which. */
  triggerReminder: (medicationId: string, localTime: string) =>
    request<{ event_id: string; attempt: number; reached_a_phone: boolean }>(
      `/api/medications/${medicationId}/remind-now`,
      { method: "POST", body: { local_time: localTime } },
    ),

  unpairDevice: (elderId: string, fcmToken: string) =>
    request<void>(
      `/api/devices/${elderId}?fcm_token=${encodeURIComponent(fcmToken)}`,
      { method: "DELETE" },
    ),

  /** A paired phone filing its own notification address. The elder id comes
   *  from the device's credentials, never the body. */
  /** Today's plan for whichever elder this device is paired to. */
  myToday: (elderId: string) =>
    request<MyDay>("/api/my/today", { as: "elder", elderId }),

  registerMyDevice: (elderId: string, fcmToken: string, label: string | null) =>
    request<{ id: string; elder_id: string }>("/api/devices/mine", {
      method: "POST",
      body: { fcm_token: fcmToken, platform: "WEB", label },
      as: "elder",
      elderId,
    }),

  listDevices: (elderId: string) =>
    request<Device[]>(`/api/elders/${elderId}/devices`),

  signOutDevices: (elderId: string) =>
    request<{ elder_name: string; devices_signed_out: number }>(
      `/api/elders/${elderId}/devices/sign-out`,
      { method: "POST" },
    ),

  activeReminder: (elderId: string) =>
    request<{
      active: boolean;
      reminder: Reminder | null;
      reminders: Reminder[];
      remaining: number;
    }>("/api/reminders/active", { as: "elder", elderId }),

  markTaken: (eventId: string, elderId: string) =>
    request<{ status: string }>(`/api/reminders/${eventId}/taken`, {
      method: "POST",
      as: "elder",
      elderId,
    }),

  snooze: (eventId: string, elderId: string, minutes: number) =>
    request<{ status: string }>(`/api/reminders/${eventId}/snooze`, {
      method: "POST",
      body: { minutes },
      as: "elder",
      elderId,
    }),

  decline: (eventId: string, elderId: string, reason: string) =>
    request<{ status: string }>(`/api/reminders/${eventId}/decline`, {
      method: "POST",
      body: { reason },
      as: "elder",
      elderId,
    }),

  chat: (elderId: string, eventId: string | null, message: string) =>
    request<{
      reply: string;
      tool_calls: string[];
      event_status: string | null;
    }>("/api/agent/chat", {
      method: "POST",
      body: { elder_id: elderId, event_id: eventId, message },
      as: "elder",
      elderId,
    }),

  /** Media served by the API needs the elder header, so <img src> cannot
   *  fetch it directly. Signed GCS URLs are absolute and pass through. */
  /** The medicine photograph, for the caregiver's own screens.
   *
   *  mediaObjectUrl below signs with the ELDER's credential, which a caregiver
   *  does not hold — so the dashboard could not fetch an image at all, and
   *  simply never showed one. The photograph is the thing the family chose to
   *  upload; not rendering it made every medicine look like an empty record.
   */
  medicationImageUrl: async (medicationId: string): Promise<string> => {
    const token = firebaseConfigured ? await idToken() : null;
    const response = await fetch(
      `${API_URL}/api/medications/${medicationId}/image`,
      {
        headers: token
          ? { Authorization: `Bearer ${token}` }
          : { "X-Caregiver-Id": caregiverId() },
      },
    );
    if (!response.ok) throw new ApiError(response.status, "Could not load photo");

    return URL.createObjectURL(await response.blob());
  },

  mediaObjectUrl: async (path: string, elderId: string): Promise<string> => {
    if (path.startsWith("http")) return path;

    const token = firebaseConfigured ? await elderIdToken(elderId) : null;
    const response = await fetch(`${API_URL}${path}`, {
      headers: token
        ? { Authorization: `Bearer ${token}` }
        : { "X-Elder-Id": elderId },
    });
    if (!response.ok) throw new ApiError(response.status, "Could not load media");

    return URL.createObjectURL(await response.blob());
  },
};
