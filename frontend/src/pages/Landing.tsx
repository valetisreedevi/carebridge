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
          <div className="phone__pill" />
          <p className="phone__name">Amlodipine</p>
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

export default function Landing() {
  return (
    <main className="land">
      <header className="land__bar">
        <span className="land__brand">
          <Mark />
          CareBridge
        </span>
        <Link className="btn-primary btn-primary--sm" to="/signin">
          Sign in
        </Link>
      </header>

      <section className="land__hero">
        <div className="land__heroText">
          <p className="land__eyebrow">Two screens. One family.</p>
          <h1>
            You cannot be there<br />
            at eight in the morning.<br />
            <em>Your voice can.</em>
          </h1>
          <p className="land__lede">
            CareBridge is two halves of one thing. You set up the medicines and
            record a reminder in <em>your</em> own voice. CareBridge goes on
            their phone once — after that they never open it. At the right time
            it wakes itself and plays your voice: nothing to tap, nothing to
            read, nothing to remember. Then you see what actually happened, so
            you never have to ring and ask.
          </p>
          <div className="land__cta">
            <Link className="btn-primary" to="/signin">
              Get started
            </Link>
            <a className="land__quiet" href="#honest">
              How it stays honest
            </a>
          </div>
        </div>

        <Phone />
      </section>

      <section className="land__story">
        <Reveal as="p">
          A missed dose is almost never stubbornness. You have a shift to get
          to, a meeting that runs on, a child to collect. The person at home has
          four tablets a day and a strip that looks like every other strip, and
          nobody in the room to say which one is next. The only way to find out
          is to ring and ask, and be told yes, because they would rather not
          have you worrying.
        </Reveal>
        <Reveal as="p" className="land__strike" delay={140}>
          CareBridge asks for you, at the moment it matters, in a voice they
          will not ignore. Then it tells you what it actually heard.
        </Reveal>
      </section>

      <section className="land__steps">
        <ol>
          <Reveal as="li" delay={0}>
            <span className="land__num">1</span>
            <h3>You set it up, once</h3>
            <p>
              The medicine, the dose, which parts of the day, and how long the
              doctor prescribed for. Ten days means ten days — it stops on its
              own.
            </p>
          </Reveal>
          <Reveal as="li" delay={110}>
            <span className="land__num">2</span>
            <h3>Their phone does the rest</h3>
            <p>
              Even locked, even face-down, their phone plays the message you
              recorded — in their own language, beside a photograph of the
              tablet. It installs once on an Android phone, and they never have
              to open it again.
            </p>
          </Reveal>
          <Reveal as="li" delay={220}>
            <span className="land__num">3</span>
            <h3>One button, and you know</h3>
            <p>
              Or they say it out loud. If nobody answers, CareBridge tries again —
              and then it tells you, by notification and by email.
            </p>
          </Reveal>
        </ol>
      </section>

      {/* The two surfaces, side by side, because that IS the product: one
          screen at a side table and one wherever the family happens to be.
          Both are built from the app's own class names — .elder__* and
          .schedule__row and .ledger are the same rules the live product uses. */}
      <section className="show">
        <p className="land__eyebrow">The two people this is for</p>
        <Reveal as="h2">Their phone. Your dashboard.</Reveal>

        <div className="show__pair">
          <figure className="show__side">
            {/* The mock is decoration; the caption below it is the content. So
                the phone is hidden from assistive tech and its buttons are
                taken out of the tab order - a keyboard user was landing on
                three controls that do nothing - while the caption still
                reads. */}
            <div className="show__phone" aria-hidden="true">
              <div className="show__elder">
                <p className="elder__title">Medicine time</p>
                <div className="show__photo pill pill--teal" aria-hidden="true" />
                <p className="elder__medicine">Amlodipine</p>
                <p className="elder__dose">1 tablet</p>
                <p className="elder__food">after food</p>
                <button
                  className="elder__voice elder__voice--on"
                  type="button"
                  tabIndex={-1}
                >
                  <span className="elder__voiceMark">▶</span> Hear family
                </button>
                <button className="elder__mic" type="button" tabIndex={-1}>
                  Speak to CareBridge
                </button>
                <button
                  className="elder__button elder__button--taken"
                  type="button"
                  tabIndex={-1}
                >
                  I took it
                </button>
                <button
                  className="elder__button elder__button--later"
                  type="button"
                  tabIndex={-1}
                >
                  Remind me later
                </button>
              </div>
            </div>
            <figcaption>
              <strong>What they see.</strong> A photograph of the tablet, your
              voice on tap, and two ways to answer — a button, or just saying
              it out loud. Nothing to scroll, no way to get lost.
            </figcaption>
          </figure>

          <div className="show__link" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>

          <figure className="show__side show__side--wide">
            <div className="show__dash">
              <p className="dash__eyebrow">Today</p>
              <p className="dash__verdict dash__verdict--alert">
                Fever Tablet needs your attention
              </p>

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
              </section>

              <ul className="schedule show__rows">
                <li className="schedule__row schedule__row--good">
                  <span className="schedule__time">8:00 AM</span>
                  <span className="schedule__photo pill pill--teal" />
                  <span className="schedule__what">
                    <strong>Amlodipine</strong>
                    <span className="course">Day 4 of 15 · ends 18 Sep</span>
                  </span>
                  <span className="schedule__status">Taken</span>
                </li>
                <li className="schedule__row schedule__row--bad">
                  <span className="schedule__time">8:00 PM</span>
                  <span className="schedule__photo pill pill--amber" />
                  <span className="schedule__what">
                    <strong>Fever Tablet</strong>
                    <small>1 tablet · after food</small>
                  </span>
                  <span className="schedule__status">Needs you</span>
                </li>
                <li className="schedule__row schedule__row--waiting">
                  <span className="schedule__time">9:00 PM</span>
                  <span className="schedule__photo pill pill--slate" />
                  <span className="schedule__what">
                    <strong>Metformin</strong>
                    <small>1 tablet</small>
                  </span>
                  <span className="schedule__status">Waiting</span>
                </li>
              </ul>
            </div>
            <figcaption>
              <strong>What you see.</strong> The day at a glance, three honest
              numbers, and every dose coloured by what actually happened —
              including the ones we failed to deliver.
            </figcaption>
          </figure>
        </div>
      </section>

      <section className="land__honest" id="honest">
        <div className="land__honestText">
          <p className="land__eyebrow">Being straight with you</p>
          <Reveal as="h2">Three numbers, not one.</Reveal>
          <p>
            What the doctor prescribed. What CareBridge actually managed to
            ask about. And what came back as an answer. Three numbers, kept
            apart on purpose, because they are three different facts.
          </p>
          <p>
            When the numbers do not line up, CareBridge says <em>why</em>. A
            dose that was never delivered — a phone that was off, a reminder
            that never arrived — is marked as ours to fix, not as a dose
            somebody declined to take.
          </p>
          <p className="land__fineprint">
            Your recording, the photographs of the medicines and the record of
            who answered stay inside your own account. They are used to send
            the reminders and to show you this page, and for nothing else — not
            sold, not advertised against, not shared with anyone you have not
            invited to the care team. You can delete a medicine, and its
            recording goes with it.
          </p>
          <p className="land__fineprint">
            <strong>CareBridge reminds. It does not advise, diagnose, or
            replace a doctor.</strong> The schedule is the one you enter, and
            it is only ever as right as the prescription you were given.
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
              <div className="demo demo--alert">
                <span className="ledger__ours">ours to fix</span>
                <span>no reminder reached the phone</span>
              </div>
            }
          >
            If nobody answers, CareBridge tries again, then tells you — and says
            plainly whether the failure was theirs or ours.
          </Feature>
        </ul>
      </section>

      <section className="land__end">
        <Reveal as="h2">
          Go to work. CareBridge stays with them.
        </Reveal>
        <Reveal as="p" className="land__endSub" delay={120}>
          It takes a few minutes to set up, and then it is one less thing you
          carry through the day.
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
