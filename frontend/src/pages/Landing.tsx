import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

/**
 * What somebody sees before they have an account.
 *
 * Until now a stranger opening CareBridge got a sign-in form: no idea what the
 * thing is, who it is for, or why it counts doses the way it does. The product
 * has an argument — that a missed dose is often our failure to reach them
 * rather than their failure to take it — and that argument was only visible to
 * people who already had a login.
 *
 * The ledger here is not a picture of the product. It is the product's own
 * markup and stylesheet, filled with a plausible day. Nothing on this page is a
 * mock-up of something that does not exist yet.
 */

/** Adds a class the first time an element is scrolled into view. */
function useReveal<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [seen, setSeen] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (still || !("IntersectionObserver" in window)) {
      setSeen(true);
      return;
    }

    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setSeen(true);
          io.disconnect();
        }
      },
      { rootMargin: "-60px" },
    );

    io.observe(node);
    return () => io.disconnect();
  }, []);

  return { ref, seen };
}

/** Wraps anything so it arrives on scroll instead of already being there. */
function Reveal({
  children,
  delay = 0,
  as: Tag = "div",
  className = "",
}: {
  children: React.ReactNode;
  delay?: number;
  as?: React.ElementType;
  className?: string;
}) {
  const { ref, seen } = useReveal<HTMLDivElement>();

  return (
    <Tag
      ref={ref}
      className={`rise ${seen ? "rise--in" : ""} ${className}`.trim()}
      style={{ transitionDelay: `${delay}ms` }}
    >
      {children}
    </Tag>
  );
}

/** A number that counts up the first time it is scrolled into view. */
function Tally({ to }: { to: number }) {
  const { ref, seen } = useReveal<HTMLSpanElement>();
  const [n, setN] = useState(0);

  useEffect(() => {
    if (!seen) return;

    const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (still) {
      setN(to);
      return;
    }

    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / 900);
      setN(Math.round(to * (1 - Math.pow(1 - t, 3))));
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [seen, to]);

  return <span ref={ref}>{n}</span>;
}

/**
 * One feature, shown rather than described.
 *
 * Every card carries a real fragment of the product — the actual course chip,
 * the actual dose counter, the real Telugu the elder screen renders — for the
 * same reason the ledger is real: a page that illustrates its claims with
 * drawings is asking to be taken on trust.
 */
function Feature({
  title,
  children,
  demo,
  index,
}: {
  title: string;
  children: React.ReactNode;
  demo: React.ReactNode;
  index: number;
}) {
  const { ref, seen } = useReveal<HTMLLIElement>();

  return (
    <li
      ref={ref}
      className={`feat ${seen ? "feat--in" : ""}`}
      style={{ transitionDelay: `${(index % 3) * 90}ms` }}
    >
      <div className="feat__demo" aria-hidden="true">
        {demo}
      </div>
      <h3>{title}</h3>
      <p>{children}</p>
    </li>
  );
}

function Mark() {
  return (
    <svg className="mark" viewBox="0 0 64 64" aria-hidden="true">
            <circle cx="19" cy="19" r="8" fill="currentColor" />
            <path
              d="M10 49V37a9.5 9.5 0 0 1 9.5-9.5"
              fill="none"
              stroke="currentColor"
              strokeWidth="6"
              strokeLinecap="round"
            />
            <path
              d="M19 31c9 0 17 3 22 8"
              fill="none"
              stroke="currentColor"
              strokeWidth="5.5"
              strokeLinecap="round"
            />
            <circle cx="44" cy="26" r="6.5" fill="currentColor" />
            <path
              d="M36 49v-7a8 8 0 0 1 16 0v7"
              fill="none"
              stroke="currentColor"
              strokeWidth="6"
              strokeLinecap="round"
            />
          </svg>
  );
}

