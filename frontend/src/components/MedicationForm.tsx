import { useRef, useState } from "react";
import {
  api,
  duplicateMedicine,
  type DuplicateMedicine,
  type Medication,
} from "../api/client";

const FOOD_OPTIONS = [
  { value: "BEFORE_FOOD", label: "Before food" },
  { value: "AFTER_FOOD", label: "After food" },
  { value: "WITH_FOOD", label: "With food" },
  { value: "ANY_TIME", label: "Any time" },
];

type Props = {
  elderId: string;
  elderName: string;
  /** IANA zone the times are read in — theirs, not the caregiver's. */
  elderTimezone: string;
  onSaved: () => void;
  /** Present when editing; absent when adding a new medication. */
  existing?: Medication;
  onCancel?: () => void;
};

/** What the clock says where they are, right now. */
function timeThere(timezone: string): string | null {
  try {
    return new Intl.DateTimeFormat("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      timeZone: timezone,
    }).format(new Date());
  } catch {
    return null;
  }
}

/** "15:05" as something a person reads: "3:05 pm". */
function spoken(time: string): string {
  const [hours, minutes] = time.split(":").map(Number);
  if (Number.isNaN(hours) || Number.isNaN(minutes)) return time;

  const suffix = hours < 12 ? "am" : "pm";
  const hour12 = hours % 12 === 0 ? 12 : hours % 12;
  return `${hour12}:${String(minutes).padStart(2, "0")} ${suffix}`;
}

