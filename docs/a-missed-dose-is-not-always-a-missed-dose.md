# The Hardest Part Wasn't the Reminder. It Was Knowing What Happened.

*CareBridge plays a medicine reminder in a family member's own recorded voice. The harder problem was telling a daughter the truth about what happened next.*

---

It's 7:55 in the morning and Meera is watching a meeting invite turn from grey to green.

Two hundred kilometres away, her mother is awake, in the kitchen, doing the small things people do before the day starts properly. On the counter there's a strip of tablets. One of them is due at eight.

Meera knows this. She knows it the way you know a thing that lives permanently at the back of your head, taking up room, never quite resolved.

She could text. Her mother reads texts about four hours late.

She could call, but she has ninety seconds and a meeting, and anyway there's something about phoning your mother to ask whether she's taken her tablets. It changes the shape of the relationship. You become the one who checks.

So she does what she does most mornings. Nothing. And carries it around all day.

*[VISUAL 1 — hero: a phone face-down on a kitchen counter beside a strip of tablets]*

---

## The problem nobody calls a problem

This isn't a medical emergency. Nobody is in danger this morning.

It's just distance, doing what distance does. A parent who's fine, mostly. A child who's competent and busy and four hours away. A tablet that gets taken about eighty percent of the time, and a low hum of worry that never fully switches off.

There are a lot of apps for this. They all do roughly the same thing: at eight o'clock, the phone makes a noise.

And the noise is the problem.

Because a notification tone is the same sound as a delivery update. It's the same sound as a bank alert, a group chat, a game she doesn't play asking her to come back. Her phone makes that sound forty times a day, and she has correctly learned to ignore it.

## A notification isn't a voice

The idea behind CareBridge is small enough to say in one sentence.

Instead of a chime at eight o'clock, her daughter's voice.

Meera records it once, herself, in her own words. *Amma, it's eight o'clock, time for your blood pressure tablet.* That recording is what plays. Not a synthesised approximation of a person, not text read aloud by a machine. Her.

The phone wakes up even though it's locked and face-down and on silent, because the reminder is tagged as alarm audio rather than a notification. A tone rings for about two and a half seconds before the voice starts, which sounds like a fussy implementation detail and isn't: the phone is usually across the room, and a voice that begins before she's looking at it is a voice she doesn't hear.

Then her daughter talks to her about her tablet.

That was the whole idea. I thought it was the product.

---

## Then: what if nobody answers?

Here's where it stopped being simple.

The reminder plays at eight. At 8:15, Meera opens the dashboard between meetings, and it says one of two things.

Either her mother took the tablet. Or she didn't.

And that second answer is a lie. Not a small one.

## A missed dose isn't always a missed dose

When a dose goes unanswered, at least four different things might have happened.

She forgot. That's the one everybody assumes, and it's the only one that's actually about her.

She heard it and hasn't answered yet. It's 8:02. She's mid-conversation, or the kettle's on. Nobody has failed at anything.

The phone was off, or flat, or in another room, or she'd left it charging in the bedroom. The reminder went out. It arrived nowhere.

Or it never reached her at all. The phone was never properly set up. The pairing didn't finish. Permission was never granted on that screen with the two buttons that look identical.

Only the first is about her mother.

Two of them are about my software.

And every reminder app I looked at rolls all four into one number and shows it to an already-anxious person as a fact about their parent. *8 of 10 doses taken.* Eighty percent. Amber.

That number isn't a fact about an eighty-year-old woman. It's a fact about the software, wearing her name.

---

## Scheduled, asked, answered, taken

The fix wasn't a better notification. It was refusing to collapse four states into two.

A dose moves through stages, and each stage belongs to somebody:

*⬇ DROP IMAGE HERE — d2_states.png (The Reminder State Model) ⬇*

**Scheduled** is what the doctor said. **Asked** means we got as far as a phone. **Answered** means she replied. **Taken** is what she told us.

The gaps between those stages are the entire product. A dose stuck between *scheduled* and *asked* is my failure. A dose sitting at *asked* at 8:02 isn't anyone's failure yet. Only a dose that reached *answered* tells you anything at all about her.

So the dashboard shows three numbers instead of one: what was prescribed, what we managed to ask about, and what came back. They add up. Meera can check my arithmetic instead of taking a percentage on trust.

