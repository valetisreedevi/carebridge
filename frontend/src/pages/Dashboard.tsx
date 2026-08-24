import { useCallback, useEffect, useState } from "react";
import {
  api,
  pairElder,
  type Alert,
  type DayItem,
  type CareTeamMember,
  type Elder,
  type HistoryDay,
  type Device,
  type Medication,
} from "../api/client";
import { firebaseConfigured } from "../api/firebase";
import MedicationForm from "../components/MedicationForm";
import { clockTime, sinceWhen, timeIn } from "../format";

const POLL_MS = 10000;

const STATUS_LABEL: Record<string, string> = {
  TAKEN: "Taken",
  DECLINED: "Declined",
  ESCALATED: "Needs you",
  REMINDER_SENT: "Waiting for a reply",
  SNOOZED: "Snoozed",
  PENDING: "Reminder due",
  UPCOMING: "Later today",
  MISSED: "Missed — no reminder sent",
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
  MISSED: "bad",
  CANCELLED: "idle",
};

/** The browser knows every IANA zone; a caregiver only needs a short list. */
const COMMON_ZONES = [
  "Asia/Kolkata",
  "Asia/Dubai",
  "Asia/Singapore",
  "Australia/Sydney",
  "Europe/London",
  "Europe/Berlin",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "UTC",
];

function zoneChoices(current: string): string[] {
  const here = Intl.DateTimeFormat().resolvedOptions().timeZone;
  return [...new Set([current, here, ...COMMON_ZONES].filter(Boolean))];
}

const FOOD_LABEL: Record<string, string> = {
  BEFORE_FOOD: "before food",
  AFTER_FOOD: "after food",
  WITH_FOOD: "with food",
  ANY_TIME: "any time",
};

/** A row where the useful action is recording the dose, not chasing it. */
/** No reminder physically went anywhere, whatever the attempt count says. */
function wentNowhere(item: DayItem): boolean {
  return (
    item.reached_a_phone === false &&
    item.status !== "UPCOMING" &&
    item.status !== "TAKEN" &&
    item.status !== "CANCELLED"
  );
}

function needsAttention(item: DayItem): boolean {
  return (
    item.status === "ESCALATED" ||
    item.status === "MISSED" ||
    item.status === "REMINDER_SENT" ||
    item.status === "SNOOZED"
  );
}

/** Rows are keyed by medicine and time; one medicine can appear twice a day. */
function rowKey(item: DayItem): string {
  return `${item.medication_id}-${item.local_time}`;
}

