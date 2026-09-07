# A missed dose isn't always a missed dose

Every medication reminder app I looked at shows the same number.

**8 of 10 doses taken.** 80%. A progress ring, probably green above some threshold and amber below it. It is the obvious number to show. It is also, in a specific and damaging way, a lie.

Because that number is computed as `taken / scheduled`. And `scheduled` includes doses where the reminder never arrived. A phone that was switched off. A notification permission nobody granted. A device that was never paired because the setup flow lost someone on step three. A push that failed silently at 2am and retried into a void.

All of those land in the denominator. All of them make the number go down. And the person reading that number — usually an adult child, several hundred miles away, already worried — reads it as a fact about their parent.

It isn't. It's a fact about your software, wearing their name.

I built [CareBridge](https://github.com/valetisreedevi/carebridge) — voice medication reminders for elderly parents, where the reminder plays in a family member's own recorded voice — and this became the design problem the whole system is organised around. Not the voice recording. Not the scheduling. This.

---

## Four different things wearing one word

Sit with an unanswered dose for a moment. There are at least four distinct realities behind it:

1. **They forgot.** The case everybody assumes, and the only one that's actually about the person.
2. **They heard it and haven't answered yet.** It's 8:02. Nobody has failed at anything.
3. **The phone was off, or flat, or in another room.** The reminder went out. It arrived nowhere.
4. **It never reached them at all.** No device paired, no permission, no delivery. Our failure entirely.

One number cannot tell those apart. Worse — one number *asserts* they're the same. And three of the four are not about the elderly person at all. Two of them are about me.

A test in the repo puts it more bluntly than I would have in a design doc:

> Almost every product in this category shows one number — taken over scheduled — which turns a phone nobody set up into a person ignoring their tablets.

---

## Two axes, not one

The fix turned out to be structural rather than cosmetic. Every dose gets classified along **two independent axes**:

- **Reach** — did we manage to ask? *Ours to answer for.*
- **Outcome** — what did they say? *Theirs.*

Those are orthogonal. Collapsing them into a single percentage is the original sin, and once they're separated most of the ambiguity evaporates.

Here's the reach classifier, in full:

```python
def classify_reach(event: dict) -> Reach:
    """A dose is only UNDELIVERED once we have actually tried and failed.

    A dose still ahead of its time has not failed at anything, and counting it
    against the household is how a dashboard cries wolf before breakfast.
    """
    if event.get("reached_a_phone"):
        return Reach.DELIVERED
    if event.get("attempt", 0) > 0:
        return Reach.UNDELIVERED
    return Reach.NOT_YET_TRIED
```

Three states, not two. The third one matters more than it looks: **a dose that hasn't come due yet is not a failure.** If you only have delivered/undelivered, tomorrow morning's tablets are undelivered right now, and your dashboard is red at breakfast for doses nobody was supposed to have taken.

`reached_a_phone` is a stored fact, not a derived one, and it has a deliberate asymmetry — it only ever moves from false to true. A dose that was successfully delivered once was genuinely asked about, whatever happened to the device afterwards.

The ledger that aggregates these is a frozen dataclass whose comments carry the whole argument:

```python
@dataclass(frozen=True)
class Ledger:
    """One window of doses, counted along both axes.

    REACH partitions the window exactly:

        scheduled == asked + unreachable + not_yet_due

    That identity is asserted in the tests. It is what lets the dashboard show
    three numbers that a family can add up themselves, instead of one number
    they have to trust.
    """

    scheduled: int = 0

    # Reach — ours to answer for.
    asked: int = 0
    unreachable: int = 0
    not_yet_due: int = 0

    # Outcome — hers.
    taken: int = 0
    declined: int = 0
    no_answer: int = 0
    waiting: int = 0
    cancelled: int = 0
```

Those two comments — `# Reach — ours to answer for.` and `# Outcome — hers.` — are the most load-bearing lines in the codebase. Every debate about what a number should mean gets settled by asking which side of that line it falls on.

---

## Make the invariant a partition, then test it

`scheduled == asked + unreachable + not_yet_due` isn't documentation. It's a partition, and it's enforced:

```python
@property
def balances(self) -> bool:
    return self.scheduled == self.asked + self.unreachable + self.not_yet_due
```

```python
assert ledger.scheduled == 6
assert ledger.asked == 4
assert ledger.unreachable == 1
assert ledger.not_yet_due == 1
assert ledger.balances
```

This is the part I'd transplant into any other project. Once the reach axis is a genuine partition, **the family can check the arithmetic themselves.** Three numbers that add up are a fundamentally different object from one number you're asked to believe. If they ever stop adding up, that's a bug in my accounting, not an ambiguity for the reader to absorb.

Cancelled doses sit outside the partition entirely — deliberately. A medicine the family stopped isn't a dose anyone was asked to take, and leaving it in the denominator makes *stopping a medicine* look like a week of misses. That was a real bug before it was a rule.

---

## The denominator is where the honesty actually lives

Here's the function I'd point at if I could only show one:

```python
def adherence_of_asked(ledger: Ledger) -> float | None:
    """Taken as a share of the doses we actually managed to ask about.

    Deliberately not over everything scheduled. Dividing by doses that were
    never delivered measures our own plumbing and reports the result as her
    behaviour.
    """
```

*Measures our own plumbing and reports the result as her behaviour.*

That sentence is the whole post. It's also an uncomfortable thing to build, because the honest denominator makes your product look worse in exactly the situations where your product **is** worse. If delivery is flaky, `asked` drops, and you're staring at your own reliability instead of a comfortable number about somebody's mother.

The dishonest denominator hides your outages inside someone else's adherence score. That's the trade, and it's why almost nobody makes it.

---

## It has to reach the interface, or it didn't happen

An honest data model that a UI averages away has achieved nothing. So the vocabulary survives all the way to the screen. The status label for a dose that was never delivered is not "Missed":

```ts
MISSED: "Missed — no reminder sent",
```

And when the numbers don't reconcile, the dashboard says why, in a badge that names the responsible party:

> **ours to fix** — 2 doses were never asked about, no reminder reached the phone.

Not "2 missed". Not a red ring. A sentence that says *we* failed, in a product built for people who are already inclined to blame themselves. The bar coloured for those doses isn't red either — it's a hatched grey, deliberately not styled like a failure by the person, because it isn't one.

There's a smaller detail I'm fond of: doses the caregiver marked taken on someone's behalf are counted separately as `taken_on_trust`. They're real, they're not lies, but they're not the same evidence as someone pressing the button themselves, and quietly merging the two would corrupt the one number the family most wants to rely on.

---

## Where I got it wrong

The discipline has an edge case I fell straight into, and it's worth telling because it shows what this way of thinking *doesn't* protect you from.

The endpoint the elder's phone polls — "what should I show right now?" — filtered on status alone:

```python
OPEN_STATUSES = frozenset({REMINDER_SENT, SNOOZED})
events = [e for e in self._for_elder(elder_id) if e["status"] in self.OPEN_STATUSES]
```

A dose stays open until somebody answers it. There was **no comparison against the clock anywhere in that query.** So a dose raised while no phone was paired stayed "happening right now" indefinitely, and the next device to pair got handed it — playing a family member's recorded voice about a dose from hours earlier, seconds after finishing setup.

I'd been rigorous about *whose fault* a dose was and careless about *when* it was. The fix reuses a rule the domain already had — a dose stops being live once it passes the escalation window — but the lesson is the general one: an honest state machine still needs a clock. "Open" and "happening now" are different propositions, and only one of them should ever drive a screen.

---

## The transferable bit

Strip out the medication and the shape stays useful for anything that acts on behalf of someone who isn't watching — notifications, deliveries, alerting, IoT, dunning emails:

1. **Separate "did we deliver?" from "what did they do?"** They are different questions with different owners. One metric that spans both is a metric that assigns your failures to your users.
2. **Make the delivery axis a partition and assert it in a test.** Numbers that add up can be checked. Numbers that don't must be trusted.
3. **Never put undelivered attempts in the denominator of a user-behaviour metric.** That's the specific line where measuring your infrastructure becomes libelling your user.
4. **Carry the vocabulary to the interface.** "Missed" and "we never asked" must not render identically, or the model was decoration.
5. **Add a clock.** Correct attribution of a stale fact is still a stale fact.

None of this made CareBridge more impressive in a demo. It made a specific number — the one an anxious person checks at 11pm, several hundred miles from their parent — mean what it says.

That seemed like the part worth getting right.

---

*CareBridge is a family medication-care system: FastAPI on Cloud Run, Firestore, Gemini via the Agent Development Kit, a React caregiver dashboard and an Android app for the elder's phone. The code is at [github.com/valetisreedevi/carebridge](https://github.com/valetisreedevi/carebridge).*
