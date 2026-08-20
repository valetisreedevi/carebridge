import { useState } from "react";
import { pairElder } from "../api/client";
import { pairElderDevice } from "../api/firebase";

/**
 * Shown on the elder's phone once, during setup. After this the device holds
 * its own credential and the elder never sees a form again.
 */
export default function PairDevice({ onPaired }: { onPaired: () => void }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);

    try {
      const elderId = await pairElderDevice(code);
      pairElder(elderId);
      onPaired();
    } catch (e) {
      setError(
        e instanceof Error && e.message.includes("pairing code")
          ? e.message
          : "That code did not work. Ask your family for a new one.",
      );
      setBusy(false);
    }
  };

  return (
    <main className="elder elder--calm">
      <h1>Set up this phone</h1>
      <p className="elder__muted">
        Paste the code your family gave you.
      </p>

      <form onSubmit={submit}>
        <textarea
          className="pair__code"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="Paste the code here"
          rows={4}
          required
          aria-label="Pairing code"
        />

        {error && <p className="elder__notice">{error}</p>}

        <button
          type="submit"
          className="elder__button elder__button--taken"
          disabled={busy || code.trim().length < 20}
        >
          {busy ? "Setting up…" : "Set up"}
        </button>
      </form>
    </main>
  );
}
