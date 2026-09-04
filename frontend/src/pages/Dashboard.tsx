import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  pairElder,
  type Alert,
  type DayItem,
  type CareTeamMember,
  type Elder,
  type HistoryDay,
  type Device,
  type Insight as InsightData,
  type Ledger,
  type Medication,
  type SelfTest,
} from "../api/client";
import { firebaseConfigured } from "../api/firebase";
import { LANGUAGE_CHOICES } from "../i18n";
import MedicationForm from "../components/MedicationForm";
import { clockTime, sinceWhen, timeIn } from "../format";

const POLL_MS = 10000;

/** Counts from zero to `value` once, then tracks it.
 *
 *  The three figures are the product's argument, and an argument that animates
 *  into place is read; one that is simply present is skipped. Deliberately
 *  short — this is a dashboard somebody checks between other things, not a
 *  title sequence — and it holds still for anyone who has asked their system
 *  not to animate.
 */
function useCountUp(value: number, ms = 650): number {
  const [shown, setShown] = useState(value);
  const from = useRef(value);

  useEffect(() => {
    const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (still || value === from.current) {
      from.current = value;
      setShown(value);
      return;
    }

    const start = performance.now();
    const origin = from.current;
    from.current = value;
    let frame = 0;

    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / ms);
      // Ease out: the numbers slow as they land rather than stopping dead.
      const eased = 1 - Math.pow(1 - t, 3);
      setShown(Math.round(origin + (value - origin) * eased));
      if (t < 1) frame = requestAnimationFrame(tick);
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, ms]);

  return shown;
}

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
    // A dose nobody has tried to deliver yet has not gone nowhere — it has
    // not gone anywhere at all, which is a different sentence. The API sends
    // reached_a_phone as a plain boolean, so "never attempted" and "attempted
    // and reached nothing" arrive here looking identical, and a dose due in
    // twenty minutes was being announced as a household with no phone set up.
    item.attempt > 0 &&
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


/** The alerts list, which was a flat wall of every notification ever sent.
 *
 *  Fifty rows, each an identical sentence and a full timestamp, newest first.
 *  Nothing receded once it was handled and nothing stood out while it was not,
 *  so the only way to find this morning's escalation was to read all of them.
 *
 *  Three things changed. Days became headings, so "when" is read once per group
 *  rather than parsed per row. Repeats collapsed, because the same tablet
 *  failing three evenings running is one fact about a week, not three facts.
 *  And a reminder that never reached her phone is marked as ours, since the
 *  whole argument of this product is that those two failures are different.
 */
