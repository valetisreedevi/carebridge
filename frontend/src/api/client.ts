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

export function pairedElderId(): string | null {
  return localStorage.getItem(ELDER_KEY);
}

export function pairElder(elderId: string): void {
  localStorage.setItem(ELDER_KEY, elderId);
}

export function unpairElder(): void {
  localStorage.removeItem(ELDER_KEY);
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
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
    headers["X-Caregiver-Id"] = caregiverId();
  } else {
    const id = elderId ?? pairedElderId();
    if (!id) throw new ApiError(401, "This device is not paired to anyone yet");
    headers["X-Elder-Id"] = id;
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
    try {
      const parsed = await response.json();
      detail = typeof parsed.detail === "string" ? parsed.detail : detail;
    } catch {
      // Non-JSON error body; the status text is the best we have.
    }
    throw new ApiError(response.status, detail);
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

  listMedications: (elderId: string) =>
    request<Medication[]>(`/api/elders/${elderId}/medications`),

  createMedication: (body: Record<string, unknown>) =>
    request<Medication>("/api/medications", { method: "POST", body }),

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

  triggerReminder: (medicationId: string) =>
    request<{ event_id: string }>("/api/demo/trigger-reminder", {
      method: "POST",
      body: { medication_id: medicationId },
    }),

  activeReminder: (elderId: string) =>
    request<{ active: boolean; reminder: Reminder | null }>(
      "/api/reminders/active",
      { as: "elder", elderId },
    ),

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

    const response = await fetch(`${API_URL}${path}`, {
      headers: { "X-Elder-Id": elderId },
    });
    if (!response.ok) throw new ApiError(response.status, "Could not load media");

    return URL.createObjectURL(await response.blob());
  },
};