*[VISUAL 2 — the dashboard: three numbers and the "ours to fix" badge]*

## When it's our fault, we say so

If two reminders never reached the phone, the dashboard doesn't say *2 missed*.

It says **ours to fix**, in a badge, naming who's responsible. The bar segment for those doses isn't red. It's hatched grey, deliberately not another shade of bad, because it isn't her failure and shouldn't be coloured like one. And the row itself reads **"Missed — no reminder sent."**

Four extra words. They move the meaning from *she didn't* to *we didn't*.

I want to be precise about a limit here, because it would be easy to overstate. CareBridge knows it had a registered device to send to. It doesn't know the notification arrived. Nothing short of an answer from her actually proves that, and the system never pretends otherwise. "We had somewhere to send it" is a weaker claim than "she got it," and it's the true one.

## And if nobody answers, a person finds out

One reminder at eight. A second at ten past. At around twenty minutes, it stops.

Two attempts, then it gives up.

A system that keeps ringing an unanswered phone isn't being diligent. It's being ignored. What actually helps at that point is a person, so at around twenty minutes CareBridge gives up and says so to somebody who can do something about it.

The email goes one message per recipient, so a care team never gets accidentally introduced to itself. And the subject line never contains the medicine name, because it's going to appear on a lock screen in a room that may have other people in it.

Care isn't usually one person, either. One account covers everyone you look after, and you can invite your brother, your sister, the neighbour with a key.

---

## How it actually works

*⬇ DROP IMAGE HERE — d1_workflow.png (End-to-End Care Workflow) ⬇*

Underneath that, the machinery:

*⬇ DROP IMAGE HERE — d4_layers.png (System Architecture) ⬇*

**Firestore holds the record**, and every dose is a small state machine. What matters is that transitions are validated *inside* a transaction: an illegal move returns a 409, and a dose that's already taken can't be quietly reopened by a retry, by the model, or by someone double-tapping a button. The states aren't a label on the data. They're enforced.

**Cloud Scheduler is the clock**, running the worker once a minute. That endpoint is guarded twice, with an OIDC identity token that Cloud Run checks and an application-level secret compared in constant time. Either would probably do alone. It's a URL that can make somebody's phone ring at three in the morning, so it has both.

**Firebase Cloud Messaging does the waking**, with data-only messages at high priority. That's deliberate: the system tray can't produce a full-screen wake on a locked phone, so the Android app has to own that behaviour rather than hand it to the OS.

**Two Cloud Run services** carry the API and the dashboard, both at `--min-instances 0`, so a system nobody's using costs nothing to keep running. **Cloud Storage** holds the recordings and photos, **Secret Manager** the credentials, granted per secret rather than project-wide.

One infrastructure detail I'm oddly proud of, and it's the least interesting to look at. The deploy script doesn't only grant permissions, it removes them. An earlier version had given the API service account project-wide storage and signing rights, far more than it needed. The script now narrows both and deletes the old broad grants every time it runs.

---

## Where the AI belongs, and where it doesn't

It would have been easy to put a language model in the middle of this. A hackathon mentions agents, so you reach for an agent.

That would have been the wrong call, and I want to explain why rather than just claim restraint.

The medication schedule is deterministic. State transitions are deterministic. What gets written to the record is decided by a transaction, not by a model. Those things are boring and they should stay boring, because the cost of getting them wrong is somebody's mother taking two doses of a blood pressure tablet.

Where a model genuinely helps is the conversation at the dose. An elderly person answering a phone at eight in the morning doesn't say "confirm." She says *okay*, or *I will*, or *mm*, or nothing at all.

And here's the thing about all of those: every one is a plausible yes, and every one is also a plausible *I didn't hear you*.

So the agent's most important job isn't understanding her. It's refusing to guess. The instruction is blunt about it:

> Never treat an ambiguous reply as a confirmation. "Okay", "alright", "mm", "I will" and silence are not confirmations.

When it can't tell, it asks one short question — *Have you taken it just now?* — and if that still doesn't settle it, it records nothing and says so. The reminder carries on exactly as it would have. If it keeps happening, the family gets told.

The reasoning is written into the prompt, and it's the sentence the whole system turns on:

> A confirmation nobody actually gave is the worst thing this system can produce: the family stop worrying, the reminder stops, and the tablet is still on the table.

