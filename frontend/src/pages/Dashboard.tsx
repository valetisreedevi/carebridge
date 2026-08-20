import { useCallback, useEffect, useState } from "react";
import { api, pairElder, type Alert, type DayItem, type Elder } from "../api/client";
import { firebaseConfigured } from "../api/firebase";
import MedicationForm from "../components/MedicationForm";

const POLL_MS = 10000;

const STATUS_LABEL: Record<string, string> = {
  TAKEN: "Taken",
  DECLINED: "Declined",
  ESCALATED: "Needs you",
  REMINDER_SENT: "Waiting for a reply",
  SNOOZED: "Snoozed",
  PENDING: "Reminder due",
  UPCOMING: "Later today",
  CANCELLED: "Cancelled",
};

const STATUS_TONE: Record<string, string> = {
  TAKEN: "good",
  DECLINED: "bad",
  ESCALATED: "bad",
  REMINDER_SENT: "waiting",
  SNOOZED: "waiting",
  PENDING: "waiting",
  UPCOMING: "idle",
  CANCELLED: "idle",
};

const FOOD_LABEL: Record<string, string> = {
  BEFORE_FOOD: "before food",
  AFTER_FOOD: "after food",
  WITH_FOOD: "with food",
  ANY_TIME: "any time",
};

/** The single line a worried family member actually reads. */
function verdict(items: DayItem[]): { text: string; alert: boolean } {
  const needsYou = items.filter(
    (i) => i.status === "ESCALATED" || i.status === "DECLINED",
  );
  if (needsYou.length) {
    const names = [...new Set(needsYou.map((i) => i.medication_name))];
    return {
      text: `${names.join(" and ")} needs your attention`,
      alert: true,
    };
  }

  const waiting = items.filter(
    (i) => i.status === "REMINDER_SENT" || i.status === "SNOOZED",
  );
  if (waiting.length) {
    return { text: "Waiting for a reply — no action needed yet", alert: false };
  }

  const taken = items.filter((i) => i.status === "TAKEN").length;
  const upcoming = items.filter((i) => i.status === "UPCOMING").length;

  if (!items.length) return { text: "No medications set up yet", alert: false };
  if (taken && !upcoming) return { text: "All done for today", alert: false };
  if (taken) {
    return {
      text: `${taken} taken, ${upcoming} still to come`,
      alert: false,
    };
  }
  return { text: "Everything is on track", alert: false };
}

