# Your dashboard is blaming somebody's mother for your outage

It is 11:40pm. A woman in another city opens an app to check on her mother.

**8 of 10 doses taken.** A progress ring. Green above some threshold, amber below. Tonight it is amber.

She scrolls back through the week looking for a pattern. She wonders about the evening tablets. She wonders whether this is the start of something, and whether it is time to talk about moving closer. She does not call. It is late, and asking *did you take your tablets* is its own small insult.

Here is what actually happened.

Her mother's phone never finished pairing. The setup flow lost her on the notification permission screen — the one with two buttons that look the same. Two reminders were raised. Neither left our servers for a device that existed.

The app did not say that. It said **80%**.

That number is not a fact about an eighty-year-old woman. It is a fact about my software, wearing her name.

I built [CareBridge](https://github.com/valetisreedevi/carebridge) — medicine reminders in a family member's own recorded voice. Not the recording and not the scheduling: *this* became the problem the whole system is organised around.

---

## A missed dose isn't always a missed dose

Sit with an unanswered dose. Four different things end up under one word.

1. **She forgot.** The one case everybody assumes.
2. **She heard it and hasn't answered yet.** It is 8:02. Nobody has failed.
3. **The phone was switched off, or out of battery, or in the next room.** The reminder went out. It arrived nowhere.
4. **It never reached her at all.** No device paired, no permission, no delivery.

They are not the same thing, and only one of them is about the person at all.

`taken / scheduled` cannot tell them apart. Worse, it *asserts* they are the same. Three of the four are not about her. Two of them are about me.

Every product in this category ships that number anyway. It is the obvious one to show. The alternative means admitting things on a screen a customer is looking at.

---

## Three numbers. Not one.

The fix is structural, not cosmetic. Every dose gets classified along two independent axes.

**Reach** — did we manage to ask? *Ours to answer for.*
**Outcome** — what did she say? *Hers.*

They are orthogonal. Collapsing them into one percentage is the original sin.

Here is the reach classifier, in full:

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

Three states, not two. The third one earns its place.

A dose that hasn't come due yet has not failed. With only delivered and undelivered, tomorrow morning's tablets are undelivered right now, and the dashboard is amber at breakfast over doses nobody was meant to have taken. Cries wolf before breakfast. And a dashboard that cries wolf gets ignored on the day it is right.

`reached_a_phone` is stored, never derived. It only ever moves from false to true. A dose delivered once was genuinely asked about, whatever happened to the handset afterwards.

---

## Make the invariant a partition, then assert it

The ledger is a frozen dataclass. Its comments carry the whole argument:

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

Those two comments are the most load-bearing lines in the repository. Every argument about what a number means gets settled by asking which side of the line it falls on. I have not had to relitigate one since.

The identity in that docstring is not documentation. It is a partition, and it is enforced:

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

This is the part I would transplant into any other project. Once reach is a real partition, the family can check my arithmetic themselves. Three numbers that add up are a different kind of object from one number you are asked to believe. If they stop adding up, that is a bug in my accounting — not an ambiguity for an anxious person to absorb at midnight.

What the doctor prescribed. What we actually managed to ask about. What came back as an answer. Three different facts, kept apart on purpose.

Cancelled doses sit outside the partition, deliberately. A medicine the family stopped is not a dose anyone was asked to take. Leaving it in the denominator makes *stopping a medicine* look like a week of misses. The test says so out loud:

```python
"""Stopping a medicine must not read as a week of misses."""
```

That was a real bug before it was a rule.

---

## The denominator is where the honesty lives

One function, if I could only show one:

```python
def adherence_of_asked(ledger: Ledger) -> float | None:
    """Taken as a share of the doses we actually managed to ask about.

    Deliberately not over everything scheduled. Dividing by doses that were
    never delivered measures our own plumbing and reports the result as her
    behaviour.
    """
```

*Measures our own plumbing and reports the result as her behaviour.*

That sentence is the whole post. It is also uncomfortable to ship, because the honest denominator makes the product look worse in exactly the situations where the product **is** worse. When delivery gets flaky, `asked` drops. You end up staring at your own reliability instead of a comfortable number about somebody's mother.

The dishonest denominator launders your outages through someone else's adherence score.

That is the trade. It is why almost nobody makes it. It is not really a technical decision.

---

## Ours to fix, and we say so

An honest model that the interface averages away has achieved nothing. So the vocabulary survives all the way out.

The label for a dose that was never delivered is not "Missed":

```ts
MISSED: "Missed — no reminder sent",
```

Four extra words. They move the whole meaning of the row from *she didn't* to *we didn't*.

When the numbers don't reconcile, the dashboard says why, in a badge that names who is responsible:

> **ours to fix** — 2 doses were never asked about, no reminder reached the phone.

Not "2 missed". Not a red ring. A sentence admitting we failed — in a product built for people already inclined to blame themselves, and already inclined to blame their parents.

The bar segment for those doses isn't red either. The green is what they answered, the amber is still waiting, and the hatched grey is the part we never delivered. Deliberately not styled like a failure by a person. Because it isn't one.

One smaller detail I am fond of. Doses a caregiver marked taken on someone's behalf are counted separately, as `taken_on_trust`. They are real. They are not lies. But they are not the same evidence as an eighty-year-old pressing the button herself, and quietly merging the two would corrupt the one number the family most wants to lean on.

---

## Where I got it wrong. Twice.

Here is the part that makes me wince. It is also the part worth reading, because it shows what this way of thinking does *not* protect you from.

The endpoint the elder's phone polls — *what should I show right now?* — filtered on status alone. A dose stays open until somebody answers it. The only things that answer one are the elder, or a worker deciding it is exhausted. There was no comparison against the clock anywhere in that query.

So a dose raised while no phone was paired stayed *happening right now*. For ever. The next device to pair got handed it.

Somebody finished setting up their mother's phone and it immediately played her daughter's recorded voice about eye drops from four hours earlier.

The fix reuses a rule the domain already had: a dose stops being live once it passes its escalation window. Its docstring is now the longest in the service, because I did not want the next person to rediscover this:

```python
"""Every reminder still waiting on an answer, earliest first.

`live_within` is how long after its scheduled time a dose is still the
thing the elder is being asked about. Without it a reminder is open
until something closes it, and the only things that close one are an
answer from the elder or the worker deciding it is exhausted. A dose
raised while no phone was paired has neither, so it stayed open for
ever and was handed to the next device to pair — which then rang about
eye drops from hours ago the moment it finished pairing.
"""
```

Now the wince. **Three days later the same bug bit again, somewhere else.**

`/reminders/active` had been given its clock. `/my/today` — the elder's own day list, a different endpoint over the same events — never had one. No event is ever written as `MISSED`, so an unanswered dose sits in `REMINDER_SENT` indefinitely, and that screen mapped every open dose to "now".

The result: a screen reading **"Nothing to take right now"** directly above a row insisting a four-hour-old dose was due.

Same root cause. Same repository. Same week.

I had fixed the instance rather than the class. The most ordinary mistake there is.

I had been rigorous about *whose fault* a dose was and careless about *when* it was. Then, having noticed that, careless about how many places were careless about it.

---

## The transferable bit

Strip out the medicine. The shape holds for anything acting on behalf of someone who isn't watching — notifications, deliveries, alerting, IoT, dunning emails, any status page.

1. **Separate "did we deliver?" from "what did they do?"** Different questions. Different owners. One metric spanning both is a metric that assigns your failures to your users.
2. **Make the delivery axis a partition and assert it in a test.** Numbers that add up can be checked. Numbers that don't must be trusted, and trust is what you spend when you have run out of evidence.
3. **Never put undelivered attempts in the denominator of a user-behaviour metric.** That is the line where measuring your infrastructure becomes libelling your user.
4. **Carry the vocabulary to the interface.** "Missed" and "we never asked" must not render identically, or the model was decoration.
5. **Add a clock. Then go and find everywhere else that needs one.** Correct attribution of a stale fact is still a stale fact. And you almost certainly wrote the bug more than once.

None of this made CareBridge more impressive in a demo.

It made one number — the one an anxious person checks at 11:40pm, several hundred miles from her mother — mean what it says.

That seemed like the part worth getting right.

---

*CareBridge is a family medicine-care system: FastAPI on Cloud Run, Firestore, Gemini via the Agent Development Kit, a React caregiver dashboard, and an Android app for the elder's phone. Every snippet above is copied verbatim from the repository, which is at [github.com/valetisreedevi/carebridge](https://github.com/valetisreedevi/carebridge).*