/**
 * The moment the product exists for, happening on the page.
 *
 * A screenshot of a reminder is a picture of a locked screen. The thing worth
 * showing is the transition — dark handset on a side table, then it lights
 * itself up without being touched. So the phone here actually wakes, on a loop,
 * and the visitor watches the product work before reading a word about it.
 */
function Phone() {
  const [awake, setAwake] = useState(false);

  useEffect(() => {
    const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (still) {
      setAwake(true);
      return;
    }

    // Dark for a beat first: the whole point is that nobody touched it.
    const first = window.setTimeout(() => setAwake(true), 1100);
    const loop = window.setInterval(() => {
      setAwake(false);
      window.setTimeout(() => setAwake(true), 1400);
    }, 9000);

    return () => {
      window.clearTimeout(first);
      window.clearInterval(loop);
    };
  }, []);

  return (
    <div className={`phone ${awake ? "phone--awake" : ""}`} aria-hidden="true">
      <div className="phone__ring" />
      <div className="phone__ring phone__ring--late" />
      <div className="phone__body">
        <div className="phone__screen">
          <p className="phone__label">MEDICINE TIME</p>
          <img
            className="phone__shot"
            src="/medicine-vitamin-c.jpg"
            alt=""
            width="447"
            height="447"
          />
          <p className="phone__name">Vitamin C</p>
          <p className="phone__strength">500 mg</p>
          <p className="phone__dose">1 tablet · after food</p>
          <div className="phone__voice">
            <span className="phone__wave" />
            <span className="phone__wave" />
            <span className="phone__wave" />
            <span className="phone__wave" />
            <span className="phone__wave" />
            <em>a familiar voice</em>
          </div>
          <div className="phone__btn">I took it</div>
        </div>
      </div>
    </div>
  );
}

/**
 * One dose, from scheduled to answered, on both screens at once.
 *
 * The centre of the page. A visitor does not need the product explained if they
 * can watch it happen: the phone lights itself at eight, the family's voice
 * plays, she presses one button, and the row on her daughter's dashboard stops
 * saying "waiting".
 *
 * The words on the right are the product's own - "Later today", "Waiting for a
 * reply", "reminder 1 of 2", "Taken" are the real STATUS_LABEL strings, and the
 * row tones are the real ones. What a visitor is reading is the actual state
 * machine, not a description of it.
 */
const STAGES = [
  { tab: "Scheduled", clock: "7:59 am" },
  { tab: "Reminder", clock: "8:00 am" },
  { tab: "Delivered", clock: "8:00 am" },
  { tab: "Answered", clock: "8:01 am" },
  { tab: "Taken", clock: "8:01 am" },
];

const LAST = STAGES.length - 1;