export default function Dashboard() {
  const [elders, setElders] = useState<Elder[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [items, setItems] = useState<DayItem[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [adding, setAdding] = useState(false);
  const [newElderName, setNewElderName] = useState("");
  const [pairingCode, setPairingCode] = useState<string | null>(null);
  const [pairingBusy, setPairingBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const loadElders = useCallback(async () => {
    try {
      const list = await api.listElders();
      setElders(list);
      setSelected((current) => current ?? list[0]?.id ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load");
    } finally {
      setLoaded(true);
    }
  }, []);

  const loadDay = useCallback(async () => {
    if (!selected) return;
    try {
      const [day, alertList] = await Promise.all([
        api.today(selected),
        api.alerts(),
      ]);
      setItems(day.items);
      setAlerts(alertList);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load");
    }
  }, [selected]);

  useEffect(() => {
    loadElders();
  }, [loadElders]);

  useEffect(() => {
    loadDay();
    const timer = setInterval(loadDay, POLL_MS);
    return () => clearInterval(timer);
  }, [loadDay]);

  // Switching person should not leave the previous person's code on screen.
  useEffect(() => setPairingCode(null), [selected]);

  const addElder = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!newElderName.trim()) return;

    try {
      const elder = await api.createElder({
        name: newElderName.trim(),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        preferred_language: "en",
      });
      setNewElderName("");
      await loadElders();
      setSelected(elder.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not add");
    }
  };

  const trigger = async (medicationId: string) => {
    try {
      await api.triggerReminder(medicationId);
      await loadDay();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not send the reminder");
    }
  };

  const getCode = async (elderId: string) => {
    setPairingBusy(true);
    try {
      const result = await api.pairingToken(elderId);
      setPairingCode(result.pairing_token);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not make a code");
    } finally {
      setPairingBusy(false);
    }
  };

  const elder = elders.find((e) => e.id === selected);
  const status = verdict(items);

  return (
    <div className="dash">
      <header className="dash__header">
        <h1>Today</h1>
        <p className={`dash__verdict ${status.alert ? "dash__verdict--alert" : ""}`}>
          {status.text}
        </p>
      </header>

      {error && (
        <p className="dash__error" onClick={() => setError(null)} role="alert">
          {error} — tap to dismiss
        </p>
      )}

      <section className="dash__elders">
        {elders.map((e) => (
          <button
            key={e.id}
            type="button"
            className={`chip ${e.id === selected ? "chip--on" : ""}`}
            onClick={() => setSelected(e.id)}
            aria-pressed={e.id === selected}
          >
            {e.name}
          </button>
        ))}

        <form className="dash__addElder" onSubmit={addElder}>
          <input
            value={newElderName}
            onChange={(event) => setNewElderName(event.target.value)}
            placeholder="Add someone"
            aria-label="Name of the person you care for"
          />
          <button type="submit">Add</button>
        </form>
      </section>

      {loaded && !elder && (
        <section className="card">
          <p className="empty">
            Add the person you look after to get started.
          </p>
        </section>
      )}

      {elder && (
        <>
          <section className="card">
            <div className="card__head">
              <h2>{elder.name}'s medications</h2>
              <button type="button" onClick={() => setAdding((v) => !v)}>
                {adding ? "Cancel" : "Add medication"}
              </button>
            </div>

            {adding && (
              <MedicationForm
                elderId={elder.id}
                onSaved={() => {
                  setAdding(false);
                  loadDay();
                }}
              />
            )}

            {items.length === 0 && !adding ? (
              <p className="empty">
                Nothing scheduled yet. Add a medication and CareBridge will take
                it from there.
              </p>
            ) : (
              <ul className="schedule">
                {items.map((item) => (
                  <li
                    key={`${item.medication_id}-${item.local_time}`}
                    className={`schedule__row schedule__row--${
                      STATUS_TONE[item.status] ?? "idle"
                    }`}
                  >
                    <span className="schedule__time">{item.local_time}</span>

                    <span className="schedule__what">
                      <strong>{item.medication_name}</strong>
                      <small>
                        {item.dose}
                        {item.food_instruction
                          ? ` · ${
                              FOOD_LABEL[item.food_instruction] ??
                              item.food_instruction.toLowerCase()
                            }`
                          : ""}
                      </small>
                    </span>

                    <span className="schedule__status">
                      {STATUS_LABEL[item.status] ?? item.status}
                      {item.attempt > 0 && item.status !== "TAKEN" && (
                        <small>
                          reminder {item.attempt} of {item.max_attempts}
                        </small>
                      )}
                    </span>

                    <button
                      type="button"
                      className="schedule__now"
                      onClick={() => trigger(item.medication_id)}
                      title="Send this reminder now instead of waiting"
                    >
                      Remind now
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="card">
            <div className="card__head">
              <h2>Alerts</h2>
            </div>

            {alerts.length === 0 ? (
              <p className="empty">
                Nothing has needed your attention. CareBridge only writes here
                when something does.
              </p>
            ) : (
              <ul className="alerts">
                {alerts.map((alert) => (
                  <li
                    key={alert.id}
                    className={`alerts__item alerts__item--${alert.reason.toLowerCase()}`}
                  >
                    <span>{alert.message}</span>
                    <small>{new Date(alert.created_at).toLocaleString()}</small>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="card">
            <div className="card__head">
              <h2>{elder.name}'s phone</h2>
            </div>

            {firebaseConfigured ? (
              <>
                <ol className="pair__steps">
                  <li>Open this website on {elder.name}'s phone.</li>
                  <li>Tap <strong>Elder device</strong> at the top.</li>
                  <li>Paste the code below and tap Set up.</li>
                </ol>

                <button
                  type="button"
                  className="btn-primary"
                  onClick={() => getCode(elder.id)}
                  disabled={pairingBusy}
                >
                  {pairingBusy
                    ? "Making a code…"
                    : pairingCode
                      ? "Make a new code"
                      : "Get a pairing code"}
                </button>

                {pairingCode && (
                  <>
                    <textarea
                      className="pair__code"
                      readOnly
                      rows={4}
                      value={pairingCode}
                      onFocus={(e) => e.currentTarget.select()}
                      aria-label={`Pairing code for ${elder.name}`}
                    />
                    <p className="muted">
                      One code, one phone. It expires in an hour, so make a new
                      one if you do not use it now.
                    </p>
                  </>
                )}
              </>
            ) : (
              <>
                <p className="muted">
                  Development mode: pair this browser instead of a phone.
                </p>
                <button
                  type="button"
                  onClick={() => {
                    pairElder(elder.id);
                    window.location.href = "/elder";
                  }}
                >
                  Pair this browser as {elder.name}
                </button>
              </>
            )}
          </section>
        </>
      )}
    </div>
  );
}
