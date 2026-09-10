# The medicine reminder that refuses to guess

It's 11:40pm and a woman in another city opens an app to check on her mother.

**8 of 10 doses taken.** A progress ring, green above some threshold, amber below. Tonight it's amber.

So she scrolls back through the week looking for a pattern. Maybe it's the evening tablets. Maybe this is the start of something and it's time to have the conversation about moving closer. She doesn't call, because it's late, and because ringing your mother to ask whether she took her tablets is its own small insult.

Here's what actually happened. Her mother's phone never finished pairing. The setup flow lost her on the notification permission screen, the one with two buttons that look basically identical. Two reminders were raised, and neither of them left the server, because there was no device to send them to.

The app didn't say any of that. It said 80%.

That number isn't a fact about an eighty-year-old woman. It's a fact about my software, with her name on it.

I built **CareBridge** after sitting with that problem for a while. It's medicine reminders that play in a family member's own recorded voice, on the theory that a familiar voice gets answered and a chime gets ignored. It runs today: two Cloud Run services, an Android app on a real handset, one household using it daily.

Code is [on GitHub](https://github.com/valetisreedevi/carebridge).

---

## What CareBridge does

**Reminders in a real voice.** You record the sentence yourself, once. *Amma, it's eight o'clock, time for your blood pressure tablet.* Her phone plays that, not a synthesised chime.

**A medicine list built for people, not pharmacists.** Dose, times, with or without food, and a photo of the strip, because a white tablet looks like every other white tablet. Ten-day courses stop after ten days without anyone remembering to stop them.

**Pairing by code.** Ten characters, good for 72 hours, single use, redeemed inside a transaction so it can't be spent twice. Wrong, used and expired codes all return the same refusal, so there's nothing to learn by guessing.

**A self-test.** A button that says *Test the locked screen*. Ten seconds later her phone does exactly what it'll do at 8pm, so you watch it work once in the room rather than finding out on a night that matters.

**Two ways to answer.** She can talk, or she can press one very large button. The buttons bypass the AI entirely and write straight to the record.

**Telugu, properly.** Not an English app with translated labels. The screen, the spoken prompt, the listening and the reply are all in the household's language. The medicine name stays exactly as her daughter typed it, in her script.

**A care team, not a lone carer.** One account covers everyone you look after. Invite your brother, your sister, the neighbour with a key. Each person is messaged separately.

**Escalation to a human.** If two reminders get no answer, the system stops trying and tells someone.

---

## Three numbers, not one

Back to that 80%.

An unanswered dose is four different things wearing the same word. She forgot, which is the case everyone assumes. Or she heard it and hasn't answered yet, and it's 8:02, so nobody has failed at anything. Or the phone was off, or flat, or in another room. Or it never got to her at all because no phone was ever set up.

Only the first is about her. Two of them are about me.

So the dashboard doesn't show one number. It shows three: what the doctor prescribed, what we actually managed to ask about, and what came back as an answer. They add up, which means a family can check my arithmetic instead of taking one number on trust.

A dose we never delivered doesn't get labelled *Missed*. It says **"Missed — no reminder sent."** Four extra words, and the meaning of the row moves from *she didn't* to *we didn't*. When the numbers don't reconcile, a badge names who's responsible: **ours to fix**. That bar segment isn't red, it's hatched grey, deliberately not another shade of bad.

One limit, stated plainly here and in the product's own docs. CareBridge knows it had a registered device to send to. It doesn't know the notification arrived. Nothing short of an answer from her proves that, and I'd rather say so than let the word "delivered" do work it hasn't earned.

---

## Architecture

Everything runs on Google Cloud. Two Cloud Run services, a FastAPI backend and a React dashboard, both built straight from source and both at `--min-instances 0`, so a system nobody's using costs nothing to keep alive.

```
   Cloud Scheduler  * * * * *
          |  OIDC token + worker secret
          v
   +------------------+   due doses, state transitions
   |  reminder worker | <-------------------------> Firestore
   |  (Cloud Run)     |                             the record
   +------------------+
          |  FCM data-only, priority high
          v
   [ locked handset ]  tone 2.6s  ->  her daughter's voice
          |
     she speaks                        she presses
          |                                 |
          v                                 |
   Gemini 3.6 Flash (ADK, Vertex)           |  bypasses
   7 tools, no elder_id parameter           |  the agent
          |                                 |
          +----------> transaction <--------+
                       validate + write
                            |
                            v
                    ledger  ->  dashboard
```

Four components, and each one has a job the others can't do:

- **The record.** Firestore. Every dose is a small state machine: pending, reminder sent, snoozed, taken, declined, escalated, cancelled.
- **The clock.** Cloud Scheduler, once a minute, driving a worker on Cloud Run.
- **The reach.** Firebase Cloud Messaging into an Android app that owns the locked-screen wake.
- **The conversation.** Gemini via the Agent Development Kit, which can request changes but never makes them.

---

## How it works, step by step

**1. The tick.** Cloud Scheduler runs one job every minute against the reminder worker. That endpoint is guarded twice: an OIDC identity token Cloud Run checks, and an application-level shared secret compared in constant time. Either would probably be fine alone. It's a URL that can make somebody's phone ring at 3am, so it has both.

**2. The read.** The worker asks Firestore which doses are due. Every transition is validated inside a transaction, and an illegal move returns a 409. A dose that's already taken can't be quietly reopened by a retry, by the model, or by a caregiver double-tapping something.

**3. The push.** FCM wakes the handset. Android gets data-only messages at high priority, which is deliberate: the system tray can't produce a full-screen wake on a locked phone, so the app has to own that rather than hand it to the OS. The tone is tagged as alarm audio so it sounds through silent and Do Not Disturb, which is where an elderly person's phone tends to live.

**4. The ring, then the voice.** A tone plays for about two and a half seconds before the recording starts. That sounds fussy and isn't: the phone is usually across the room, and a voice that begins before she's looking at it is a voice she doesn't hear.

**5. The answer, by two separate paths.** Speech goes to Gemini through the ADK. A button press doesn't go near the model at all.

**6. The write.** Both paths land on the same transaction. Whatever decided it, the change is re-validated server-side before anything is recorded.

**7. The ledger**, which is what her daughter reads at 11:40pm.

And if nobody answers at all:

```
   t+0    reminder      attempt 1   phone rings, voice plays
            |
            |  no answer
            v
   t+10   reminder      attempt 2   same dose, same voice
            |
            |  still no answer
            v
   t+20   ESCALATE                  stop trying, tell a person
            |
            +--> push to the care team
            |
            +--> email, 5 minutes later
                 one message per recipient
                 no medicine name in the subject
```

Two attempts, then it stops. A system that keeps ringing an unanswered phone isn't being diligent, it's being ignored, and what actually helps at that point is a person.

The email goes one per recipient so a care team never gets accidentally introduced to itself. A single group email would put the neighbour's address in front of the whole family, which isn't anyone's to hand out. The subject line never names the medicine, because it's going to land on a lock screen in a room that may have other people in it.

---

## The Google Cloud stack

Ten APIs, all enabled from one block in the deploy script.

```
SERVICE                WHAT IT DOES, AND THE DELIBERATE PART
---------------------  ---------------------------------------
Cloud Run  x2          API + dashboard; min-instances 0
Firestore              the record; transitions inside a txn
Cloud Scheduler        fires the worker 1/min; OIDC + secret
Firebase Cloud Msg     wakes the handset; data-only, alarm
Firebase Auth          two identities; revocation checked
Vertex AI + Gemini     the conversation; analyst has 0 tools
Cloud Text-to-Speech   speaks the reply; cached, 0.9x, 5s cap
Cloud Storage          photos + voice; bucket-scoped role
Secret Manager         tokens; per-secret, never logged
Cloud Build            builds from source; 3 roles, not editor
```

A few of those deserve a sentence.

**Firebase Auth** handles two quite different identities. Caregivers sign in normally. The elder's phone signs in with a custom token carrying an `elder_id` claim, minted only after a pairing code is redeemed, and every call from that phone gets a revocation check so "sign out all phones" takes effect immediately instead of whenever a cached token expires. An elder device token is rejected outright if it ever shows up as a caregiver credential.

**Cloud Text-to-Speech** runs at 0.9× rate, slower than default and better for an older listener. It's cached so the same handful of phrases aren't re-synthesised and re-billed all day, and the endpoint requires a paired-elder token so only a real phone can spend synthesis quota.

**IAM** is the detail I'm most pleased with, and it's the least interesting to look at. The deploy script doesn't only grant permissions, it removes them. Earlier versions had handed the API service account project-wide storage and token-signing rights, which was more than it ever needed. The script now narrows both to the single media bucket and to the account signing as itself, and deletes the old broad grants every time it runs.

Two things worth naming so they don't get miscredited. Speech *recognition* isn't a Google Cloud service here, it's the browser's Web Speech API and Android's on-device recogniser. And the escalation email is ordinary SMTP, not a managed mail product.

---

## How the AI is constrained

Ask most people what the AI does here and they'll guess *understands what she said*. It's closer to the opposite. The most important thing this agent does is decline to interpret.

An elderly person answering a phone at 8pm says things like *okay*. Or *I will*. Or *mm*. Or nothing at all. Every one of those is a plausible yes, and every one is also a plausible *I didn't hear you*.

So the instruction is blunt about it:

> Never treat an ambiguous reply as a confirmation. "Okay", "alright", "mm", "I will" and silence are not confirmations.

When the agent can't tell, it asks one short question, *Have you taken it just now?*, and if that still doesn't settle it then it records nothing and says so. The reminder carries on exactly as it would have. If it keeps happening the family gets told.

The reasoning is written into the prompt, and it's the sentence the whole system turns on:

> A confirmation nobody actually gave is the worst thing this system can produce: the family stop worrying, the reminder stops, and the tablet is still on the table.

A false negative costs a repeated reminder. A false positive costs everything the product is for. That asymmetry is the whole design.

Three other rules earn their place. Nothing gets said that a tool didn't return (*if a tool did not return it, you do not know it*), which is how you stop a language model inventing a dose. Medicine names are never translated or spelled out phonetically. And times never get reformatted: the tools hand the model a time already phrased the way that family says it, and the model repeats it back rather than deciding for a second time whether 7pm counts as evening or night.

None of that is enforced by the model, though. It's prompt-level, and the documentation says so rather than implying otherwise. What's actually enforced sits underneath, and it splits three ways.

**The model may:** read the current reminder, ask one clarifying question, phrase a reply in her language, request a change by calling a tool, and record that it couldn't understand her.

**The model may not:** pass an `elder_id`, reopen a finished dose, or change a dose, a schedule or a food instruction.

**Only the server decides:** whether a transition is legal, which elder this caller actually is, whether a dose is already closed, and what finally gets written.

The tools take no `elder_id` parameter, so identity comes from the authenticated caller and there's no phrasing that gets you into another household's records. And the two large buttons on the elder's screen reach that transaction without the model being involved at all, which means a total Gemini outage still records a tablet.

There are two agents, and the split matters. The companion agent talks to the elder and holds seven tools. The analyst agent that writes alert wording has zero tools and an eight-second timeout, so an alert never waits on a model.

The intelligence is allowed to be helpful. It isn't allowed to be the last line of defence.

---

## What's missing

The companion agent has no timeout. The analyst got one and the elder-facing path didn't, so a slow model can block her turn until Cloud Run gives up at 120 seconds. The clients degrade reasonably and the buttons still work, so it isn't catastrophic, but it's the one real hole in a failure design I'm otherwise happy with.

The alerts tab is scoped to the caregiver rather than the elder you're currently looking at, so with two parents in one account the badge counts both. That's a bug, not a decision.

There's no rate limiting, no retention policy, and no monitoring beyond whatever Cloud Run captures by default. The database security rules exist in the repo but aren't deployed; clients never touch the database directly so nothing is exposed, but I'd rather say that precisely than let a file sitting in a folder imply more than it does.

That list isn't modesty. It's the same discipline as the rest of the product, pointed at myself. A system that won't guess what an elderly woman meant shouldn't be guessing about its own security posture either.

None of this made CareBridge more impressive in a demo. What it did was make one number, the one an anxious person checks at 11:40pm from several hundred miles away, mean what it says.

Which felt like the part worth getting right.

---

*CareBridge: FastAPI on Cloud Run, Firestore, Firebase Auth and Cloud Messaging, Cloud Scheduler, Cloud Storage, Secret Manager, Cloud Text-to-Speech, and Gemini 3.6 Flash via the Agent Development Kit on Vertex AI. A React dashboard for the family, an Android app for the elder's phone. English and Telugu, end to end. Code at [github.com/valetisreedevi/carebridge](https://github.com/valetisreedevi/carebridge).*