export default function MedicationForm({
  elderId,
  elderName,
  elderTimezone,
  onSaved,
  existing,
  onCancel,
}: Props) {
  const [name, setName] = useState(existing?.name ?? "");
  const [dose, setDose] = useState(existing?.dose ?? "");
  const [food, setFood] = useState(existing?.food_instruction ?? "BEFORE_FOOD");
  const [time, setTime] = useState(existing?.schedule_times?.[0] ?? "08:00");
  const [retry, setRetry] = useState(existing?.retry_after_minutes ?? 10);
  const [attempts, setAttempts] = useState(existing?.max_attempts ?? 2);
  const [photo, setPhoto] = useState<File | null>(null);
  const [recording, setRecording] = useState<Blob | null>(null);
  const [listening, setListening] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [clash, setClash] = useState<DuplicateMedicine | null>(null);

  const recorder = useRef<MediaRecorder | null>(null);

  // Read at render rather than ticked: it only has to be right while somebody
  // is filling the form in, and every keystroke re-renders.
  const here = timeThere(elderTimezone);
  const mine = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const elsewhere = Boolean(elderTimezone) && elderTimezone !== mine;

  const toggleRecording = async () => {
    if (listening) {
      recorder.current?.stop();
      setListening(false);
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const chunks: BlobPart[] = [];
      const media = new MediaRecorder(stream, { mimeType: "audio/webm" });

      media.ondataavailable = (event) => chunks.push(event.data);
      media.onstop = () => {
        setRecording(new Blob(chunks, { type: "audio/webm" }));
        stream.getTracks().forEach((track) => track.stop());
      };

      media.start();
      recorder.current = media;
      setListening(true);
      setError(null);
    } catch {
      setError("Microphone access was blocked.");
    }
  };

  const save = async (event: React.FormEvent | null, force = false) => {
    event?.preventDefault();
    setSaving(true);
    setError(null);
    if (force) setClash(null);

    const fields = {
      name: name.trim(),
      dose: dose.trim(),
      food_instruction: food,
      schedule_times: [time],
      retry_after_minutes: retry,
      max_attempts: attempts,
    };

    try {
      const medication = existing
        ? await api.updateMedication(existing.id, fields)
        : await api.createMedication({
            elder_id: elderId,
            ...fields,
            allow_duplicate: force,
          });

      // Media is optional; a failed upload should not lose the medication.
      if (photo) await api.uploadImage(medication.id, photo, photo.name);
      if (recording) await api.uploadAudio(medication.id, recording, "voice.webm");

      onSaved();
    } catch (e) {
      // Not an error to report but a choice to offer: almost always the
      // caregiver meant another time on the medicine they already have.
      const duplicate = duplicateMedicine(e);
      if (duplicate) setClash(duplicate);
      else setError(e instanceof Error ? e.message : "Could not save");
    } finally {
      setSaving(false);
    }
  };

  /** Folds this time into the medicine that already exists. */
  const addTimeToExisting = async () => {
    if (!clash) return;
    setSaving(true);
    try {
      await api.updateMedication(clash.existing_id, {
        schedule_times: [...new Set([...clash.existing_times, time])],
      });
      setClash(null);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="medform" onSubmit={save}>
      {/* The whole point of the product is a family who do not live together,
          so this is the ordinary case rather than the edge one. Said once at
          the top, because by the time they reach the time field they are
          already thinking in their own afternoon. */}
      {elsewhere && (
        <p className="medform__zone">
          Times are {elderName}'s local time
          {here && <> — it is <strong>{here}</strong> there now</>}, not yours.
        </p>
      )}

      <div className="medform__grid">
        <label>
          Medicine
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Amlodipine"
            required
          />
        </label>

        <label>
          Dose
          <input
            value={dose}
            onChange={(e) => setDose(e.target.value)}
            placeholder="1 tablet"
            required
          />
        </label>

        <label>
          Time
          <input
            type="time"
            value={time}
            onChange={(e) => setTime(e.target.value)}
            required
          />
          {/* Whose clock this is. A caregiver abroad is the person this
              product is for, and a bare time field silently means something
              other than the one on their own wall. */}
          <small className="medform__hint">
            {spoken(time)} for {elderName}
            {here && <> · {here} there now</>}
          </small>
        </label>

        <label>
          Food
          <select value={food} onChange={(e) => setFood(e.target.value)}>
            {FOOD_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label>
          Remind again after
          <select
            value={retry}
            onChange={(e) => setRetry(Number(e.target.value))}
          >
            {[5, 10, 15, 30].map((minutes) => (
              <option key={minutes} value={minutes}>
                {minutes} minutes
              </option>
            ))}
          </select>
        </label>

        <label>
          Then tell me after
          <select
            value={attempts}
            onChange={(e) => setAttempts(Number(e.target.value))}
          >
            {[1, 2, 3].map((count) => (
              <option key={count} value={count}>
                {count} reminder{count > 1 ? "s" : ""}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="medform__media">
        <label className="medform__file">
          Medicine photo
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            onChange={(e) => setPhoto(e.target.files?.[0] ?? null)}
          />
        </label>

        <div className="medform__voice">
          <span>Your voice</span>
          <button
            type="button"
            className={listening ? "medform__rec" : ""}
            onClick={toggleRecording}
          >
            {listening ? "Stop recording" : recording ? "Record again" : "Record a message"}
          </button>
          {recording && <small>Saved · plays at reminder time</small>}
        </div>
      </div>

      {error && <p className="dash__error">{error}</p>}

      {clash && (
        <div className="medform__clash" role="alertdialog">
          <p>
            {clash.message} Did you mean to add <strong>{time}</strong> to it?
          </p>
          <div className="medform__clashActions">
            <button
              type="button"
              className="btn-primary btn-primary--sm"
              onClick={addTimeToExisting}
              disabled={saving}
            >
              Add {time} to {clash.existing_name}
            </button>
            <button
              type="button"
              className="btn-quiet"
              onClick={() => save(null, true)}
              disabled={saving}
            >
              No, it is a separate medicine
            </button>
          </div>
        </div>
      )}

      <div className="medform__actions">
        <button type="submit" className="medform__save btn-primary" disabled={saving}>
          {saving ? "Saving…" : existing ? "Save changes" : "Save medication"}
        </button>
        {onCancel && (
          <button type="button" className="btn-quiet" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}
