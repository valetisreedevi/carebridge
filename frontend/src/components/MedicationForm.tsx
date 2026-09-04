import { useRef, useState } from "react";
import { clockTime, timeIn } from "../format";
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

/** The API takes up to six; more than that is not a prescription any more. */
const MAX_TIMES = 6;

const TIMES_PER_DAY = [
  { count: 1, label: "Once a day" },
  { count: 2, label: "Twice a day" },
  { count: 3, label: "Three times a day" },
  { count: 4, label: "Four times a day" },
];

/** How long a doctor prescribes for, in the words they use.
 *
 *  Zero is "ongoing", and it has to be a real value rather than an absence:
 *  moving a medicine back off a course is an edit like any other, and an
 *  absent field cannot express it.
 */
const DURATION_OPTIONS = [
  { days: 0, label: "Ongoing — until I stop it" },
  { days: 5, label: "5 days" },
  { days: 7, label: "7 days" },
  { days: 10, label: "10 days" },
  { days: 15, label: "15 days" },
  { days: 30, label: "1 month" },
  { days: 60, label: "2 months" },
  { days: 90, label: "3 months" },
];

/** Where a day's doses fall when nobody has said otherwise.
 *
 *  A caregiver holding a prescription slip knows how many times a day, not
 *  which hours — the hours are ours to suggest and theirs to correct.
 */
const DEFAULT_TIMES: Record<number, string[]> = {
  1: ["08:00"],
  2: ["08:00", "20:00"],
  3: ["08:00", "14:00", "20:00"],
  4: ["08:00", "13:00", "17:00", "21:00"],
};

