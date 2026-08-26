import { useEffect, useRef, useState } from "react";
import { pairElder } from "../api/client";
import { pairElderDevice } from "../api/firebase";
import { unlockAudio } from "../api/audio";

/**
 * Shown on the elder's phone once, during setup. After this the device holds
 * its own credential and the elder never sees a form again.
 *
 * The field is small and the type is large because the person filling it in is
 * the person the reminders are for, typing a code somebody read to them.
 */
export default function PairDevice({ onPaired }: { onPaired: () => void }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [paired, setPaired] = useState<string | null>(null);

  // Held in a ref because the parent passes an inline arrow: depending on it
  // directly would restart the timer on every re-render, and it would never
  // fire. Written in an effect rather than during render, which is the only
  // safe place to touch one.
  const done = useRef(onPaired);
  useEffect(() => {
    done.current = onPaired;
  });

  useEffect(() => {
    if (!paired) return;

    // Reading "this phone is set up" as the end of the job is the correct
    // reading. Requiring a tap after it left the device sitting on a
    // confirmation screen, not polling, with nothing to say anything was
    // wrong.
    const timer = setTimeout(() => done.current(), 2500);
    return () => clearTimeout(timer);
  }, [paired]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();

    // The one tap that matters. Setting a phone up is done by a family
    // member, in the room, pressing a button — so this is where the browser's
    // "no sound without a gesture" rule gets satisfied, once, on their
    // behalf. Every reminder after this plays on its own, and the person the
    // reminders are for never has to press anything to hear her family.
    unlockAudio();

    setBusy(true);
    setError(null);

    try {
      const { elderId, elderName } = await pairElderDevice(code);
      pairElder(elderId);

      // Their own name, before anything else happens. A code typed one
      // character out lands on a real person, and this is where that shows up
      // rather than at the next dose.
      if (elderName) {
        setPaired(elderName);
        return;
      }

      onPaired();
    } catch (e) {
      setError(
        e instanceof Error && e.message.includes("pairing code")
          ? "That code did not work. Ask your family for a new one."
          : "That code did not work. Ask your family for a new one.",
      );
      setBusy(false);
    }
  };

  if (paired) {
    return (
      <main className="elder elder--calm">
        <h1>This phone is set up for {paired}</h1>
        <p className="elder__muted">
          Reminders will arrive here from now on. There is nothing else to do.
        </p>
        <button
          type="button"
          className="elder__button elder__button--taken"
          onClick={onPaired}
        >
          Continue
        </button>
      </main>
    );
  }

  return (
    <main className="elder elder--calm">
      <h1>Set up this phone</h1>
      <p className="elder__muted">
        Type the code your family gave you.
      </p>

      <form onSubmit={submit}>
        <input
          className="pair__entry"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="ABCDE-FGHJK"
          autoCapitalize="characters"
          autoCorrect="off"
          spellCheck={false}
          required
          aria-label="Pairing code"
        />

        {error && <p className="elder__notice">{error}</p>}

        <button
          type="submit"
          className="elder__button elder__button--taken"
          disabled={busy || code.trim().length < 6}
        >
          {busy ? "Setting up…" : "Set up"}
        </button>
      </form>
    </main>
  );
}
