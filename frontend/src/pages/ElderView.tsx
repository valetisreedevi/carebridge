import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  ApiError,
  pairedElderIds,
  unpairElder,
  type Reminder,
} from "../api/client";
import { firebaseConfigured, watchElder } from "../api/firebase";
import { pushState, registerForPush, type PushState } from "../api/push";
import { playVoice, unlockAudio, whenVoiceEnds } from "../api/audio";
import { listen, speak, speechSupported, speechTag, stopSpeaking } from "../api/voice";
import { t, tFood, tTemplate, type StringKey } from "../i18n";
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
  // Held as a key, not a sentence. On a shared phone the queue can advance to
  // someone who reads a different language, and a notice raised for the last
  // person must not still be sitting there in the wrong one.
  const [notice, setNotice] = useState<StringKey | null>(null);
  // Tracked separately from `notice`: a failed poll must never be able to
  // look like "nothing to take", or a due medicine disappears silently.
  const [unreachable, setUnreachable] = useState(false);
  const [everLoaded, setEverLoaded] = useState(false);
  const [push, setPush] = useState<PushState>(pushState);
  const [askingForPush, setAskingForPush] = useState(false);
  // A recording of her own son saying "take your tablet" is the best thing on
  // this screen. It used to play once, silently fail on most phones, and then
  // ask her to tap the screen — an apology for a browser rule, dressed up as
  // an instruction. It is a feature, so it gets a button, and she can hear it
  // as many times as she likes.
  const [voicePlaying, setVoicePlaying] = useState(false);
  const [heardVoice, setHeardVoice] = useState(false);

  const stopListening = useRef<() => void>(() => {});
  const playedFor = useRef<string | null>(null);

  // The language belongs to whoever this reminder is for, not to the phone.
  // A device shared by a Telugu speaker and an English speaker shows each of
  // them their own, one reminder at a time. Before anything has loaded there
  // is nobody to read yet, so English stands in.
  const lang = reminder?.elder_language ?? "en";

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
      //
      // Settled, not all: a phone keeps ids for everyone it was ever set up
      // for, and one of them losing its session must not blank the screen for
      // the person standing in front of it. With Promise.all a single stale id
      // — an unfinished setup, a household member since removed — took the
      // whole household down and reported it as no internet.
      const perPerson = await Promise.allSettled(
        elderIds.map((id) => api.activeReminder(id)),
      );

      // Nobody answered at all. That is the only case that is really a
      // connection problem; one person failing is that person's problem.
      if (!perPerson.some((result) => result.status === "fulfilled")) {
        setUnreachable(true);
        return;
      }

      // Whoever has no credential left is dropped rather than retried every
      // fifteen seconds forever. Only for the definite refusal — a network
      // blip must never unpair anybody.
      const lost = elderIds.filter((_, index) => {
        const result = perPerson[index];
        return (
          result.status === "rejected" &&
          result.reason instanceof ApiError &&
          result.reason.status === 401
        );
      });

      if (lost.length) {
        lost.forEach(unpairElder);
        setElderIds(pairedElderIds());
      }

      setQueue(
        perPerson.flatMap((result) =>
          result.status === "fulfilled" ? (result.value.reminders ?? []) : [],
        ),
      );
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

  // A registration token is not permanent, so a phone that filed one last
  // week may be addressing nobody today. Re-filed on every load, but only
  // once permission is already granted: nobody should meet a browser dialog
  // they did not ask for while a tablet is due.
  useEffect(() => {
    if (!ready || push !== "on") return;
    registerForPush(elderIds, { prompt: false });
  }, [ready, push, elderIds]);

  // Load the photo and the caregiver's recording for whichever reminder is up.
  useEffect(() => {
    if (!reminder) {
      setPhotoUrl(null);
      setAudioUrl(null);
      return;
    }

    setHeardVoice(false);
    setVoicePlaying(false);

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

  /**
   * The recording of somebody's own family saying "take your tablet".
   *
   * A phone will not make a sound it was not asked for, so the first attempt
   * is refused on most handsets and the screen falls back to asking for a
   * tap. That ask used to go nowhere: nothing listened, so an elder who did
   * exactly as they were told still heard silence. Now any tap on the screen
   * retries it, which is also the gesture that unblocks audio for the rest of
   * the visit.
   */
  const playFamilyVoice = useCallback(async () => {
    if (!audioUrl) return;

    setVoicePlaying(true);
    // The shared element, not a new one: a fresh Audio() is a fresh element
    // that no gesture ever unlocked, which is why the recording used to play
    // only for whoever had just pressed something.
    const played = await playVoice(audioUrl);

    if (played) {
      setHeardVoice(true);
      setNotice((current) => (current === "tapToHear" ? null : current));
    } else {
      setVoicePlaying(false);
    }
  }, [audioUrl]);

  useEffect(() => whenVoiceEnds(() => setVoicePlaying(false)), []);

  // The caregiver's voice plays once per reminder, not on every poll.
  useEffect(() => {
    if (!audioUrl || !reminder) return;
    if (playedFor.current === reminder.event_id) return;

    playedFor.current = reminder.event_id;
    void playFamilyVoice();
  }, [audioUrl, reminder, playFamilyVoice]);

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
        setNotice("somethingWrong");
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
      (failure) => {
        setListening(false);
        setNotice(failure);
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
          say(t("recordedThanks", lang));
        } else {
          await api.snooze(reminder.event_id, reminder.elder_id, 10);
          say(t("willRemindInTen", lang));
        }
        await refresh();
      } catch {
        setNotice("didNotGoThrough");
      } finally {
        setBusy(false);
      }
    },
    [reminder, busy, say, refresh, lang],
  );

  const askForNotifications = useCallback(async () => {
    setAskingForPush(true);
    const granted = await registerForPush(elderIds, { prompt: true });
    setAskingForPush(false);
    setPush(granted ? "on" : pushState());
  }, [elderIds]);

  // Everything above the first loaded reminder is in English by necessity:
  // until the phone knows who it belongs to there is no language to read.
  if (credential === "resolving") {
    return (
      <main className="elder elder--calm">
        <p className="elder__muted">{t("oneMoment", lang)}</p>
      </main>
    );
  }

  if (credential === "unpaired" || !elderId) {
    if (firebaseConfigured) {
      return <PairDevice onPaired={() => setElderIds(pairedElderIds())} />;
    }
    return (
      <main className="elder elder--calm">
        <h1>{t("notSetUp", lang)}</h1>
        <p className="elder__muted">{t("askFamilyToSetUp", lang)}</p>
      </main>
    );
  }

  // Say so plainly rather than implying there is nothing to take.
  if (unreachable && !reminder) {
    return (
      <main className="elder elder--calm">
        <h1>{t("cannotReach", lang)}</h1>
        <p className="elder__muted">
          {t(everLoaded ? "checkInternet" : "checkInternetRetry", lang)}
        </p>
        <button
          type="button"
          className="elder__button elder__button--later"
          onClick={refresh}
        >
          {t("tryAgain", lang)}
        </button>
      </main>
    );
  }

  if (!reminder) {
    return (
      <main className="elder elder--calm">
        <div className="elder__tick">✓</div>
        <h1>{t("nothingToTake", lang)}</h1>
        <p className="elder__muted">
          {t(push === "on" ? "willLetYouKnow" : "keepPageOpen", lang)}
        </p>

        {/* Offered here, on the quiet screen, because asking is a setup step
            and this is where whoever sets the phone up will be standing. */}
        {push === "off" && (
          <button
            type="button"
            className="elder__button elder__button--later"
            onClick={askForNotifications}
            disabled={askingForPush}
          >
            {t(askingForPush ? "oneMoment" : "letPhoneRing", lang)}
          </button>
        )}

        {push === "blocked" && (
          <p className="elder__muted">{t("notificationsBlocked", lang)}</p>
        )}
      </main>
    );
  }

  return (
    // The tap the notice asks for. On the whole screen rather than a button,
    // because "tap anywhere" has to mean anywhere to somebody holding the
    // phone at arm's length. Harmless when there is nothing waiting to play.
    <main
      className="elder"
      onClick={() => {
        unlockAudio();
        void playFamilyVoice();
      }}
    >
      <h1 className="elder__title">{t("medicineTime", lang)}</h1>

      {/* On a phone set up for one person the name is noise. On a shared one
          it is the difference between the right tablet and the wrong one. */}
      {elderIds.length > 1 && reminder.elder_name && (
        <p className="elder__who">{reminder.elder_name}</p>
      )}

      {queue.length > 1 && (
        <p className="elder__count">
          {tTemplate("moreAfterThis", lang, { count: queue.length - 1 })}
        </p>
      )}

      {photoUrl && <img className="elder__photo" src={photoUrl} alt="" />}

      {/* Offered whenever a recording exists, whether or not it managed to
          play on its own. A phone that refused to autoplay and a phone that
          played it while she was in the next room look the same to her. */}
      {audioUrl && (
        <button
          type="button"
          className={`elder__voice ${voicePlaying ? "elder__voice--on" : ""}`}
          onClick={(event) => {
            event.stopPropagation();
            void playFamilyVoice();
          }}
          disabled={voicePlaying}
        >
          <span className="elder__voiceMark" aria-hidden="true">
            ▶
          </span>
          {t(
            voicePlaying
              ? "hearFamilyPlaying"
              : heardVoice
                ? "hearFamilyAgain"
                : "hearFamily",
            lang,
          )}
        </button>
      )}

      <p className="elder__medicine">{reminder.medication_name}</p>
      <p className="elder__dose">{reminder.dose}</p>
      <p className="elder__food">
        {tTemplate("takeIt", lang, {
          food: tFood(reminder.food_instruction, lang),
        })}
      </p>

      {turns.length > 0 && (
        <div className="elder__talk">
          {turns.slice(-4).map((turn, index) => (
            <p key={index} className={`elder__turn elder__turn--${turn.who}`}>
              {turn.text}
            </p>
          ))}
        </div>
      )}

      {notice && <p className="elder__notice">{t(notice, lang)}</p>}

      {unreachable && (
        <p className="elder__notice">{t("offlineAnswer", lang)}</p>
      )}

      {speechSupported && (
        <button
          type="button"
          className={`elder__mic ${listening ? "elder__mic--on" : ""}`}
          onClick={toggleMic}
          disabled={busy}
        >
          {t(
            listening ? "listening" : busy ? "oneMoment" : "speakToCareBridge",
            lang,
          )}
        </button>
      )}

      <button
        type="button"
        className="elder__button elder__button--taken"
        onClick={() => act("taken")}
        disabled={busy}
      >
        {t("iTookIt", lang)}
      </button>

      <button
        type="button"
        className="elder__button elder__button--later"
        onClick={() => act("snooze")}
        disabled={busy}
      >
        {t("remindMeLater", lang)}
      </button>
    </main>
  );
}
