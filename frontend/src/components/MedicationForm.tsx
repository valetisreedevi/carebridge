import { useEffect, useRef, useState } from "react";
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

/** The parts of a day a dose is actually prescribed for.
 *
 *  "Twice a day" is underdetermined - it can mean morning and night, morning
 *  and afternoon, or afternoon and night - so asking for a count and inventing
 *  the hours was a guess. A slip says WHICH parts of the day, so that is what
 *  this asks. The count falls out of the answer.
 *
 *  `from`/`to` are hours, half-open, and every hour of the day belongs to
 *  exactly one slot so a time can never light up two chips.
 */
const SLOTS = [
  { key: "morning", label: "Morning", at: "08:00", from: 0, to: 12 },
  { key: "afternoon", label: "Afternoon", at: "14:00", from: 12, to: 17 },
  { key: "evening", label: "Evening", at: "18:00", from: 17, to: 20 },
  { key: "night", label: "Night", at: "21:00", from: 20, to: 24 },
];

type Slot = (typeof SLOTS)[number];

function hourOf(hhmm: string): number {
  return Number(hhmm.split(":")[0]);
}

function inSlot(hhmm: string, slot: Slot): boolean {
  const hour = hourOf(hhmm);
  return hour >= slot.from && hour < slot.to;
}

