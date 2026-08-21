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

export function pairElder(elderId: string): void {
  const ids = pairedElderIds();
  if (!ids.includes(elderId)) ids.push(elderId);

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
};

export type DayItem = {
  event_id: string | null;
  medication_id: string;
  medication_name: string;
  dose: string | null;
  food_instruction: string | null;
  local_time: string;
  status: string;
  attempt: number;
  max_attempts: number | null;
  confirmed_at: string | null;
  acknowledged_at: string | null;
};

export type CareTeamMember = {
  caregiver_id: string;
  email: string | null;
  name: string | null;
  is_you: boolean;
};

export type HistoryDay = {
  date: string;
  taken: number;
  missed: number;
  declined: number;
  total: number;
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
  medication_id: string;
  medication_name: string;
  dose: string;
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
    request<{ elder: Elder; date: string; items: DayItem[] }>(
      `/api/elders/${elderId}/today`,
    ),

  alerts: () => request<Alert[]>("/api/caregivers/me/alerts"),

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

  triggerReminder: (medicationId: string) =>
    request<{ event_id: string }>(
      `/api/medications/${medicationId}/remind-now`,
      { method: "POST" },
    ),

  unpairDevice: (elderId: string, fcmToken: string) =>
    request<void>(
      `/api/devices/${elderId}?fcm_token=${encodeURIComponent(fcmToken)}`,
      { method: "DELETE" },
    ),

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