/** The single line a worried family member actually reads. */
function verdict(items: DayItem[]): { text: string; alert: boolean } {
  // Acknowledged means the caregiver has already taken it on. Keeping it in
  // the headline is how a dashboard trains someone to stop reading it.
  const needsYou = items.filter(
    (i) =>
      (i.status === "ESCALATED" || i.status === "DECLINED") &&
      !i.acknowledged_at,
  );
  if (needsYou.length) {
    const names = [...new Set(needsYou.map((i) => i.medication_name))];
    return {
      text: `${names.join(" and ")} needs your attention`,
      alert: true,
    };
  }

  // A time that came and went without a reminder is the caregiver's problem to
  // know about, so it outranks anything still in flight.
  const missed = items.filter((i) => i.status === "MISSED");
  if (missed.length) {
    const names = [...new Set(missed.map((i) => i.medication_name))];
    return {
      text: `No reminder went out for ${names.join(" and ")}`,
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

/** Where the day stands, under the one line that says how it is going. */
function Progress({ items }: { items: DayItem[] }) {
  const taken = items.filter((i) => i.status === "TAKEN").length;
  const missed = items.filter(
    (i) => (i.status === "ESCALATED" || i.status === "MISSED") && !i.acknowledged_at,
  ).length;
  const waiting = items.filter(
    (i) => i.status === "REMINDER_SENT" || i.status === "SNOOZED",
  ).length;

  return (
    <div className="progress">
      <div
        className="progress__bar"
        role="img"
        aria-label={`${taken} of ${items.length} taken`}
      >
        <span
          className="progress__fill"
          style={{ width: `${(taken / items.length) * 100}%` }}
        />
      </div>
      <p className="progress__counts">
        <strong>
          {taken} of {items.length}
        </strong>{" "}
        taken
        {waiting > 0 && <> · {waiting} waiting</>}
        {missed > 0 && <span className="progress__missed"> · {missed} missed</span>}
      </p>
    </div>
  );
}

/** CB-08: the week behind today, which is the question families carry. */
function History({ days }: { days: HistoryDay[] }) {
  const weekday = (date: string) =>
    new Date(`${date}T12:00:00`).toLocaleDateString(undefined, {
      weekday: "narrow",
    });

  return (
    <section className="card">
      <div className="card__head">
        <h2>This week</h2>
      </div>

      <ul className="week">
        {days.map((day) => {
          const tone =
            day.total === 0
              ? "empty"
              : day.missed > 0
                ? "bad"
                : day.taken === day.total
                  ? "good"
                  : "part";

          return (
            <li key={day.date} className={`week__day week__day--${tone}`}>
              <span className="week__letter">{weekday(day.date)}</span>
              <span className="week__count">
                {day.total === 0 ? "–" : `${day.taken}/${day.total}`}
              </span>
            </li>
          );
        })}
      </ul>

      <p className="card__hint week__legend">
        Doses recorded as taken, out of those scheduled. A day with nothing
        scheduled shows a dash.
      </p>
    </section>
  );
}

export default function Dashboard() {
  const [elders, setElders] = useState<Elder[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [items, setItems] = useState<DayItem[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [adding, setAdding] = useState(false);
  const [medications, setMedications] = useState<Medication[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [team, setTeam] = useState<CareTeamMember[]>([]);
  const [inviteCode, setInviteCode] = useState<{
    elderId: string;
    code: string;
  } | null>(null);
  const [joinCode, setJoinCode] = useState("");
  const [joinNotice, setJoinNotice] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryDay[]>([]);
  const [phones, setPhones] = useState<Device[] | null>(null);
  const [confirmingRemind, setConfirmingRemind] = useState<string | null>(null);
  const [confirmingSignOut, setConfirmingSignOut] = useState<string | null>(null);
  const [signOutResult, setSignOutResult] = useState<string | null>(null);
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [newElderName, setNewElderName] = useState("");
  const [pairingCode, setPairingCode] = useState<{
    elderId: string;
    code: string;
  } | null>(null);
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
      const [day, alertList, meds, past, devices] = await Promise.all([
        api.today(selected),
        api.alerts(),
        api.listMedications(selected),
        api.history(selected, 7),
        api.listDevices(selected),
      ]);
      setItems(day.items);
      setAlerts(alertList);
      setMedications(meds.filter((m) => m.active !== false));
      setHistory(past.days);
      setPhones(devices);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load");
    }
  }, [selected]);

  const loadTeam = useCallback(async () => {
    if (!selected) return;
    try {
      setTeam(await api.listCaregivers(selected));
    } catch {
      // The care team is supporting detail; the day matters more.
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

  useEffect(() => {
    loadTeam();
  }, [loadTeam]);

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

  const trigger = async (medicationId: string, localTime: string) => {
    // Two steps rather than a dialog. This lights up a phone, plays a recorded
    // voice and can wake somebody; Remove asks before it acts and this used
    // not to, which had the confirmation on the reversible action only.
    //
    // Armed per row, not per medicine: one tablet taken morning and night is
    // two rows, and keying on the medicine armed both of them at once.
    const row = `${medicationId}-${localTime}`;
    if (confirmingRemind !== row) {
      setConfirmingRemind(row);
      return;
    }

    setConfirmingRemind(null);
    setOpenMenu(null);
    try {
      await api.triggerReminder(medicationId, localTime);
      await loadDay();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not send the reminder");
    }
  };

  const signOutDevices = async (elderId: string) => {
    // Same two-step as Remind now. This one cannot be undone from here: every
    // phone has to be paired again with a fresh code.
    if (confirmingSignOut !== elderId) {
      setConfirmingSignOut(elderId);
      return;
    }

    setConfirmingSignOut(null);
    try {
      const result = await api.signOutDevices(elderId);
      setSignOutResult(
        result.devices_signed_out === 0
          ? `${result.elder_name} had no phones paired.`
          : `Signed out ${result.devices_signed_out} ${
              result.devices_signed_out === 1 ? "phone" : "phones"
            }. Pair again with a new code.`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not sign the phones out");
    }
  };

  const acknowledge = async (eventId: string) => {
    try {
      await api.acknowledgeAlert(eventId);
      await loadDay();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not mark it handled");
    }
  };

  const markTaken = async (medicationId: string, localTime: string) => {
    setOpenMenu(null);
    try {
      await api.markTakenByCaregiver(medicationId, localTime);
      await loadDay();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not record it");
    }
  };

  const removeMedication = async (medicationId: string) => {
    try {
      await api.deleteMedication(medicationId);
      setRemoving(null);
      await loadDay();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not remove it");
    }
  };

  const invite = async () => {
    if (!selected) return;
    try {
      const created = await api.createInvite(selected);
      setInviteCode({ elderId: selected, code: created.code });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not make an invite");
    }
  };

  const join = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!joinCode.trim()) return;

    setJoinNotice(null);
    try {
      const joined = await api.acceptInvite(joinCode.trim());
      setJoinCode("");
      setJoinNotice(`You now share ${joined.elder_name}'s care.`);
      await loadElders();
      setSelected(joined.elder_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "That code did not work");
    }
  };

  const removeCaregiver = async (memberId: string) => {
    if (!selected) return;
    try {
      await api.removeCaregiver(selected, memberId);
      await loadTeam();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not remove them");
    }
  };

  const changeTimezone = async (zone: string) => {
    if (!selected) return;
    try {
      await api.updateElder(selected, { timezone: zone });
      await loadElders();
      await loadDay();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not change the timezone");
    }
  };

  const getCode = async (elderId: string) => {
    setPairingBusy(true);
    try {
      const result = await api.pairingCode(elderId);
      setPairingCode({ elderId, code: result.code });
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

        {items.length > 0 && <Progress items={items} />}

        {/* Said before any dose is due, not after one has quietly failed.
            With no phone set up nothing can reach her, and every reminder is
            recorded as sent to nobody. */}
        {phones?.length === 0 && elder && (
          <p className="dash__nophone">
            No phone is set up for {elder.name}, so reminders cannot reach her.
            Get a pairing code below and enter it on her phone.
          </p>
        )}
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

        <form className="dash__addElder" onSubmit={join}>
          <input
            value={joinCode}
            onChange={(event) => setJoinCode(event.target.value)}
            placeholder="Have an invite code?"
            aria-label="Invite code from another family member"
          />
          <button type="submit">Join</button>
        </form>
      </section>

      {joinNotice && (
        <p className="dash__notice" role="status">
          {joinNotice}
        </p>
      )}

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
              <div className="card__headActions">
                <button
                  type="button"
                  className="btn-quiet"
                  onClick={() => setShowSettings((v) => !v)}
                >
                  {showSettings ? "Done" : "Settings"}
                </button>
                <button
                  type="button"
                  className="btn-primary btn-primary--sm"
                  onClick={() => setAdding((v) => !v)}
                >
                  {adding ? "Cancel" : "Add medication"}
                </button>
              </div>
            </div>

            {showSettings && (
              <div className="settings">
                <label>
                  Timezone for {elder.name}
                  <select
                    value={elder.timezone}
                    onChange={(event) => changeTimezone(event.target.value)}
                  >
                    {zoneChoices(elder.timezone).map((zone) => (
                      <option key={zone} value={zone}>
                        {zone.replace(/_/g, " ")} — {timeIn(zone)}
                      </option>
                    ))}
                  </select>
                </label>
                <p className="settings__note">
                  Reminder times are read in {elder.name}'s timezone, not yours.
                  It is {timeIn(elder.timezone)} there now.
                </p>

                <div className="team">
                  <h3>Who gets told</h3>
                  <p className="settings__note">
                    Everyone here is alerted when {elder.name} misses a dose.
                  </p>

                  <ul className="team__list">
                    {team.map((member) => (
                      <li key={member.caregiver_id}>
                        <span>
                          {member.email ?? member.name ?? member.caregiver_id}
                          {member.is_you && <small> · you</small>}
                        </span>
                        {!member.is_you && team.length > 1 && (
                          <button
                            type="button"
                            className="btn-quiet btn-quiet--danger"
                            onClick={() => removeCaregiver(member.caregiver_id)}
                          >
                            Remove
                          </button>
                        )}
                      </li>
                    ))}
                  </ul>

                  {inviteCode?.elderId === elder.id ? (
                    <div className="team__code">
                      <p className="settings__note">
                        Send this to the family member who should also be told.
                        It works once, and only for the next three days.
                      </p>
                      <code>{inviteCode.code}</code>
                    </div>
                  ) : (
                    <button type="button" className="btn-quiet" onClick={invite}>
                      Invite someone
                    </button>
                  )}
                </div>
              </div>
            )}

            {adding && (
              <MedicationForm
                elderId={elder.id}
                elderName={elder.name}
                elderTimezone={elder.timezone}
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
                      item.acknowledged_at
                        ? "idle"
                        : (STATUS_TONE[item.status] ?? "idle")
                    }`}
                  >
                    <span className="schedule__time">{clockTime(item.local_time)}</span>

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
                      {item.acknowledged_at
                        ? "You said you have it"
                        : wentNowhere(item)
                          ? "Not reminded — no phone set up"
                          : (STATUS_LABEL[item.status] ?? item.status)}
                      {/* The attempt count is a count of tries, not of doses
                          she declined to answer. Showing "2 of 2" beside a
                          household with no phone reads as her ignoring it. */}
                      {item.attempt > 0 &&
                        item.status !== "TAKEN" &&
                        (wentNowhere(item) ? (
                          <small>nothing was delivered</small>
                        ) : (
                          <small>
                            reminder {item.attempt} of {item.max_attempts}
                          </small>
                        ))}
                    </span>

                    {/* One action visible, ranked by what this row needs, and
                        the rest behind a menu. Five medicines used to mean
                        fifteen controls competing with the information. */}
                    <span className="schedule__actions">
                      {needsAttention(item) ? (
                        <button
                          type="button"
                          className="btn-primary btn-primary--sm"
                          onClick={() =>
                            markTaken(item.medication_id, item.local_time)
                          }
                          title="Record it, on your word rather than theirs"
                        >
                          They took it
                        </button>
                      ) : (
                        <button
                          type="button"
                          className={
                            confirmingRemind === rowKey(item)
                              ? "btn-danger"
                              : "btn-quiet"
                          }
                          onClick={() => trigger(item.medication_id, item.local_time)}
                          onBlur={() => setConfirmingRemind(null)}
                          title="Send this reminder now instead of waiting"
                        >
                          {confirmingRemind === rowKey(item)
                            ? "Send it now?"
                            : "Remind now"}
                        </button>
                      )}

                      <span className="rowmenu">
                        <button
                          type="button"
                          className="btn-quiet rowmenu__toggle"
                          aria-haspopup="true"
                          aria-expanded={openMenu === rowKey(item)}
                          aria-label={`More for ${item.medication_name}`}
                          onClick={() =>
                            setOpenMenu(
                              openMenu === rowKey(item) ? null : rowKey(item),
                            )
                          }
                        >
                          ⋯
                        </button>

                        {openMenu === rowKey(item) && (
                          <span className="rowmenu__items">
                            {needsAttention(item) && (
                              <button
                                type="button"
                                onClick={() => trigger(item.medication_id, item.local_time)}
                              >
                                {confirmingRemind === rowKey(item)
                                  ? "Send it now?"
                                  : "Remind now"}
                              </button>
                            )}
                            {item.event_id &&
                              item.status === "ESCALATED" &&
                              !item.acknowledged_at && (
                                <button
                                  type="button"
                                  onClick={() =>
                                    acknowledge(item.event_id as string)
                                  }
                                >
                                  I have got this
                                </button>
                              )}
                            <button
                              type="button"
                              onClick={() => {
                                setOpenMenu(null);
                                setEditing(
                                  editing === item.medication_id
                                    ? null
                                    : item.medication_id,
                                );
                              }}
                            >
                              Edit
                            </button>
                            <button
                              type="button"
                              className="rowmenu__danger"
                              onClick={() => {
                                setOpenMenu(null);
                                setRemoving(item.medication_id);
                              }}
                            >
                              Remove
                            </button>
                          </span>
                        )}
                      </span>
                    </span>

                    {editing === item.medication_id && (
                      <div className="schedule__editor">
                        <MedicationForm
                          elderId={elder.id}
                          elderName={elder.name}
                          elderTimezone={elder.timezone}
                          existing={medications.find(
                            (m) => m.id === item.medication_id,
                          )}
                          onCancel={() => setEditing(null)}
                          onSaved={() => {
                            setEditing(null);
                            loadDay();
                          }}
                        />
                      </div>
                    )}

                    {removing === item.medication_id && (
                      <div className="schedule__confirm" role="alertdialog">
                        <span>
                          Stop reminding {elder.name} about{" "}
                          <strong>{item.medication_name}</strong>? Today's
                          record is kept.
                        </span>
                        <button
                          type="button"
                          className="btn-danger"
                          onClick={() => removeMedication(item.medication_id)}
                        >
                          Remove it
                        </button>
                        <button
                          type="button"
                          className="btn-quiet"
                          onClick={() => setRemoving(null)}
                        >
                          Keep it
                        </button>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>

          {history.length > 0 && <History days={history} />}

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
              <h2>
                {elder.name}'s {phones && phones.length > 1 ? "phones" : "phone"}
              </h2>
            </div>

            {/* Whether the phone on the side table is actually working was
                something neither the family nor CareBridge could tell. */}
            {phones && phones.length > 0 && (
              <ul className="phones">
                {phones.map((device) => (
                  <li key={device.device_id} className="phones__row">
                    <span className="phones__what">
                      {device.label ?? device.platform ?? "Phone"}
                      {device.shared_with > 0 && (
                        <span className="muted">
                          {" "}
                          — also {device.shared_with === 1
                            ? "one other person"
                            : `${device.shared_with} other people`}
                        </span>
                      )}
                    </span>
                    <span className="muted">
                      last heard from {sinceWhen(device.last_seen_at)}
                    </span>
                  </li>
                ))}
              </ul>
            )}

            {firebaseConfigured ? (
              <>
                <ol className="pair__steps">
                  <li>Open this website on {elder.name}'s phone.</li>
                  <li>Tap <strong>Elder device</strong> at the top.</li>
                  <li>Read them the code below, and they type it in.</li>
                </ol>

                <button
                  type="button"
                  className="btn-primary"
                  onClick={() => getCode(elder.id)}
                  disabled={pairingBusy}
                >
                  {pairingBusy
                    ? "Making a code…"
                    : pairingCode?.elderId === elder.id
                      ? "Make a new code"
                      : "Get a pairing code"}
                </button>

                {pairingCode?.elderId === elder.id && (
                  <>
                    {/* Short enough to say out loud, which is how a family
                        does this — so it is set to be read, not copied. */}
                    <p
                      className="pair__spoken"
                      aria-label={`Pairing code for ${elder.name}`}
                    >
                      {pairingCode.code}
                    </p>
                    <p className="muted">
                      Their phone will show {elder.name}'s name once it works.
                      One code, one phone, and it lasts three days.
                    </p>
                  </>
                )}

                <div className="pair__lost">
                  <p className="muted">
                    Lost the phone, or someone has it who should not? Signing
                    out stops it opening {elder.name}'s medicines straight away.
                  </p>
                  <button
                    type="button"
                    className={
                      confirmingSignOut === elder.id
                        ? "btn-danger"
                        : "btn-quiet btn-quiet--danger"
                    }
                    onClick={() => signOutDevices(elder.id)}
                    onBlur={() => setConfirmingSignOut(null)}
                  >
                    {confirmingSignOut === elder.id
                      ? "Sign every phone out?"
                      : "Sign out all phones"}
                  </button>
                  {signOutResult && <p className="muted">{signOutResult}</p>}
                </div>
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
