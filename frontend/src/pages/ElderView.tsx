import { useCallback, useEffect, useRef, useState } from "react";
import { api, pairedElderIds, type Reminder } from "../api/client";
import { firebaseConfigured, watchElder } from "../api/firebase";
import { listen, speak, speechSupported, speechTag, stopSpeaking } from "../api/voice";
import PairDevice from "./PairDevice";

const POLL_MS = 15000;

type Turn = { who: "elder" | "carebridge"; text: string };

/** Resolving means Firebase has not yet said whether this device is paired. */
type Credential = "resolving" | "paired" | "unpaired";

export default function ElderView() {
  const [elderIds, setElderIds] = useState<string[]>(pairedElderIds());
  const elderId = elderIds[0] ?? null;
  const [credential, setCredential] = useState<Credential>(
    firebaseConfigured ? "resolving" : "paired",
  );

  const [queue, setQueue] = useState<Reminder[]>([]);

  // Whatever is at the front of the queue is the one being asked about. A
  // morning is rarely one tablet, but it is always one decision at a time.
  const reminder = queue[0] ?? null;
  const [photoUrl, setPhotoUrl] = useState<string | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [listening, setListening] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  // Tracked separately from `notice`: a failed poll must never be able to
  // look like "nothing to take", or a due medicine disappears silently.
  const [unreachable, setUnreachable] = useState(false);
  const [everLoaded, setEverLoaded] = useState(false);

  const stopListening = useRef<() => void>(() => {});
  const playedFor = useRef<string | null>(null);
  const lang = "en";

  // Firebase restores a session asynchronously, so polling before this
  // resolves would fetch with no credential and fail on every first load.
  useEffect(
    () =>
      watchElder(elderId ?? "", (user) => {
        if (!firebaseConfigured || !elderId) return;
        setCredential(user ? "paired" : "unpaired");
      }),
    [elderId],
  );

  const ready = credential === "paired" && Boolean(elderId);

  const refresh = useCallback(async () => {
    if (!ready || !elderIds.length) return;

    try {
      // One queue across everyone this phone is set up for, in time order, so
      // a couple sharing a device are not asked to take turns with the screen.
      const perPerson = await Promise.all(
        elderIds.map((id) => api.activeReminder(id)),
      );

      setQueue(perPerson.flatMap((response) => response.reminders ?? []));
      setUnreachable(false);
      setEverLoaded(true);
    } catch {
      setUnreachable(true);
    }
  }, [ready, elderIds]);

  useEffect(() => {
    if (!ready) return;

    refresh();
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [ready, refresh]);

  // Load the photo and the caregiver's recording for whichever reminder is up.
  useEffect(() => {
    if (!reminder) {
      setPhotoUrl(null);
      setAudioUrl(null);
      return;
    }

    let cancelled = false;
    const created: string[] = [];

    const load = async (path: string | null, set: (v: string) => void) => {
      if (!path) return;
      try {
        // Signed with the credential of whoever this reminder belongs to; on
        // a shared phone the first person's token cannot read the second's.
        const url = await api.mediaObjectUrl(path, reminder.elder_id);
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
  }, [reminder]);

  // The caregiver's voice plays once per reminder, not on every poll.
  useEffect(() => {
    if (!audioUrl || !reminder) return;
    if (playedFor.current === reminder.event_id) return;

    playedFor.current = reminder.event_id;
    new Audio(audioUrl).play().catch(() => {
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
      if (!reminder || busy) return;

      setTurns((previous) => [...previous, { who: "elder", text: message }]);
      setBusy(true);
      setNotice(null);

      try {
        const result = await api.chat(
          reminder.elder_id,
          reminder.event_id,
          message,
        );
        say(result.reply);
        await refresh();
      } catch {
        setNotice("Something went wrong. Please use the buttons below.");
      } finally {
        setBusy(false);
      }
    },
    [reminder, busy, say, refresh],
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
      if (!reminder || busy) return;
      setBusy(true);

      try {
        if (action === "taken") {
          await api.markTaken(reminder.event_id, reminder.elder_id);
          say("Thank you. I have recorded it.");
        } else {
          await api.snooze(reminder.event_id, reminder.elder_id, 10);
          say("Alright, I will remind you again in ten minutes.");
        }
        await refresh();
      } catch {
        setNotice("That did not go through. Please try again.");
      } finally {
        setBusy(false);
      }
    },
    [reminder, busy, say, refresh],
  );

  if (credential === "resolving") {
    return (
      <main className="elder elder--calm">
        <p className="elder__muted">One moment…</p>
      </main>
    );
  }

  if (credential === "unpaired" || !elderId) {
    if (firebaseConfigured) {
      return <PairDevice onPaired={() => setElderIds(pairedElderIds())} />;
    }
    return (
      <main className="elder elder--calm">
        <h1>This phone is not set up yet</h1>
        <p className="elder__muted">
          Ask your family to set it up from CareBridge.
        </p>
      </main>
    );
  }

  // Say so plainly rather than implying there is nothing to take.
  if (unreachable && !reminder) {
    return (
      <main className="elder elder--calm">
        <h1>Cannot reach CareBridge</h1>
        <p className="elder__muted">
          {everLoaded
            ? "Please check the internet connection."
            : "Please check the internet connection, then try again."}
        </p>
        <button
          type="button"
          className="elder__button elder__button--later"
          onClick={refresh}
        >
          Try again
        </button>
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

      {/* On a phone set up for one person the name is noise. On a shared one
          it is the difference between the right tablet and the wrong one. */}
      {elderIds.length > 1 && reminder.elder_name && (
        <p className="elder__who">{reminder.elder_name}</p>
      )}

      {queue.length > 1 && (
        <p className="elder__count">
          {queue.length - 1} more after this one
        </p>
      )}

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

      {unreachable && (
        <p className="elder__notice">
          CareBridge is offline. Your answer may not be saved yet.
        </p>
      )}

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