function Alerts({ alerts }: { alerts: Alert[] }) {
  const [expanded, setExpanded] = useState(false);

  if (alerts.length === 0) {
    return (
      <p className="empty">
        Nothing has needed your attention. CareBridge only writes here when
        something does.
      </p>
    );
  }

  const dayOf = (iso: string) => new Intl.DateTimeFormat("en-CA").format(new Date(iso));
  const today = dayOf(new Date().toISOString());
  const yesterday = dayOf(new Date(Date.now() - 86400000).toISOString());

  const heading = (day: string) => {
    if (day === today) return "Today";
    if (day === yesterday) return "Yesterday";
    return new Date(`${day}T12:00:00`).toLocaleDateString(undefined, {
      weekday: "long",
      day: "numeric",
      month: "short",
    });
  };

  // Same sentence on the same day is one row with a count. The message already
  // names the medicine and the time, so identical text means identical event.
  const days: { day: string; rows: (Alert & { times: number })[] }[] = [];
  for (const alert of alerts) {
    const day = dayOf(alert.created_at);
    let group = days.find((d) => d.day === day);
    if (!group) days.push((group = { day, rows: [] }));

    const seen = group.rows.find((r) => r.message === alert.message);
    if (seen) seen.times += 1;
    else group.rows.push({ ...alert, times: 1 });
  }

  const shown = expanded ? days : days.slice(0, 2);
  const hidden = days.slice(shown.length).reduce((n, d) => n + d.rows.length, 0);

  return (
    <>
      {shown.map((group) => (
        <div className="alerts__day" key={group.day}>
          <h3 className="alerts__heading">{heading(group.day)}</h3>
          <ul className="alerts">
            {group.rows.map((alert) => {
              // The distinction the whole product is built on: a phone we
              // never reached is our failure, not hers.
              const ours = alert.reason.toUpperCase() === "UNREACHABLE";

              return (
                <li
                  key={alert.id}
                  className={`alerts__item alerts__item--${alert.reason.toLowerCase()} ${
                    ours ? "alerts__item--ours" : ""
                  }`}
                >
                  <span className="alerts__what">
                    {alert.message}
                    {alert.times > 1 && (
                      <small className="alerts__times">· {alert.times} times</small>
                    )}
                  </span>

                  <span className="alerts__meta">
                    {ours && <span className="alerts__ours">ours to fix</span>}
                    <small title={new Date(alert.created_at).toLocaleString()}>
                      {group.day === today
                        ? sinceWhen(alert.created_at)
                        : new Date(alert.created_at).toLocaleTimeString(undefined, {
                            hour: "numeric",
                            minute: "2-digit",
                          })}
                    </small>
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      ))}

      {hidden > 0 && !expanded && (
        <button
          type="button"
          className="btn-quiet alerts__more"
          onClick={() => setExpanded(true)}
        >
          Show earlier ({hidden})
        </button>
      )}
    </>
  );
}

/** Enough of an address to tell two people apart, not enough to read out.
 *
 *  The care team list keeps an address rather than a name on purpose: this is
 *  the identity that received the invite and that escalation email will go to,
 *  and removing the wrong person from it is a safety mistake, not a cosmetic
 *  one. Masking keeps that check possible without putting a full address on
 *  screen for everyone in the room.
 */
function maskEmail(value: string): string {
  const [local, domain] = value.split("@");
  if (!domain) return value;
  const head = local.slice(0, 3);
  return `${head}${local.length > 3 ? "•••" : ""}@${domain}`;
}

/** The elder's own today, as YYYY-MM-DD. en-CA is the shortest way to get
 *  an ISO date out of Intl, and the course dates are stored in that shape. */
function todayIn(zone: string): string {
  try {
    return new Intl.DateTimeFormat("en-CA", { timeZone: zone }).format(new Date());
  } catch {
    return new Intl.DateTimeFormat("en-CA").format(new Date());
  }
}

function yesterdayIn(zone: string): string {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  try {
    return new Intl.DateTimeFormat("en-CA", { timeZone: zone }).format(d);
  } catch {
    return new Intl.DateTimeFormat("en-CA").format(d);
  }
}

function shortDate(iso: string): string {
  // Midday, so no timezone can drag the label onto the day before.
  return new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
  });
}

/** Where this medicine has got to in the course the doctor prescribed.
 *
 *  Shown once per medicine rather than on every row: a tablet taken three
 *  times a day is three rows, and "Day 4 of 15" repeated down all of them is
 *  noise pretending to be information.
 */
function CourseChip({ course }: { course: NonNullable<DayItem["course"]> }) {
  const lastDay = course.day >= course.of;

  return (
    <span className={`course ${lastDay ? "course--last" : ""}`}>
      {lastDay
        ? "Last day · ends today"
        : `Day ${course.day} of ${course.of} · ends ${shortDate(course.ends_on)}`}
    </span>
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

  // She answered. Nobody understood her. That is a person waiting on a reply,
  // and it outranks anything still merely in flight.
  const muddled = items.filter((i) => i.unclear_count > 0 && !i.acknowledged_at);
  if (muddled.length) {
    return {
      text: `Could not understand the reply about ${
        [...new Set(muddled.map((i) => i.medication_name))].join(" and ")
      }`,
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

/** The three numbers, and the gap between them.
 *
 *  Almost every product in this category shows one: doses taken out of doses
 *  scheduled. That number silently blames a woman for a phone nobody set up.
 *  These three separate what CareBridge managed to ask about from what she
 *  answered, and they add up — so a family can check them rather than trust
 *  them.
 */
function Progress({ ledger }: { ledger: Ledger }) {
  const { scheduled, asked, taken, unreachable, taken_on_trust } = ledger;
  const shownTaken = useCountUp(taken);
  const shownAsked = useCountUp(asked);
  const shownScheduled = useCountUp(scheduled);
  if (!scheduled) return null;

  const pct = (n: number) => `${(n / scheduled) * 100}%`;

  // The bar is the reach partition, with green filling the part of `asked`
  // that came back taken. It cannot be `taken` directly: a dose the family
  // records that was never delivered counts as taken but was never asked
  // about, so drawing it inside the asked segment would overflow the track
  // and, worse, would claim we reached her when we did not.
  const answered = Math.min(taken, asked);

  return (
    <section className="ledger">
      {/* The three numbers first, because they are the argument. Every other
          product in this category shows one — doses taken out of doses
          scheduled — and that one number blames her for a phone nobody set up. */}
      <dl className="ledger__figures">
        <div className="ledger__figure ledger__figure--taken">
          <dd>{shownTaken}</dd>
          <dt>Taken</dt>
        </div>
        <div className="ledger__figure ledger__figure--asked">
          <dd>{shownAsked}</dd>
          <dt>Asked</dt>
        </div>
        <div className="ledger__figure">
          <dd>{shownScheduled}</dd>
          <dt>Scheduled</dt>
        </div>
      </dl>

      <div
        className="progress__bar"
        role="img"
        aria-label={`${taken} taken, ${asked} asked about, ${scheduled} scheduled`}
      >
        <span className="progress__fill" style={{ width: pct(answered) }} />
        <span
          className="progress__asked"
          style={{ width: pct(asked - answered) }}
        />
        <span className="progress__unreached" style={{ width: pct(unreachable) }} />
      </div>

      {/* Without a key the green is just a green bar. The legend is permanent
          rather than a tooltip: this is the one thing on the page a family is
          asked to trust, so it has to be readable without being hunted for. */}
      <ul className="ledger__key">
        <li>
          <span className="ledger__swatch ledger__swatch--taken" />
          She answered
        </li>
        <li>
          <span className="ledger__swatch ledger__swatch--asked" />
          Asked, waiting
        </li>
        <li>
          <span className="ledger__swatch ledger__swatch--unreached" />
          Never reached them
        </li>
      </ul>

      {/* The whole point of counting this way, said in words. The difference
          between the second number and the third is the difference between a
          person ignoring her tablets and a phone that never rang. */}
      {unreachable > 0 && (
        <p className="progress__gap">
          <span className="ledger__ours">ours to fix</span>
          {unreachable === 1 ? "1 dose was" : `${unreachable} doses were`} never
          asked about — no reminder reached the phone.
        </p>
      )}

      {taken_on_trust > 0 && (
        <p className="progress__trust">
          {taken_on_trust === 1 ? "1 was" : `${taken_on_trust} were`} recorded on
          your word rather than hers.
        </p>
      )}
    </section>
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
          // A day nothing was delivered on is not a bad day for her. It gets
          // its own mark, so the strip cannot be read as a run of misses.
          const tone =
            day.scheduled === 0
              ? "empty"
              : day.unreachable > 0
                ? "unreached"
                : day.no_answer > 0
                  ? "bad"
                  : day.asked > 0 && day.taken === day.asked
                    ? "good"
                    : "part";

          return (
            <li
              key={day.date}
              className={`week__day week__day--${tone}`}
              title={
                day.scheduled === 0
                  ? "Nothing scheduled"
                  : `${day.taken} taken of ${day.asked} asked, ${day.scheduled} scheduled`
              }
            >
              <span className="week__letter">{weekday(day.date)}</span>
              <span className="week__count">
                {day.scheduled === 0
                  ? "–"
                  : day.asked === 0
                    ? // Nothing was delivered, so there is no ratio to show.
                      // "0/0" reads as a failure by her; this does not.
                      "·"
                    : `${day.taken}/${day.asked}`}
              </span>
            </li>
          );
        })}
      </ul>

      <p className="card__hint week__legend">
        Taken, out of the doses CareBridge was able to ask about. A crossed day
        is one where a reminder never reached the phone — that one is ours, not
        hers.
      </p>
    </section>
  );
}

const CHANGE_LABEL: Record<string, string> = {
  adherence_of_asked: "doses taken",
  median_minutes_to_taken: "how long doses take",
  morning_adherence: "mornings",
  afternoon_adherence: "afternoons",
  evening_adherence: "evenings",
  doses_never_delivered: "reminders that never arrived",
};

/** The week in a sentence, with the figures underneath it.
 *
 *  Every number here was computed before the model saw it; the agent is asked
 *  only to phrase them. Which is why the card still works with the agent
 *  switched off — `narrated` says which version you are reading.
 */
function Insight({ insight }: { insight: InsightData }) {
  const week = insight.this_week;
  const late = week.median_minutes_to_taken;

  return (
    <section className="card insight">
      <div className="card__head">
        <h2>How the week went</h2>
      </div>

      <p className="insight__note">{insight.note}</p>

      <dl className="insight__figures">
        <div>
          <dt>Taken, of those asked</dt>
          <dd>
            {week.adherence_of_asked === null
              ? "—"
              : `${Math.round(week.adherence_of_asked * 100)}%`}
          </dd>
        </div>
        <div>
          {/* The number that moves first. Someone beginning to struggle still
              takes the tablet, just later and later — weeks before a dose is
              ever actually missed. */}
          <dt>Usual wait</dt>
          <dd>{late === null ? "—" : `${Math.round(late)} min`}</dd>
        </div>
        <div>
          <dt>Never delivered</dt>
          <dd>{week.unreachable}</dd>
        </div>
      </dl>

      {insight.what_changed.length > 0 && (
        <ul className="insight__changes">
          {insight.what_changed.map((change) => (
            <li
              key={change.metric}
              className={`insight__change insight__change--${change.direction}`}
            >
              {CHANGE_LABEL[change.metric] ?? change.metric}
              {change.direction === "ours_to_fix"
                ? " — ours to fix"
                : change.direction === "worse"
                  ? " — worse than usual"
                  : " — better than usual"}
            </li>
          ))}
        </ul>
      )}

      <p className="card__hint">
        {insight.narrated
          ? "Counted by CareBridge, written up by the analyst agent."
          : "Counted by CareBridge."}
      </p>
    </section>
  );
}

/** Whether the whole chain works, asked before the evening it has to.
 *
 *  Every silent failure this project has hit is on this list, and each one only
 *  ever announced itself as "she has not confirmed" — which reads as a person
 *  rather than as plumbing.
 */
function SelfTestResult({ result }: { result: SelfTest }) {
  return (
    <div className={`selftest ${result.ok ? "selftest--ok" : "selftest--broken"}`}>
      <p className="selftest__verdict">
        {result.ok
          ? "Everything is set up. A reminder tonight will get through."
          : "Something in the chain is not set up yet."}
      </p>
      <ul className="selftest__checks">
        {result.checks.map((check) => (
          <li key={check.check} className={check.ok ? "is-ok" : "is-broken"}>
            <span aria-hidden="true">{check.ok ? "✓" : "✗"}</span>
            <span className="selftest__what">{check.check}</span>
            <small>{check.detail}</small>
          </li>
        ))}
      </ul>
    </div>
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
  const [ledger, setLedger] = useState<Ledger | null>(null);
  const [insight, setInsight] = useState<InsightData | null>(null);
  const [selfTest, setSelfTest] = useState<SelfTest | null>(null);
  const [testing, setTesting] = useState(false);
  const [phones, setPhones] = useState<Device[] | null>(null);
  const [confirmingRemind, setConfirmingRemind] = useState<string | null>(null);
  const [confirmingSignOut, setConfirmingSignOut] = useState<string | null>(null);
  const [signOutResult, setSignOutResult] = useState<string | null>(null);
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [newElderName, setNewElderName] = useState("");
  const [newElderLanguage, setNewElderLanguage] = useState("en");
  // One long scroll held everything: the day, the week, the alerts, the
  // phones and the setup steps. A caregiver checking in between other things
  // is answering one question, and had to scroll past four others to reach it.
  const [tab, setTab] = useState<"today" | "alerts" | "phone">("today");
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
      setLedger(day.ledger);
      setAlerts(alertList);
      setMedications(meds.filter((m) => m.active !== false));
      setHistory(past.days);
      setPhones(devices);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load");
    }
  }, [selected]);

  // Deliberately outside loadDay. The note is a week old by nature and can
  // wait on a model for a few seconds; the day cannot wait on anything.
  const loadInsight = useCallback(async () => {
    if (!selected) return;
    try {
      setInsight(await api.insight(selected));
    } catch {
      // A missing weekly note is not worth an error banner over today.
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

  useEffect(() => {
    setInsight(null);
    loadInsight();
  }, [loadInsight]);

  useEffect(() => {
    setSelfTest(null);
  }, [selected]);

  const addElder = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!newElderName.trim()) return;

    try {
      const elder = await api.createElder({
        name: newElderName.trim(),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        // Asked for at the same moment as the name, because the person setting
        // this up knows it then, and the elder screen is unreadable to whoever
        // it is for until somebody says.
        preferred_language: newElderLanguage,
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

  const checkItWorks = async (elderId: string) => {
    setTesting(true);
    setSelfTest(null);
    try {
      setSelfTest(await api.selfTest(elderId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not run the check");
    } finally {
      setTesting(false);
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

  const changeLanguage = async (language: string) => {
    if (!selected) return;
    try {
      await api.updateElder(selected, { preferred_language: language });
      await loadElders();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not change the language");
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

  // One chip per medicine, on whichever of its rows comes first.
  const chipRow = new Map<string, string>();
  for (const item of items) {
    if (!chipRow.has(item.medication_id)) chipRow.set(item.medication_id, rowKey(item));
  }

  // A finished course has no rows left — its doses stopped being generated —
  // so without this the medicine simply vanishes from the day with no word
  // about where it went.
  const elderToday = elder ? todayIn(elder.timezone) : "";
  const finished = elder
    ? medications.filter((m) => m.ends_on && m.ends_on < elderToday)
    : [];

  return (
    <div className="dash">
      {/* One panel rather than a heading followed by a card. The sentence a
          worried family reads and the numbers that back it up are the same
          thought, and splitting them made the page open on an announcement
          with no evidence under it. */}
      <header className="dash__hero">
        <p className="dash__eyebrow">Today</p>
        <p className={`dash__verdict ${status.alert ? "dash__verdict--alert" : ""}`}>
          {status.text}
        </p>

        {/* Said before any dose is due, not after one has quietly failed.
            With no phone set up nothing can reach her, and every reminder is
            recorded as sent to nobody. */}
        {phones?.length === 0 && elder && (
          <p className="dash__nophone">
            No phone is set up for {elder.name}, so reminders cannot reach her.
            Get a pairing code below and enter it on her phone.
          </p>
        )}

        {ledger && <Progress ledger={ledger} />}
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
          <select
            value={newElderLanguage}
            onChange={(event) => setNewElderLanguage(event.target.value)}
            aria-label="Language they read and speak"
          >
            {LANGUAGE_CHOICES.map((choice) => (
              <option key={choice.code} value={choice.code}>
                {choice.label}
              </option>
            ))}
          </select>
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
          <nav className="tabs" aria-label={`${elder.name}'s sections`}>
            {(
              [
                ["today", "Today"],
                ["alerts", "Alerts"],
                ["phone", "Phone"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                className={`tabs__tab ${tab === key ? "tabs__tab--on" : ""}`}
                aria-current={tab === key ? "page" : undefined}
                onClick={() => setTab(key)}
              >
                {label}
                {/* The count is the point of the tab. A caregiver should not
                    have to open it to find out whether it wants them. */}
                {key === "alerts" && alerts.length > 0 && (
                  <span className="tabs__count">{alerts.length}</span>
                )}
              </button>
            ))}
          </nav>

          {tab === "today" && (
          <div className="dash__grid">
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

                <label>
                  Language for {elder.name}
                  <select
                    value={elder.preferred_language}
                    onChange={(event) => changeLanguage(event.target.value)}
                  >
                    {LANGUAGE_CHOICES.map((choice) => (
                      <option key={choice.code} value={choice.code}>
                        {choice.label}
                      </option>
                    ))}
                  </select>
                </label>
                <p className="settings__note">
                  {elder.name}'s screen is written and spoken in this language,
                  and CareBridge listens for it too. Medicine names stay exactly
                  as you typed them.
                </p>

                <div className="team">
                  <h3>Who gets told</h3>
                  <p className="settings__note">
                    Everyone here is alerted when {elder.name} misses a dose.
                  </p>

                  <ul className="team__list">
                    {team.map((member) => (
                      <li key={member.caregiver_id}>
                        <span title={member.email ?? undefined}>
                          {member.name?.trim()
                            ? member.name
                            : member.email
                              ? maskEmail(member.email)
                              : member.caregiver_id}
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

            {finished.length > 0 && (
              <ul className="finished">
                {finished.map((m) => (
                  <li key={m.id}>
                    <span>
                      <strong>{m.name}</strong> finished{" "}
                      {m.ends_on === yesterdayIn(elder.timezone)
                        ? "yesterday"
                        : `on ${shortDate(m.ends_on as string)}`}
                      .
                    </span>
                    <button
                      type="button"
                      className="btn-quiet"
                      onClick={() => setEditing(editing === m.id ? null : m.id)}
                    >
                      Extend
                    </button>
                    <button
                      type="button"
                      className="btn-quiet btn-quiet--danger"
                      onClick={() => removeMedication(m.id)}
                    >
                      Remove
                    </button>

                    {editing === m.id && (
                      <div className="schedule__editor">
                        <MedicationForm
                          elderId={elder.id}
                          elderName={elder.name}
                          elderTimezone={elder.timezone}
                          existing={m}
                          onCancel={() => setEditing(null)}
                          onSaved={() => {
                            setEditing(null);
                            loadDay();
                          }}
                        />
                      </div>
                    )}
                  </li>
                ))}
              </ul>
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
                      {item.course && chipRow.get(item.medication_id) === rowKey(item) && (
                        <CourseChip course={item.course} />
                      )}
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

                      {/* Who vouched for it. A dose recorded from another city
                          is a different fact from one she answered herself,
                          and a record a clinician might read should say so. */}
                      {item.status === "TAKEN" &&
                        item.confirmed_source === "CAREGIVER" && (
                          <small>on your word</small>
                        )}

                      {/* She answered and CareBridge could not tell what she
                          meant. Nothing was recorded either way, which is the
                          honest outcome and the one worth showing. */}
                      {item.unclear_count > 0 && (
                        <small className="schedule__unclear">
                          could not understand
                          {item.last_unclear ? `: “${item.last_unclear}”` : ""}
                        </small>
                      )}
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

          <aside className="dash__aside">
            {history.length > 0 && <History days={history} />}
            {insight && <Insight insight={insight} />}
          </aside>
          </div>
          )}

          {tab === "alerts" && (
          <section className="card">
            <div className="card__head">
              <h2>Alerts</h2>
            </div>

            <Alerts alerts={alerts} />
          </section>
          )}

          {tab === "phone" && (
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

            {/* The question a family actually has about the phone on the side
                table, answerable in one press instead of one missed dose. */}
            <div className="selftest__run">
              <button
                type="button"
                className="btn-primary"
                onClick={() => checkItWorks(elder.id)}
                disabled={testing}
              >
                {testing ? "Checking…" : "Check it works"}
              </button>
              <p className="muted">
                Rings {elder.name}'s phone and checks every step of the chain.
                Nothing is recorded against her medicines.
              </p>
              {selfTest && <SelfTestResult result={selfTest} />}
            </div>

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
          )}
        </>
      )}
    </div>
  );
}
