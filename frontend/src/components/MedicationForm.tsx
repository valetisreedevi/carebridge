import { useRef, useState } from "react";
import { api } from "../api/client";

const FOOD_OPTIONS = [
  { value: "BEFORE_FOOD", label: "Before food" },
  { value: "AFTER_FOOD", label: "After food" },
  { value: "WITH_FOOD", label: "With food" },
  { value: "ANY_TIME", label: "Any time" },
];

type Props = {
  elderId: string;
  onSaved: () => void;
};

export default function MedicationForm({ elderId, onSaved }: Props) {
  const [name, setName] = useState("");
  const [dose, setDose] = useState("");
  const [food, setFood] = useState("BEFORE_FOOD");
  const [time, setTime] = useState("08:00");
  const [retry, setRetry] = useState(10);
  const [attempts, setAttempts] = useState(2);
  const [photo, setPhoto] = useState<File | null>(null);
  const [recording, setRecording] = useState<Blob | null>(null);
  const [listening, setListening] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const recorder = useRef<MediaRecorder | null>(null);

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

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);

    try {
      const medication = await api.createMedication({
        elder_id: elderId,
        name: name.trim(),
        dose: dose.trim(),
        food_instruction: food,
        schedule_times: [time],
        retry_after_minutes: retry,
        max_attempts: attempts,
      });

      // Media is optional; a failed upload should not lose the medication.
      if (photo) await api.uploadImage(medication.id, photo, photo.name);
      if (recording) await api.uploadAudio(medication.id, recording, "voice.webm");

      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="medform" onSubmit={save}>
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
          <button type="button" onClick={toggleRecording}>
            {listening ? "Stop recording" : recording ? "Record again" : "Record"}
          </button>
          {recording && <small>Saved · plays at reminder time</small>}
        </div>
      </div>

      {error && <p className="dash__error">{error}</p>}

      <button type="submit" className="medform__save" disabled={saving}>
        {saving ? "Saving…" : "Save medication"}
      </button>
    </form>
  );
}