function shiftBy(hhmm: string, minutes: number): string {
  const [h, m] = hhmm.split(":").map(Number);
  const total = (h * 60 + m + minutes + 1440) % 1440;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(Math.floor(total / 60))}:${pad(total % 60)}`;
}

function defaultTimes(count: number, food: string): string[] {
  // A once-daily tablet taken after food is almost always the evening one.
  if (count === 1 && food === "AFTER_FOOD") return ["20:00"];

  const base = DEFAULT_TIMES[count] ?? DEFAULT_TIMES[1];
  // Otherwise "after food" would land at exactly the hour of the meal.
  return food === "AFTER_FOOD" ? base.map((t) => shiftBy(t, 30)) : base;
}

/** Morning-afternoon-night, the way the prescription itself is written.
 *
 *  Indian slips say 1-0-1 and doctors say BD; a caregiver copying one across
 *  should be able to see their own notation echoed back rather than having to
 *  trust that four clock fields mean the same thing.
 */
function slipNotation(times: string[]): string {
  const slots = [0, 0, 0];
  for (const t of times) {
    const hour = Number(t.split(":")[0]);
    if (hour < 12) slots[0] += 1;
    else if (hour < 17) slots[1] += 1;
    else slots[2] += 1;
  }
  return slots.join("-");
}

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
  // Every time, not just the first. Reading only [0] here and writing back a
  // one-element array is how editing the dose of a twice-daily medicine used
  // to delete its second dose.
  const [times, setTimes] = useState<string[]>(
    existing?.schedule_times?.length ? [...existing.schedule_times] : ["08:00"],
  );
  const [durationDays, setDurationDays] = useState(existing?.duration_days ?? 0);
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
  const here = timeIn(elderTimezone);
  const mine = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const elsewhere = Boolean(elderTimezone) && elderTimezone !== mine;

  const setTimeAt = (index: number, value: string) =>
    setTimes((current) => current.map((t, i) => (i === index ? value : t)));

  const removeTimeAt = (index: number) =>
    setTimes((current) => current.filter((_, i) => i !== index));

  const changeFood = (next: string) => {
    setFood(next);
    // Only re-suggest while the caregiver is still on our suggestions. Once
    // they have typed their own hours, changing the food rule must not throw
    // those away.
    setTimes((current) => {
      const suggested = defaultTimes(current.length, food);
      const untouched = current.every((t, i) => t === suggested[i]);
      return untouched ? defaultTimes(current.length, next) : current;
    });
  };

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
      schedule_times: [...new Set(times)].sort(),
      retry_after_minutes: retry,
      max_attempts: attempts,
      duration_days: durationDays,
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

  /** Folds these times into the medicine that already exists. */
  const addTimeToExisting = async () => {
    if (!clash) return;
    setSaving(true);
    try {
      await api.updateMedication(clash.existing_id, {
        schedule_times: [...new Set([...clash.existing_times, ...times])].sort(),
      });
      setClash(null);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
    } finally {
      setSaving(false);
    }
  };

  const spokenTimes = times.map(clockTime).join(", ");

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
          Food
          <select value={food} onChange={(e) => changeFood(e.target.value)}>
            {FOOD_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label>
          How many times a day
          <select
            value={TIMES_PER_DAY.some((o) => o.count === times.length)
              ? times.length
              : "custom"}
            onChange={(e) => setTimes(defaultTimes(Number(e.target.value), food))}
          >
            {TIMES_PER_DAY.map((option) => (
              <option key={option.count} value={option.count}>
                {option.label}
              </option>
            ))}
            {/* Only reachable by adding rows by hand — a prescription is never
                written as "five times a day" in the first instance. */}
            {!TIMES_PER_DAY.some((o) => o.count === times.length) && (
              <option value="custom">{times.length} times a day</option>
            )}
          </select>
          {/* The notation the slip is actually written in, echoed back so a
              caregiver copying one across can check themselves. Read-only:
              parsing it as input would guess at dosing, and 1-0-1 already
              disagrees with the Dose field about what the 1 means. */}
          <small className="medform__hint">
            {slipNotation(times)} · morning-afternoon-night
          </small>
        </label>
      </div>

      <fieldset className="medform__times">
        <legend>What time for {elderName}</legend>

        {times.map((t, index) => (
          <div className="medform__timeRow" key={index}>
            <input
              type="time"
              value={t}
              onChange={(e) => setTimeAt(index, e.target.value)}
              aria-label={`Dose ${index + 1} of ${times.length}`}
              required
            />
            <small className="medform__hint">{clockTime(t)}</small>
            {times.length > 1 && (
              <button
                type="button"
                className="btn-quiet"
                onClick={() => removeTimeAt(index)}
                aria-label={`Remove the ${clockTime(t)} dose`}
              >
                Remove
              </button>
            )}
          </div>
        ))}

        {times.length < MAX_TIMES && (
          <button
            type="button"
            className="btn-quiet"
            onClick={() => setTimes([...times, "12:00"])}
          >
            Add another time
          </button>
        )}

        <small className="medform__hint">
          OD once · BD twice · TID three times · QID four times a day
        </small>
      </fieldset>

      <label className="medform__duration">
        For how long
        <select
          value={durationDays}
          onChange={(e) => setDurationDays(Number(e.target.value))}
        >
          {DURATION_OPTIONS.map((option) => (
            <option key={option.days} value={option.days}>
              {option.label}
            </option>
          ))}
        </select>
        {/* The whole reason this field exists: a course that ends on its own
            is one nobody has to remember to end. */}
        <small className="medform__hint">
          {durationDays
            ? `${elderName} stops being reminded after ${durationDays} ${
                durationDays === 1 ? "day" : "days"
              }. Starts today.`
            : `${elderName} is reminded every day until you remove it.`}
        </small>
      </label>

      {/* Two knobs almost nobody changes, kept out of the way but with their
          values still readable without opening anything. */}
      <details className="medform__fallback">
        <summary>
          If they do not answer — remind after {retry} min · tell me after{" "}
          {attempts} reminder{attempts > 1 ? "s" : ""}
        </summary>

        <div className="medform__grid">
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
      </details>

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
            {clash.message} Did you mean to add <strong>{spokenTimes}</strong> to
            it?
          </p>
          <div className="medform__clashActions">
            <button
              type="button"
              className="btn-primary btn-primary--sm"
              onClick={addTimeToExisting}
              disabled={saving}
            >
              Add {spokenTimes} to {clash.existing_name}
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