function shiftBy(hhmm: string, minutes: number): string {
  const [h, m] = hhmm.split(":").map(Number);
  const total = (h * 60 + m + minutes + 1440) % 1440;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(Math.floor(total / 60))}:${pad(total % 60)}`;
}

/** When a dose in this slot lands, given the food rule. */
function slotTime(slot: Slot, food: string): string {
  // Otherwise "after food" would land at exactly the hour of the meal.
  return food === "AFTER_FOOD" ? shiftBy(slot.at, 30) : slot.at;
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
  const [playing, setPlaying] = useState(false);

  const recorder = useRef<MediaRecorder | null>(null);
  // Resolved by the recorder's own stop handler. save() waits on this when the
  // caregiver is still recording, because "record, speak, save" is what people
  // actually do and the blob does not exist until the recorder has stopped.
  const finished = useRef<((blob: Blob) => void) | null>(null);
  // Held separately so the microphone can be released if this form closes
  // mid-recording. It used to be stopped only inside onstop, so closing the
  // editor while recording left the mic light on until the tab was closed.
  const mic = useRef<MediaStream | null>(null);

  useEffect(
    () => () => {
      if (recorder.current?.state === "recording") recorder.current.stop();
      mic.current?.getTracks().forEach((track) => track.stop());
    },
    [],
  );

  // Read at render rather than ticked: it only has to be right while somebody
  // is filling the form in, and every keystroke re-renders.
  const here = timeIn(elderTimezone);
  const mine = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const elsewhere = Boolean(elderTimezone) && elderTimezone !== mine;

  const setTimeAt = (index: number, value: string) =>
    setTimes((current) => current.map((t, i) => (i === index ? value : t)));

  const removeTimeAt = (index: number) =>
    setTimes((current) => current.filter((_, i) => i !== index));

  /** Turning a part of the day on adds its dose; turning it off removes it. */
  const toggleSlot = (slot: Slot) => {
    setTimes((current) => {
      const mine = current.filter((t) => inSlot(t, slot));

      if (mine.length) {
        const left = current.filter((t) => !inSlot(t, slot));
        // A medicine with no time at all is not a medicine. The last chip
        // stays on rather than leaving the form in a state it cannot save.
        return left.length ? left : current;
      }

      if (current.length >= MAX_TIMES) return current;
      return [...current, slotTime(slot, food)].sort();
    });
  };

  const changeFood = (next: string) => {
    setFood(next);
    // Only re-suggest hours the caregiver never touched. A time that still
    // matches one of our own suggestions moves with the food rule; anything
    // they typed themselves is left exactly where they put it.
    setTimes((current) =>
      current
        .map((t) => {
          const slot = SLOTS.find((sl) => slotTime(sl, food) === t);
          return slot ? slotTime(slot, next) : t;
        })
        .sort(),
    );
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
        const blob = new Blob(chunks, { type: "audio/webm" });
        setRecording(blob);
        // Hands the blob to whoever is waiting - save(), if the caregiver
        // pressed Save without pressing Stop first.
        finished.current?.(blob);
        finished.current = null;
        stream.getTracks().forEach((track) => track.stop());
        mic.current = null;
      };

      media.start();
      recorder.current = media;
      mic.current = stream;
      setListening(true);
      setError(null);
    } catch {
      setError("Microphone access was blocked.");
    }
  };

  /** Stops the recorder if it is running and returns the finished blob.
   *
   *  Returns the state value when nothing is recording, so callers can treat
   *  the two cases the same. The blob is returned rather than read back from
   *  state because setRecording has not landed by the time save() continues.
   */
  const stopRecordingIfRunning = async (): Promise<Blob | null> => {
    const media = recorder.current;
    // Asked of the recorder rather than of React state: stop() throws if it is
    // not recording, and this runs before save()'s try block, so a throw here
    // would escape and leave the form spinning on Saving for ever.
    if (media?.state !== "recording") return recording;

    const blob = await new Promise<Blob>((resolve) => {
      finished.current = resolve;
      media.stop();
    });
    setListening(false);
    return blob;
  };

  /** The voice message goes first, deliberately.
   *
   *  These used to run photo-first in the same try as the medicine itself, so
   *  a photo the phone made too large threw before the recording was ever
   *  uploaded - and the caregiver saw a save error for a save that had already
   *  succeeded. Each is now reported for what it is, and neither can discard
   *  the other.
   */
  const saveMedia = async (medicationId: string, voice: Blob | null) => {
    if (voice) {
      try {
        await api.uploadAudio(medicationId, voice, "voice.webm");
      } catch {
        throw new Error(
          "The medicine was saved, but the voice message could not be uploaded. Record it again.",
        );
      }
    }

    if (photo) {
      try {
        await api.uploadImage(medicationId, photo, photo.name);
      } catch {
        throw new Error(
          "The medicine was saved, but the photo could not be uploaded. Try a smaller one.",
        );
      }
    }
  };

  /** Plays back the message the SERVER holds, not the one in this form.
   *
   *  The only way to tell a recording that uploaded from one that quietly did
   *  not is to ask the server for it and listen.
   */
  const playStored = async () => {
    if (!existing) return;
    setPlaying(true);
    try {
      const url = await api.medicationAudioUrl(existing.id);
      const audio = new Audio(url);
      audio.onended = () => {
        setPlaying(false);
        URL.revokeObjectURL(url);
      };
      await audio.play();
    } catch {
      setPlaying(false);
      setError("Could not play the saved voice message.");
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

    // Before anything else: if they are still recording, finish it. Pressing
    // Save while the recorder runs used to leave `recording` null, so the
    // upload was never attempted and nothing failed - the medicine saved, the
    // photo uploaded, and the elder went on hearing the previous message in
    // the previous language.
    const voice = await stopRecordingIfRunning();

    try {
      const medication = existing
        ? await api.updateMedication(existing.id, fields)
        : await api.createMedication({
            elder_id: elderId,
            ...fields,
            allow_duplicate: force,
          });

      await saveMedia(medication.id, voice);
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
    // Anything they recorded or photographed on the way to this dialog belongs
    // to the medicine they are folding into. This used to send the times alone
    // and drop both without saying so.
    const voice = await stopRecordingIfRunning();
    try {
      await api.updateMedication(clash.existing_id, {
        schedule_times: [...new Set([...clash.existing_times, ...times])].sort(),
      });
      await saveMedia(clash.existing_id, voice);
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

      </div>

      <fieldset className="medform__times">
        <legend>When does {elderName} take it</legend>

        <div className="medform__slots" role="group" aria-label="Parts of the day">
          {SLOTS.map((slot) => {
            const on = times.some((t) => inSlot(t, slot));
            return (
              <button
                key={slot.key}
                type="button"
                className={`slot ${on ? "slot--on" : ""}`}
                aria-pressed={on}
                onClick={() => toggleSlot(slot)}
              >
                {slot.label}
              </button>
            );
          })}
        </div>

        {/* The notation the slip is actually written in, echoed back so a
            caregiver copying one across can check themselves. Three buckets,
            not four: evening counts as night here because that is how the
            slip counts it. Read-only - parsing it as input would guess at
            dosing, and 1-0-1 already disagrees with the Dose field about what
            the 1 means. */}
        <p className="medform__notation">
          <strong>{slipNotation(times)}</strong>
          <small>morning-afternoon-night</small>
        </p>

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

        {/* What the SERVER holds, not what this form is holding. A recording
            that failed to upload used to look exactly like one that worked -
            the old message went on playing, in the old language, and nothing
            on this screen disagreed. */}
        <div className="medform__voice">
          <span>Your voice</span>
          <button
            type="button"
            className={listening ? "medform__rec" : ""}
            onClick={toggleRecording}
          >
            {listening
              ? "Stop recording"
              : recording
                ? "Record again"
                : existing?.caregiver_audio_object_name
                  ? "Replace the message"
                  : "Record a message"}
          </button>

          {listening && <small>Recording — this will be saved when you save.</small>}

          {!listening && recording && (
            <small className="is-new">
              New message ready · it replaces the saved one when you save
            </small>
          )}

          {!listening && !recording && existing?.caregiver_audio_object_name && (
            <small>
              A message is saved and plays at reminder time.{" "}
              <button
                type="button"
                className="medform__play"
                onClick={playStored}
                disabled={playing}
              >
                {playing ? "Playing…" : "Hear it"}
              </button>
            </small>
          )}

          {!listening && !recording && existing && !existing.caregiver_audio_object_name && (
            <small>
              No message saved yet — CareBridge reads the reminder out instead.
            </small>
          )}
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