function DoseJourney() {
  const { ref, seen } = useReveal<HTMLDivElement>();
  // Read once, in the initialiser: an effect that calls setState synchronously
  // is the one lint rule this file is already carrying four of.
  const [still] = useState(
    () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false,
  );
  const [stage, setStage] = useState(0);
  const [held, setHeld] = useState(false);

  // A chain of timeouts rather than one interval, so each step can have its own
  // beat - the wake is quick, the voice needs a moment to be heard.
  useEffect(() => {
    if (!seen || still || held || stage >= LAST) return;
    const wait = stage === 0 ? 1100 : stage === 2 ? 2100 : 1500;
    const id = window.setTimeout(() => setStage((s) => s + 1), wait);
    return () => window.clearTimeout(id);
  }, [seen, still, held, stage]);

  // Touching it hands control over for good. Nothing is more irritating than a
  // demo that keeps moving while you are trying to read one step of it.
  const pick = (next: number) => {
    setHeld(true);
    setStage(next);
  };

  const onKeys = (event: React.KeyboardEvent) => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    event.preventDefault();
    pick(
      event.key === "ArrowRight"
        ? Math.min(LAST, stage + 1)
        : Math.max(0, stage - 1),
    );
  };

  const awake = stage >= 1;
  const speaking = stage === 2;
  const answered = stage >= 3;
  const done = stage === LAST;

  return (
    <div className="journey" ref={ref}>
      <div className="journey__head">
        <p className="land__eyebrow">See what happens when a dose is due</p>
        <button
          type="button"
          className="journey__replay"
          onClick={() => {
            setHeld(false);
            setStage(0);
          }}
        >
          {stage === 0 && !held ? "Watch it" : "Play it again"}
        </button>
      </div>

      <div
        className="journey__stages"
        role="tablist"
        aria-label="One dose, step by step"
        onKeyDown={onKeys}
      >
        {STAGES.map((s, i) => (
          <button
            key={s.tab}
            type="button"
            role="tab"
            aria-selected={i === stage}
            tabIndex={i === stage ? 0 : -1}
            className={`journey__stage ${i === stage ? "journey__stage--on" : ""} ${
              i < stage ? "journey__stage--past" : ""
            }`}
            onClick={() => pick(i)}
          >
            <span className="journey__stageDot" aria-hidden="true" />
            {s.tab}
          </button>
        ))}
      </div>

      <div className="journey__pair">
        {/* Her phone. Decorative - the caption and the stage names carry the
            meaning, and a keyboard user should not land on three dead buttons. */}
        <figure className="journey__side" aria-hidden="true">
          <div className={`journey__phone ${awake ? "journey__phone--awake" : ""}`}>
            <p className="journey__clock">{STAGES[stage].clock}</p>

            {!awake ? (
              <p className="journey__asleep">on the side table</p>
            ) : done ? (
              <div className="journey__calm">
                <span className="journey__tick">✓</span>
                <p>Nothing to take right now</p>
              </div>
            ) : (
              /* Deliberately the real screen's proportions, not a prettier
                 version of them: the medicine name is set larger than the
                 heading above it, and the three actions are full-width blocks
                 in the order the product actually shows them - answer, put off,
                 speak. What tells a visitor who this was built for is the size
                 of the type, not the photograph. */
              <div className="journey__screen">
                <p className="journey__label">Medicine time</p>

                <img
                  className="journey__shot"
                  src="/medicine-vitamin-c.jpg"
                  alt=""
                  loading="lazy"
                  decoding="async"
                  width="447"
                  height="447"
                />

                <div
                  className={`journey__voice ${speaking ? "journey__voice--on" : ""}`}
                >
                  <span className="journey__wave" />
                  <span className="journey__wave" />
                  <span className="journey__wave" />
                  <span className="journey__wave" />
                  <span className="journey__wave" />
                  <em>{speaking ? "your voice" : "Hear your family"}</em>
                </div>

                <p className="journey__medicine">Vitamin C</p>
                <p className="journey__strength">500 mg</p>
                <p className="journey__dose">1 tablet</p>
                <p className="journey__food">after food</p>

                <div
                  className={`journey__btn ${answered ? "journey__btn--pressed" : ""}`}
                >
                  I took it
                </div>
                <div className="journey__btn journey__btn--later">
                  Remind me later
                </div>
                <div className="journey__btn journey__btn--speak">
                  Speak to CareBridge
                </div>
              </div>
            )}
          </div>
          <figcaption>Their phone</figcaption>
        </figure>

        <figure className="journey__side" aria-hidden="true">
          <div className="journey__dash">
            <p className="dash__eyebrow">Today</p>
            <ul className="schedule journey__rows">
              <li
                className={`schedule__row schedule__row--${
                  done ? "good" : stage === 0 ? "idle" : "waiting"
                }`}
              >
                <span className="schedule__time">8:00 am</span>
                <span className="journey__photo pill pill--teal" />
                <span className="schedule__what">
                  <strong>Vitamin C 500 mg</strong>
                  <small>1 tablet · after food</small>
                </span>
                <span className="schedule__status">
                  {done
                    ? "Taken"
                    : stage === 0
                      ? "Later today"
                      : "Waiting for a reply"}
                  {stage >= 1 && !done && <small>reminder 1 of 2</small>}
                  {done && <small>they answered on their phone</small>}
                </span>
              </li>
            </ul>
          </div>
          <figcaption>Your dashboard</figcaption>
        </figure>
      </div>
    </div>
  );
}