A false negative costs a repeated reminder. A false positive costs everything the product is for. That asymmetry is the design.

Two other rules earn their place. Nothing gets said that a tool didn't return, which is how you stop a model inventing a dose. And medicine names are never translated or spelled out phonetically, because the wrong medicine name is the one mistake this whole thing exists to prevent.

None of that is enforced *by* the model, and I'd rather say so than imply otherwise. It's prompt-level. What's actually enforced sits underneath:

**The model may** read the current reminder, ask a clarifying question, reply in her language, request a change by calling a tool, and record that it couldn't understand her.

**It may not** pass an elder id, reopen a finished dose, or change a dose or a schedule.

**Only the server decides** whether a transition is legal, which elder the caller is, and what finally gets written.

There's a second agent that writes the wording of escalation alerts. It has zero tools and an eight-second timeout, so it can rephrase figures it's handed and it cannot touch a record. An alert never waits on a model.

And on the elder's screen there are two very large buttons that skip the agent entirely and write straight to the record. If Gemini is down, the tablet still gets logged.

The intelligence is allowed to be helpful. It isn't allowed to be the last line of defence.

---

## What it isn't

CareBridge is not a medical device. It doesn't diagnose, it doesn't prescribe, and it doesn't decide anything about anyone's treatment. The family sets the schedule; the software's only opinion is when to speak and what to admit.

The product's own footer says it plainly: *CareBridge reminds. It does not advise, diagnose, or replace a doctor.*

There's real access control underneath. Every request is checked against who's asking, cross-tenant access is refused and unit-tested, pairing codes are hashed and single-use, and a lost phone can be signed out immediately rather than whenever a cached token expires.

But I'm not going to list compliance acronyms. There's no rate limiting, no retention policy, and no monitoring beyond what Cloud Run captures by default. The database rules exist in the repository but aren't deployed. Clients never touch the database directly so nothing's exposed, but I'd rather say that precisely than let a file in a folder imply more than it does.

---

## What surprised me

I started this thinking the problem was reminders.

Get the voice right, get the phone to wake up, get the tone loud enough. That's a hard engineering problem and I spent weeks on it and it works.

Then I put it in front of a real household and discovered the reminder was the easy half. The hard half was the sentence on the dashboard the next morning. Because as soon as the software reports *anything*, it's making a claim about a person who isn't in the room to argue with it.

The second surprise was less flattering. I'd been rigorous about *whose fault* a dose was and completely careless about *when* it was — an unanswered dose stayed "happening right now" indefinitely, so a newly-paired phone would immediately announce a dose from four hours earlier. I fixed it. Three days later the same bug turned up somewhere else, in a different endpoint reading the same data, because I'd fixed the instance rather than the class.

Which is a very ordinary mistake, and it's the reason the honest-accounting thing isn't a pose. I need it. I'm the one who keeps getting this wrong.

## What's next

Decline exists in the model but has no button on either screen yet — you can only tell it you're not taking something by saying so out loud, which is backwards. The alerts view is scoped to the caregiver rather than the person you're looking at, so with two parents in one account the badge counts both. The elder-facing agent needs the timeout its sibling already has.

English and Telugu work end to end today. Hindi, Tamil and Kannada have voices but not the full path, and I'd rather ship two languages properly than five badly.

---

It's 8:04. Meera's meeting has started.

Two hundred kilometres away a phone lit up on a kitchen counter, rang for two and a half seconds, and then her daughter said *Amma, it's eight o'clock*.

Her mother pressed the big green button, said something to the phone that nobody recorded, and went back to her tea.

At 8:15, between two slides, Meera looks at her phone and sees the only three words that were ever worth building this for.

*She took it.*

Not eighty percent. Not a ring, not an amber warning, not an inference dressed up as a fact.

She couldn't be there.

But her voice could.

**CareBridge — still there, even when you're not.**

---

*Built with FastAPI on Cloud Run, Firestore, Firebase Auth and Cloud Messaging, Cloud Scheduler, Cloud Storage, Secret Manager, Cloud Text-to-Speech, and Gemini via the Agent Development Kit on Vertex AI. A React dashboard for the family and an Android app for the elder's phone, running in daily use in one home. Code at [github.com/valetisreedevi/carebridge](https://github.com/valetisreedevi/carebridge).*
