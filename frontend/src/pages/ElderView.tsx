import { useCallback, useEffect, useRef, useState } from "react";
import { api, pairedElderId, type Reminder } from "../api/client";
import { listen, speak, speechSupported, speechTag, stopSpeaking } from "../api/voice";

const POLL_MS = 15000;

type Turn = { who: "elder" | "carebridge"; text: string };

export default function ElderView() {
  const elderId = pairedElderId();

  const [reminder, setReminder] = useState<Reminder | null>(null);
  const [photoUrl, setPhotoUrl] = useState<string | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [listening, setListening] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const stopListening = useRef<() => void>(() => {});
  const playedFor = useRef<string | null>(null);
  const lang = "en";

  const refresh = useCallback(async () => {
    if (!elderId) return;
    try {
      const { reminder: next } = await api.activeReminder(elderId);
      setReminder(next);
    } catch {
      setNotice("Cannot reach CareBridge right now.");
    }
  }, [elderId]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  // Load the photo and the caregiver's recording for whichever reminder is up.
  useEffect(() => {
    if (!reminder || !elderId) {
      setPhotoUrl(null);
      setAudioUrl(null);
      return;
    }

    let cancelled = false;
    const created: string[] = [];

    const load = async (path: string | null, set: (v: string) => void) => {
      if (!path) return;
      try {
        const url = await api.mediaObjectUrl(path, elderId);
        if (cancelled) return;
        if (url.startsWith("blob:")) created.push(url);
        set(url);
      } catch {
        // A missing photo or recording is not worth interrupting anyone over.
      }
    };

    load(reminder.photo_url, setPhotoUrl);
    load(reminder.caregiver_audio_url, setAudioUrl);

    return () => {
      cancelled = true;
      created.forEach(URL.revokeObjectURL);
    };
  }, [reminder, elderId]);

  // The caregiver's voice plays once per reminder, not on every poll.
  useEffect(() => {
    if (!audioUrl || !reminder) return;
    if (playedFor.current === reminder.event_id) return;

    playedFor.current = reminder.event_id;
    const audio = new Audio(audioUrl);
    audio.play().catch(() => {
      setNotice("Tap anywhere to hear the message from your family.");
    });
  }, [audioUrl, reminder]);

  const say = useCallback(
    (text: string) => {
      setTurns((previous) => [...previous, { who: "carebridge", text }]);
      speak(text, speechTag(lang));
    },
    [lang],
  );

  const send = useCallback(
    async (message: string) => {
      if (!elderId || !reminder || busy) return;

      setTurns((previous) => [...previous, { who: "elder", text: message }]);
      setBusy(true);
      setNotice(null);

      try {
        const result = await api.chat(elderId, reminder.event_id, message);
        say(result.reply);
        await refresh();
      } catch {
        setNotice("Something went wrong. Please use the buttons below.");
      } finally {
        setBusy(false);
      }
    },
    [elderId, reminder, busy, say, refresh],
  );

  const toggleMic = useCallback(() => {
    if (listening) {
      stopListening.current();
      setListening(false);
      return;
    }

    stopSpeaking();
    setListening(true);
    setNotice(null);

    stopListening.current = listen(
      speechTag(lang),
      (transcript) => {
        setListening(false);
        send(transcript);
      },
      (message) => {
        setListening(false);
        setNotice(message);
      },
    );
  }, [listening, lang, send]);

  const act = useCallback(
    async (action: "taken" | "snooze") => {
      if (!elderId || !reminder || busy) return;
      setBusy(true);

      try {
        if (action === "taken") {
          await api.markTaken(reminder.event_id, elderId);
          say("Thank you. I have recorded it.");
        } else {
          await api.snooze(reminder.event_id, elderId, 10);
          say("Alright, I will remind you again in ten minutes.");
        }
        await refresh();
      } catch {
        setNotice("That did not go through. Please try again.");
      } finally {
        setBusy(false);
      }
    },
    [elderId, reminder, busy, say, refresh],
  );

  if (!elderId) {
    return (
      <main className="elder elder--calm">
        <h1>This device is not set up yet</h1>
        <p className="elder__muted">
          Ask your family to pair it from the CareBridge dashboard.
        </p>
      </main>
    );
  }

  if (!reminder) {
    return (
      <main className="elder elder--calm">
        <div className="elder__tick">✓</div>
        <h1>Nothing to take right now</h1>
        <p className="elder__muted">CareBridge will let you know when it is time.</p>
      </main>
    );
  }

  return (
    <main className="elder">
      <h1 className="elder__title">Medicine time</h1>

      {photoUrl && <img className="elder__photo" src={photoUrl} alt="" />}

      <p className="elder__medicine">{reminder.medication_name}</p>
      <p className="elder__dose">{reminder.dose}</p>
      <p className="elder__food">Take it {reminder.food_instruction_text}</p>

      {turns.length > 0 && (
        <div className="elder__talk">
          {turns.slice(-4).map((turn, index) => (
            <p key={index} className={`elder__turn elder__turn--${turn.who}`}>
              {turn.text}
            </p>
          ))}
        </div>
      )}

      {notice && <p className="elder__notice">{notice}</p>}

      {speechSupported && (
        <button
          type="button"
          className={`elder__mic ${listening ? "elder__mic--on" : ""}`}
          onClick={toggleMic}
          disabled={busy}
        >
          {listening ? "Listening…" : busy ? "One moment…" : "Speak to CareBridge"}
        </button>
      )}

      <button
        type="button"
        className="elder__button elder__button--taken"
        onClick={() => act("taken")}
        disabled={busy}
      >
        I took it
      </button>

      <button
        type="button"
        className="elder__button elder__button--later"
        onClick={() => act("snooze")}
        disabled={busy}
      >
        Remind me later
      </button>
    </main>
  );
}