/**
 * One account, several people to look after.
 *
 * The dashboard's own question is "who needs me?", not "what are my numbers",
 * so the board leads with the person and the one word that matters, and the
 * timeline only opens for whoever you pick. The switcher is the real one - the
 * caregiver app has exactly this row of chips.
 */
const FAMILY = [
  {
    name: "Mom",
    line: "8 of 8 taken",
    ok: true,
    day: [
      { time: "8:00 am", what: "Amlodipine", tone: "good", said: "Taken" },
      { time: "2:00 pm", what: "Metformin", tone: "good", said: "Taken" },
      { time: "8:00 pm", what: "Atorvastatin", tone: "good", said: "Taken" },
    ],
  },
  {
    name: "Dad",
    line: "6 of 8 taken",
    ok: false,
    day: [
      { time: "8:00 am", what: "Metformin", tone: "good", said: "Taken" },
      { time: "2:00 pm", what: "Losartan", tone: "waiting", said: "Waiting for a reply" },
      { time: "8:00 pm", what: "Eye drops", tone: "bad", said: "Needs you" },
    ],
  },
  {
    name: "Grandma",
    line: "5 of 5 taken",
    ok: true,
    day: [
      { time: "9:00 am", what: "Vitamin D", tone: "good", said: "Taken" },
      { time: "1:00 pm", what: "Calcium", tone: "good", said: "Taken" },
      { time: "7:00 pm", what: "Thyroxine", tone: "good", said: "Taken" },
    ],
  },
];

