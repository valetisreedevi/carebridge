import { useCallback, useEffect, useState } from "react";
import { api, pairElder, type Alert, type DayItem, type Elder } from "../api/client";
import MedicationForm from "../components/MedicationForm";

const POLL_MS = 10000;

const STATUS_LABEL: Record<string, string> = {
  TAKEN: "Taken",
  DECLINED: "Declined",
  ESCALATED: "Needs attention",
  REMINDER_SENT: "Waiting for a reply",
  SNOOZED: "Snoozed",
  PENDING: "Reminder due",
  UPCOMING: "Upcoming",
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

export default function Dashboard() {
  const [elders, setElders] = useState<Elder[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [items, setItems] = useState<DayItem[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [adding, setAdding] = useState(false);
  const [newElderName, setNewElderName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const loadElders = useCallback(async () => {
    try {
      const list = await api.listElders();
      setElders(list);
      setSelected((current) => current ?? list[0]?.id ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load");
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

  const needsAttention = items.filter(
    (i) => i.status === "ESCALATED" || i.status === "DECLINED",
  );

  const elder = elders.find((e) => e.id === selected);

  return (
    <div className="dash">
      <header className="dash__header">
        <h1>CareBridge</h1>
        <p className="dash__sub">
          {needsAttention.length > 0
            ? `${needsAttention.length} thing${
                needsAttention.length > 1 ? "s" : ""
              } needs your attention`
            : "Everything is on track today"}
        </p>
      </header>

      {error && (
        <p className="dash__error" onClick={() => setError(null)}>
          {error}
        </p>
      )}

      <section className="dash__elders">
        {elders.map((e) => (
          <button
            key={e.id}
            type="button"
            className={`chip ${e.id === selected ? "chip--on" : ""}`}
            onClick={() => setSelected(e.id)}
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

      {elder && (
        <>
          <section className="card">
            <div className="card__head">
              <h2>Today</h2>
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

            {items.length === 0 && !adding && (
              <p className="muted">No medications set up yet.</p>
            )}

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
                        ? ` · ${item.food_instruction.toLowerCase().replace(/_/g, " ")}`
                        : ""}
                    </small>
                  </span>

                  <span className="schedule__status">
                    {STATUS_LABEL[item.status] ?? item.status}
                    {item.attempt > 0 && item.status !== "TAKEN" && (
                      <small>
                        {" "}
                        · reminder {item.attempt} of {item.max_attempts}
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
          </section>

          <section className="card">
            <div className="card__head">
              <h2>Alerts</h2>
            </div>

            {alerts.length === 0 ? (
              <p className="muted">Nothing needed your attention.</p>
            ) : (
              <ul className="alerts">
                {alerts.map((alert) => (
                  <li key={alert.id} className={`alerts__item alerts__item--${alert.reason.toLowerCase()}`}>
                    <span>{alert.message}</span>
                    <small>{new Date(alert.created_at).toLocaleString()}</small>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="card">
            <div className="card__head">
              <h2>Elder device</h2>
            </div>
            <p className="muted">
              Open CareBridge on {elder.name}'s phone and pair it to this person.
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
          </section>
        </>
      )}
    </div>
  );
}
