# The medicine reminder that refuses to guess

It is 11:40pm. A woman in another city opens an app to check on her mother.

**8 of 10 doses taken.** A progress ring. Green above some threshold, amber below. Tonight it is amber.

She scrolls back through the week looking for a pattern. She wonders about the evening tablets. She wonders whether this is the start of something, and whether it is time to talk about moving closer. She does not call. It is late, and asking *did you take your tablets* is its own small insult.

Here is what actually happened.

Her mother's phone never finished pairing. The setup flow lost her on the notification permission screen — the one with two buttons that look the same. Two reminders were raised. Neither left the server for a device that existed.

The app did not say that. It said **80%**.

That number is not a fact about an eighty-year-old woman. It is a fact about the software, wearing her name.

**CareBridge** is what I built after sitting with that problem. Medicine reminders that play in a family member's own recorded voice — because a familiar voice gets answered and a chime gets ignored.

It runs today. Two Cloud Run services, an Android app on a real handset, and one household using it daily. This post is what it does, how it is put together, and which parts of Google Cloud carry which job.

The live app is at [carebridge-web-gdjifq5mea-uc.a.run.app](https://carebridge-web-gdjifq5mea-uc.a.run.app/), and the code is [on GitHub](https://github.com/valetisreedevi/carebridge).

---

## One dose, end to end

**You record the reminder once.** Not a text field — your actual voice, saying the actual sentence. *Amma, it's eight o'clock, time for your blood pressure tablet.*

You add the dose, the times, and whether it is taken with food. And a photo of the strip, because a white tablet looks like every other white tablet.

If it is a ten-day course, you say so. Ten days means ten days. It stops on its own, so nobody has to remember to stop it.

**You pair her phone with a code.** Ten characters, good for 72 hours, single use. It is redeemed inside a database transaction, so the same code cannot be spent twice. A wrong code, a spent code and an expired code all produce the identical refusal. There is nothing to learn by guessing.

Then, before you trust it with anything, you press **Test the locked screen**. Ten seconds later her phone does exactly what it will do at 8pm. You watch it happen once, in the room, instead of finding out on a night that matters.

**8pm arrives.** Her phone is locked, face-down, on silent. It lights up anyway. A tone rings for about two and a half seconds first. The phone is across the room. A voice that starts before she is looking at it is a voice she misses. Then your recording plays.

**She answers however she can.** She can speak. If the household's language is Telugu, then it is Telugu all the way down — the screen, the spoken prompt, the listening, and the reply. Not an English app with a translated label on it. The medicine name stays exactly as her daughter typed it, in the script it was written in, because that is the one word nobody should be creative with.

Or she can press one very large button. The buttons do not go anywhere near the AI. They write the dose directly. If the model is down, or slow, or having a bad day, the tablet still gets recorded.

She can also snooze. Ten minutes, or twenty, her choice.

**If nobody answers**, a second reminder goes out ten minutes later. If that goes unanswered too, at about the twenty-minute mark it stops trying and tells a person. The care team gets a push, then an email five minutes behind it.

The email does not name the medicine in the subject line. It will land on a lock screen, in a room that may have other people in it.

**And the care team is a team.** One account, everyone you look after — your mother's morning and your father's evening in the same place. Invite your brother, your sister, the neighbour who has a key. Each of them is told separately, in their own message, so nobody has to be the only one carrying it.

---

## Three numbers, not one

Now back to that 80%.

An unanswered dose is four different things wearing one word. She forgot. She heard it and hasn't answered yet — it is 8:02, nobody has failed. The phone was off, or flat, or in the next room. Or it never reached her at all, because no phone was ever set up.

Only one of those is about her. Two of them are about me.

So CareBridge does not show one number. It shows three: what the doctor prescribed, what we actually managed to ask about, and what came back as an answer. They add up. A family can check the arithmetic themselves, which is a different kind of object from one number you are asked to believe.

A dose we never delivered is not labelled *Missed*. It is labelled **"Missed — no reminder sent."** Four extra words, and the whole meaning of the row moves from *she didn't* to *we didn't*.

When the numbers do not reconcile, the dashboard says so, in a badge naming who is responsible: **ours to fix**. The bar segment for those doses is not red. It is hatched grey — deliberately not another shade of bad, because it is not her failure.

One honest limit, stated plainly here and in the product's own documentation: CareBridge knows it had a registered device to send to. It does not know the notification arrived. Nothing short of an answer from her proves that, and the system never pretends otherwise.

---

## How it is built

Everything runs on Google Cloud. Two Cloud Run services — a FastAPI backend and a React dashboard, each built straight from source. Both sit at `--min-instances 0`, so a system nobody is currently using costs nothing to keep alive. The API caps at five instances, the web at three.

Here is the whole thing on one page:

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

Now follow the 8pm dose through it.

**The tick.** Cloud Scheduler fires one job, every minute, at the reminder worker. That endpoint is guarded twice: an OIDC identity token Cloud Run itself checks, and an application-level shared secret compared in constant time. Either alone would probably do. It is a URL that can make somebody's phone ring at 3am, so it has both.

**The read.** The worker asks Firestore which doses are due. Every dose is a small state machine — pending, reminder sent, snoozed, taken, declined, escalated, cancelled — and every transition is validated *inside* a transaction. An illegal move gets a 409. A dose that is already taken cannot be quietly reopened, not by a retry, not by the model, not by a caregiver pressing something twice.

**The push.** Firebase Cloud Messaging wakes the handset. Android gets data-only messages, at high priority, deliberately. The system tray cannot produce a full-screen wake on a locked phone, so the app owns that behaviour instead of handing it to the OS. The tone is tagged as alarm audio, so it sounds through silent and through Do Not Disturb — which is where an elderly person's phone usually lives.

**The answer, by two separate paths.** This is the part of the diagram that matters most. If she speaks, the reply goes to Gemini through the Agent Development Kit. If she presses a button, it does not go near the model at all — it writes the dose directly.

**The write.** Both paths land on the same transaction. Whatever decided it, the state change is re-validated server-side before anything is recorded.

**The ledger.** Which is what her daughter reads at 11:40pm.

**Firebase Authentication handles two very different identities.** Caregivers sign in normally. The elder's phone signs in with a custom token carrying an `elder_id` claim, minted only after a pairing code is redeemed. Every call from that phone is verified with a revocation check, so *Sign out all phones* takes effect immediately rather than whenever a cached token happens to expire. An elder device token is explicitly rejected if it is ever presented as a caregiver credential.

**Gemini 3.6 Flash, through the Agent Development Kit, on Vertex AI.** Two agents, and the split is the interesting part. The companion agent talks to the elder and holds seven tools. The analyst agent that writes alert wording has **zero tools** and an eight-second timeout — it can rephrase numbers it is handed, and it cannot touch a record. An alert never waits on a model. If the analyst is slow, deterministic wording ships instead.

**Cloud Text-to-Speech** speaks the agent's replies on the web client. At 0.9× rate, for an older listener. Cached, so the same handful of phrases are not re-synthesised and re-billed all day. Behind a 5-second timeout, with a browser fallback. And the endpoint requires a paired-elder token, so only a real phone can spend synthesis quota.

**Cloud Storage** holds the photos and the voice clips, served as time-limited signed URLs. **Secret Manager** holds the worker token and the mail password. Access is granted per secret, not project-wide. The deploy output is discarded, so no token is ever echoed into a build log.

The detail I am most pleased with is the least glamorous. The deploy script does not only grant permissions — it **removes** them. Earlier versions had given the API service account project-wide storage and token-signing rights. The script now narrows both to the single media bucket and to the account signing as itself, and actively deletes the old broad grants every time it runs. The infrastructure repairs its own history.

Two things worth naming so they are not miscredited. Speech *recognition* is not a Google Cloud service here — it is the browser's Web Speech API and Android's on-device recogniser. And the escalation email is ordinary SMTP, not a managed mail product.

---

## When nobody answers

The other flow worth drawing is the one that runs when the first one gets no reply.

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

Two attempts, then it stops. A system that keeps ringing an unanswered phone is not being diligent, it is being ignored — and the thing that actually helps at that point is a human being.

The email lands one per recipient, so a care team is never accidentally introduced to itself. And the subject line never names the medicine, because it will appear on a lock screen in a room that may have other people in it.

---

## The agent's hardest job is not answering

Ask most people what the AI does here and they will guess *understands what she said*. It is the opposite. The most important thing this agent does is decline to interpret.

An elderly person answering a phone at 8pm says things like *okay*. Or *I will*. Or *mm*. Or nothing at all. Every one of those is a plausible yes. Every one of them is also a plausible *I didn't hear you*.

So the instruction is explicit about it:

> Never treat an ambiguous reply as a confirmation. "Okay", "alright", "mm", "I will" and silence are not confirmations.

When the agent cannot tell, it asks one short question — *Have you taken it just now?* — and if that still does not resolve it, it records nothing and says so. The reminder carries on exactly as it would have. If it keeps happening, the family is told.

The reasoning is written into the prompt, and it is the sentence the whole system turns on:

> A confirmation nobody actually gave is the worst thing this system can produce: the family stop worrying, the reminder stops, and the tablet is still on the table.

A false negative costs a repeated reminder. A false positive costs everything the product is for.

Three more rules earn their place. **Nothing is said that a tool did not return** — *if a tool did not return it, you do not know it*, which is how a language model stops inventing a dose. **Medicine names are never translated or spelled out phonetically**, because the wrong medicine name is the one mistake this system exists to prevent. And **times are never reformatted**: tools hand the model a time already phrased the way that family says it, in their language, and the model repeats it verbatim rather than deciding a second time whether 7pm is evening or night.

None of this is enforced by the model. It is prompt-level, and the product's own documentation says so plainly.

What *is* enforced sits underneath it:

```
   the model MAY                    only the server DECIDES
   ------------------------------   ------------------------------
   read the current reminder        whether a transition is legal
   ask a clarifying question        which elder this caller is
   phrase a reply in her language   whether a dose is already closed
   call a tool to REQUEST a change  what finally gets written
   record "I could not understand"
                                    and two very large buttons
   it may NOT                       reach the transaction
   ------------------------------   without the model at all
   pass an elder_id
   reopen a finished dose
   change a dose or a schedule
```

The tools take no `elder_id` parameter. Identity comes from the authenticated caller, so there is no phrasing that reaches another household's records. And every status change the model requests is re-validated in the same transaction as everything else.

The intelligence is allowed to be helpful. It is not allowed to be the last line of defence.

---

## What I would fix next

The companion agent has no timeout. The analyst got one, and the elder-facing path did not — a slow model can block her turn until Cloud Run gives up at 120 seconds. The clients degrade gracefully and the big buttons still work, but it is the one genuine hole in an otherwise careful failure design, and I know exactly where it is.

The alerts tab is scoped to the caregiver, not to the elder you are currently looking at. With two parents in one account, the badge counts both. It is a real bug, not a design choice.

There is no rate limiting, no retention policy, and no monitoring beyond whatever Cloud Run captures by default.

The database security rules exist in the repository, but they are not deployed. Clients never touch the database directly, so nothing is exposed. I would still rather say that precisely than let a file in a folder imply more than it does.

That list is not modesty. It is the same discipline as the rest of the product, pointed at myself. A system that will not guess what an elderly woman meant should not guess what its own security posture is either.

---

None of this made CareBridge more impressive in a demo.

It made one number — the one an anxious person checks at 11:40pm, several hundred miles from her mother — mean what it says.

That seemed like the part worth getting right.

---

*CareBridge: FastAPI on Cloud Run, Firestore, Firebase Auth and Cloud Messaging, Cloud Scheduler, Cloud Storage, Secret Manager, Cloud Text-to-Speech, and Gemini 3.6 Flash via the Agent Development Kit on Vertex AI. A React dashboard for the family, an Android app for the elder's phone. English and Telugu, end to end. The code is at [github.com/valetisreedevi/carebridge](https://github.com/valetisreedevi/carebridge).*