function FamilyBoard() {
  const [who, setWho] = useState(1);
  const person = FAMILY[who];

  return (
    <div className="board">
      <p className="board__ask">Who needs me?</p>

      <div className="board__people">
        {FAMILY.map((p, i) => (
          <button
            key={p.name}
            type="button"
            className={`board__person ${i === who ? "board__person--on" : ""}`}
            onClick={() => setWho(i)}
            aria-pressed={i === who}
          >
            <span className="board__name">{p.name}</span>
            <span className="board__line">{p.line}</span>
            <span
              className={`board__flag ${p.ok ? "board__flag--ok" : "board__flag--needs"}`}
            >
              {p.ok ? "All caught up" : "1 needs attention"}
            </span>
          </button>
        ))}
      </div>

      <div className="board__day" aria-live="polite">
        <p className="board__dayTitle">{person.name}&rsquo;s day</p>
        <ul className="schedule board__rows">
          {person.day.map((row) => (
            <li
              key={row.time}
              className={`schedule__row schedule__row--${row.tone}`}
            >
              <span className="schedule__time">{row.time}</span>
              <span className="journey__photo pill pill--teal" />
              <span className="schedule__what">
                <strong>{row.what}</strong>
              </span>
              <span className="schedule__status">{row.said}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export default function Landing() {
  return (
    <main className="land">
      <header className="land__bar">
        <span className="land__brand">
          <Mark />
          CareBridge
        </span>
        <nav className="land__nav">
          <a href="#how">How it works</a>
          <a href="#family">For families</a>
          <a href="#safety">Safety</a>
        </nav>
        <Link className="btn-primary btn-primary--sm" to="/signin">
          Sign in
        </Link>
      </header>

      <section className="land__hero">
        <div className="land__heroText">
          <h1>
            Still there,<br />
            <em>even when you&rsquo;re not.</em>
          </h1>
          <p className="land__lede land__lede--lift">
            You can&rsquo;t be beside them for every medicine. But your voice can
            be there when it matters.
          </p>
          <p className="land__lede">
            CareBridge lets you send a reminder in your own voice, helps them
            answer with one tap or in their own words, and tells you what
            actually happened.
          </p>
          <div className="land__cta">
            <Link className="btn-primary" to="/signin">
              Get started
            </Link>
            <a className="land__quiet" href="#how">
              See how it works
            </a>
          </div>
        </div>

        <Phone />
      </section>

      <section className="land__moment" id="how">
        <DoseJourney />
      </section>

      <section className="land__story">
        <Reveal as="h2" className="land__big">
          You can&rsquo;t be there for every dose.
        </Reveal>
        <Reveal as="p" delay={80}>
          Work starts. Meetings run late. Life gets in the way. Meanwhile
          someone at home still has a medicine to take, and a strip that looks
          like every other strip.
        </Reveal>
        <Reveal as="p" className="land__strike" delay={160}>
          But your voice can.
        </Reveal>
      </section>

      <section className="cases">
        <Reveal as="h2" className="land__big">
          A missed dose isn&rsquo;t always a missed dose.
        </Reveal>
        <Reveal as="p" className="cases__lede" delay={80}>
          Four different things end up under one word. They are not the same
          thing, and only one of them is about the person at all.
        </Reveal>

        <ul className="cases__list">
          <Reveal as="li" delay={0}>
            <span className="cases__mark cases__mark--them" aria-hidden="true" />
            <strong>They forgot.</strong>
            <span>The one case everybody assumes.</span>
          </Reveal>
          <Reveal as="li" delay={90}>
            <span className="cases__mark cases__mark--wait" aria-hidden="true" />
            <strong>They heard it, and haven&rsquo;t answered yet.</strong>
            <span>Still open. Nobody has failed.</span>
          </Reveal>
          <Reveal as="li" delay={180}>
            <span className="cases__mark cases__mark--wait" aria-hidden="true" />
            <strong>The phone was switched off, or out of battery.</strong>
            <span>
              A locked phone is no trouble — CareBridge wakes it. A phone with
              no power is a different thing.
            </span>
          </Reveal>
          <Reveal as="li" delay={270}>
            <span className="cases__mark cases__mark--ours" aria-hidden="true" />
            <strong>It never reached them.</strong>
            <span>Ours to fix, and we say so.</span>
          </Reveal>
        </ul>

        {/* The two paths, in the product's own status words. */}
        <div className="paths">
          <Reveal className="paths__one" delay={0}>
            <p className="paths__title">When it works</p>
            <ol className="paths__flow">
              <li>Scheduled</li>
              <li>Asked</li>
              <li>Answered</li>
              <li className="paths__end paths__end--good">Taken</li>
            </ol>
          </Reveal>
          <Reveal className="paths__one" delay={120}>
            <p className="paths__title">When it doesn&rsquo;t</p>
            <ol className="paths__flow">
              <li>Scheduled</li>
              <li className="paths__miss">Not reached</li>
              <li>Reminded again</li>
              <li className="paths__end paths__end--bad">You are told</li>
            </ol>
          </Reveal>
        </div>
      </section>


      <section className="family" id="family">
        <p className="land__eyebrow">One account, everyone you look after</p>
        <Reveal as="h2" className="land__big">
          Care is rarely one person.
        </Reveal>
        <Reveal as="p" className="cases__lede" delay={80}>
          Most people carrying this are carrying it for more than one person.
          Mom&rsquo;s morning, Dad&rsquo;s evening, and a grandparent who is
          doing fine — in one place, so the day starts with who needs you rather
          than with a list.
        </Reveal>
        <Reveal delay={140}>
          <FamilyBoard />
        </Reveal>
      </section>

      <section className="team">
        <p className="land__eyebrow">Nobody has to be the only one</p>
        <Reveal as="h2" className="land__big">
          Care doesn&rsquo;t have to fall on one person.
        </Reveal>

        <div className="team__pair">
          <div className="team__text">
            <Reveal as="p" delay={60}>
              Right now it is a group chat and a rota nobody agreed to. One of
              you rings at nine to check. Another rings at half past, because
              they did not know the first call happened.
            </Reveal>
            <Reveal as="p" delay={120}>
              Invite whoever shares it — your brother, your sister, the
              neighbour who has a key. Everyone sees the same day. And when a
              dose goes unanswered, <em>everyone</em> is told.
            </Reveal>
            <Reveal as="p" delay={180} className="team__aside">
              And if it is both your parents, that is one account and two
              people — not two logins and twice the remembering.
            </Reveal>
          </div>

          {/* Not a diagram of an idea: this is what notify_caregiver does with
              a missed dose - one message per person on the elder's team. */}
          <figure className="team__fan" aria-hidden="true">
            <p className="team__event">8:00 PM · no answer</p>
            <div className="team__lines">
              <span />
              <span />
              <span />
            </div>
            <ul className="team__people">
              <li>
                <span className="team__name">Meera</span>
                <span className="team__where">Bangalore</span>
              </li>
              <li>
                <span className="team__name">Raghu</span>
                <span className="team__where">Dubai</span>
              </li>
              <li>
                <span className="team__name">Lakshmi</span>
                <span className="team__where">next door</span>
              </li>
            </ul>
          </figure>
        </div>

        <Reveal as="p" delay={240} className="team__note">
          Each of them told separately, in their own message — so the neighbour
          helping for a fortnight never sees the family&rsquo;s email addresses.
        </Reveal>
      </section>

      <section className="numbers">
        <p className="land__eyebrow">Being straight with you</p>
        <Reveal as="h2" className="land__big">
          Three numbers. Not one.
        </Reveal>
        <Reveal as="p" className="cases__lede" delay={80}>
          What the doctor prescribed. What CareBridge actually managed to ask
          about. And what came back as an answer. Three different facts, kept
          apart on purpose.
        </Reveal>

        <div className="numbers__row" aria-hidden="true">
          <Reveal className="numbers__one" delay={0}>
            <span className="numbers__fig">
              <Tally to={10} />
            </span>
            <span className="numbers__word">Scheduled</span>
          </Reveal>
          <Reveal className="numbers__one" delay={110}>
            <span className="numbers__fig numbers__fig--asked">
              <Tally to={8} />
            </span>
            <span className="numbers__word">Asked</span>
          </Reveal>
          <Reveal className="numbers__one" delay={220}>
            <span className="numbers__fig numbers__fig--taken">
              <Tally to={6} />
            </span>
            <span className="numbers__word">Answered</span>
          </Reveal>
        </div>

        {/* The whole argument of the product, in one panel. */}
        <Reveal className="ours" delay={300}>
          <p className="ours__count">
            <Tally to={2} /> doses never reached them.
          </p>
          <p className="ours__badge">
            <span className="ledger__ours">ours to fix</span>
          </p>
          <p className="ours__say">
            Not a missed dose. A reminder that never arrived — the phone was
            off, or flat, or had never been set up. CareBridge does not put that
            on them, and it does not quietly round it into a number that looks
            like they forgot.
          </p>
        </Reveal>
      </section>

      <section className="land__honest" id="honest">
        <div className="land__honestText">
          <p className="land__eyebrow">And here it is in the product</p>
          <Reveal as="h2">The same day, on your dashboard.</Reveal>
          <p>
            Not a picture of the product — the product&rsquo;s own markup and
            stylesheet, filled with a plausible day. The green is what they
            answered, the amber is still waiting, and the hatched piece is the
            part we never delivered.
          </p>
        </div>

        {/* Not a picture of the product: the product's own markup and
            stylesheet, filled with a plausible day. */}
        <div className="land__ledger" aria-hidden="true">
          <section className="ledger">
            <dl className="ledger__figures">
              <div className="ledger__figure ledger__figure--taken">
                <dd><Tally to={6} /></dd>
                <dt>Taken</dt>
              </div>
              <div className="ledger__figure ledger__figure--asked">
                <dd><Tally to={8} /></dd>
                <dt>Asked</dt>
              </div>
              <div className="ledger__figure">
                <dd><Tally to={10} /></dd>
                <dt>Scheduled</dt>
              </div>
            </dl>
            <div className="progress__bar">
              <span className="progress__fill" style={{ width: "60%" }} />
              <span className="progress__asked" style={{ width: "20%" }} />
              <span className="progress__unreached" style={{ width: "20%" }} />
            </div>
            <ul className="ledger__key">
              <li>
                <span className="ledger__swatch ledger__swatch--taken" />
                They answered
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
            <p className="progress__gap">
              <span className="ledger__ours">ours to fix</span>
              2 doses were never asked about — no reminder reached the phone.
            </p>
          </section>
        </div>

        {/* Spans both columns rather than sitting in the text one. Stacked
            under the argument it made the left side run long past the ledger
            beside it, and what happens to a recording of your mother's voice
            reads as an evasion when it is squeezed in as a column footnote. */}
      </section>

      <section className="land__features">
        <p className="land__eyebrow">What it actually does</p>
        <Reveal as="h2">Built around how medicine actually works.</Reveal>

        <ul className="feats">
          <Feature
            index={0}
            title="Your voice, not a chime"
            demo={
              <div className="demo demo--voice">
                <span className="phone__wave" />
                <span className="phone__wave" />
                <span className="phone__wave" />
                <span className="phone__wave" />
                <span className="phone__wave" />
              </div>
            }
          >
            You record the reminder once. They hear you say it, at every dose,
            for as long as the prescription lasts.
          </Feature>

          <Feature
            index={1}
            title="In the language they think in"
            demo={
              <div className="demo demo--telugu">
                <strong>Dolo 650</strong>
                <span>వేసుకోండి</span>
              </div>
            }
          >
            The screen, the spoken prompt and the listening are all in Telugu —
            and the medicine keeps the name you typed.
          </Feature>

          <Feature
            index={2}
            title="A course that ends by itself"
            demo={
              <div className="demo">
                <span className="course">Day 4 of 15 · ends 18 Sep</span>
              </div>
            }
          >
            Ten days means ten days. It stops on its own, so nobody has to
            remember to switch it off on day eleven.
          </Feature>

          <Feature
            index={3}
            title="Three tablets, one moment"
            demo={
              <div className="demo demo--count">
                <em>1 of 3</em>
                <span className="demo__dots">
                  <i className="on" />
                  <i />
                  <i />
                </span>
              </div>
            }
          >
            Three tablets after dinner is one moment, walked through one at a
            time — not three alarms anyone learns to ignore.
          </Feature>

          <Feature
            index={4}
            title="It wakes a locked phone"
            demo={
              <div className="demo demo--lock">
                <span className="demo__screen">MEDICINE TIME</span>
              </div>
            }
          >
            It lights up face-down, locked, and on silent — the times a
            reminder matters most.
          </Feature>

          <Feature
            index={5}
            title="You are told when it matters"
            demo={
              /* This card is about being TOLD, so the demo shows the thing
                 that arrives. It used to show the "ours to fix" mark, which
                 belongs to the honesty argument and is already made twice
                 above - so the picture was illustrating a different card than
                 the one it sits in. */
              <div className="demo demo--alert">
                <span className="demo__from">CareBridge</span>
                <strong>No answer about the 8:00 PM dose</strong>
                <span className="demo__when">emailed to you · 9:32 pm</span>
              </div>
            }
          >
            If nobody answers, CareBridge tries again — and when that goes
            unanswered too it stops guessing and comes to you, saying plainly
            whether the failure was theirs or ours.
          </Feature>
        </ul>
      </section>

      <section className="trail">
        <p className="land__eyebrow">When nobody answers</p>
        <Reveal as="h2" className="land__big">
          CareBridge doesn&rsquo;t give up at the first silence.
        </Reveal>
        <Reveal as="p" className="cases__lede" delay={80}>
          A dose nobody answers is not marked missed and forgotten. It is tried
          again, and then it becomes your problem to know about rather than theirs
          to have failed at.
        </Reveal>

        <ol className="trail__steps">
          <Reveal as="li" delay={0}>
            <span className="trail__when">8:00 pm</span>
            <strong>The reminder goes out</strong>
            <span>Their phone wakes and plays your voice.</span>
          </Reveal>
          <Reveal as="li" delay={90}>
            <span className="trail__when">no answer</span>
            <strong>Nothing comes back</strong>
            <span>The dose stays open. Nobody has failed yet.</span>
          </Reveal>
          <Reveal as="li" delay={180}>
            <span className="trail__when">8:10 pm</span>
            <strong>It asks again</strong>
            <span>A second reminder, ten minutes later.</span>
          </Reveal>
          <Reveal as="li" delay={270} className="trail__last">
            <span className="trail__when">still nothing</span>
            <strong>You are told</strong>
            <span>
              A notification, then an email — to everyone on the care team, each
              one separately.
            </span>
          </Reveal>
        </ol>
      </section>

      <section className="privacy" id="safety">
        <p className="land__eyebrow">Their health stays with the family</p>
        <Reveal as="h2" className="land__big">
          What we hold, and what we do with it.
        </Reveal>

        <ul className="privacy__cards">
          <Reveal as="li" delay={0}>
            <strong>Your recordings</strong>
            <span>
              Used to play the reminder, and for nothing else. Delete the
              medicine and the recording goes with it.
            </span>
          </Reveal>
          <Reveal as="li" delay={90}>
            <strong>Medicine photographs</strong>
            <span>Stored inside your account, shown on their screen at the dose.</span>
          </Reveal>
          <Reveal as="li" delay={180}>
            <strong>Who can see it</strong>
            <span>
              Only the people you invited to the care team. Nobody else, and no
              advertiser.
            </span>
          </Reveal>
          <Reveal as="li" delay={270}>
            <strong>A reminder, not a doctor</strong>
            <span>
              CareBridge does not advise, diagnose or replace a doctor. The
              schedule is the one you enter, and only as right as the
              prescription you were given.
            </span>
          </Reveal>
        </ul>
      </section>


      <section className="land__end">
        <Reveal as="h2">
          Go to work. CareBridge stays with them.
        </Reveal>
        {/* What it does, then what it costs you, then the button. Nothing here
            asks the reader to infer anything: what they do, what the other
            person gets, what happens when nobody answers - and only then how
            little it takes to start. */}
        <Reveal as="p" className="land__close" delay={120}>
          Leave a reminder in your own voice. They hear you at the right time.
        </Reveal>
        <Reveal as="p" className="land__close" delay={200}>
          And if a dose goes unanswered, CareBridge comes to you — a
          notification, then an email.
        </Reveal>
        <Reveal as="p" className="land__endSub" delay={280}>
          A few minutes to set up, and then it is one less thing you carry
          through the day.
        </Reveal>
        {/* The last line is hers, not ours. Everything above is what the
            product does; this is the sentence somebody using it would say. */}
        <Reveal as="p" className="land__last" delay={360}>
          I may be away from them. But I&rsquo;m still there.
        </Reveal>
        <Link className="btn-primary" to="/signin">
          Get started
        </Link>
      </section>

      <footer className="land__foot">
        <span className="land__brand land__brand--sm">
          <Mark />
          CareBridge
        </span>
        <span>Medicine reminders in your family's own voice.</span>
        <span className="land__fineprint">
          Not a medical device. <a href="#honest">What we do with your data</a>.
        </span>
      </footer>
    </main>
  );
}
