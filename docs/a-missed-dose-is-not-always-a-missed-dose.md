# The medicine reminder that refuses to guess

It's 11:40pm and a woman in another city opens an app to check on her mother.

**8 of 10 doses taken.** There's a progress ring. Green above some threshold, amber below. Tonight it's amber.

So she scrolls back through the week looking for a pattern. Maybe it's the evening tablets. Maybe this is the start of something and it's time to have the conversation about moving closer. She doesn't call, because it's late, and because ringing your mother to ask whether she took her tablets is its own small insult.

Here's what actually happened that day.

Her mother's phone never finished pairing. The setup flow lost her on the notification permission screen, the one with two buttons that look basically identical. Two reminders were raised. Neither of them left the server, because there was no device to send them to.

The app didn't say any of that. It said 80%.

That number isn't a fact about an eighty-year-old woman. It's a fact about my software, with her name on it.

I built **CareBridge** after sitting with that problem for a while. It's medicine reminders that play in a family member's own recorded voice, on the theory that a familiar voice gets answered and a chime gets ignored. It runs today: two Cloud Run services, an Android app on a real handset, one household using it daily.

This post is what it does, how it's put together, and which bits of Google Cloud do which job. The code is [on GitHub](https://github.com/valetisreedevi/carebridge).

---

## One dose, end to end

**You record the reminder once.** Not a text field. Your actual voice, saying the actual sentence: *Amma, it's eight o'clock, time for your blood pressure tablet.*

Then you add the dose, the times, whether it's taken with food, and a photo of the strip. The photo matters more than I expected it to. A white tablet looks like every other white tablet.

If it's a ten-day course you say so, and it stops after ten days without anyone having to remember to stop it.

**You pair her phone with a code.** Ten characters, good for 72 hours, single use. It gets redeemed inside a database transaction so the same code can't be spent twice, and a wrong code, a used code and an expired code all come back with the same refusal, so there's nothing to learn by guessing at them.

Before you trust it with anything, there's a button that says **Test the locked screen**. Press it and ten seconds later her phone does exactly what it's going to do at 8pm. You get to watch it happen once, in the room, rather than finding out on a night that matters.

**8pm arrives.** Her phone is locked, face down, on silent. It lights up anyway. A tone rings for about two and a half seconds before the voice starts, which sounds like a fussy detail and isn't: the phone is usually across the room, and a voice that begins before she's looking at it is a voice she doesn't hear. Then your recording plays.

**She answers however she can.** She can just talk. If the household's language is Telugu then it's Telugu the whole way down, the screen and the spoken prompt and the listening and the reply, not an English app with translated labels stuck on it. The medicine name stays exactly as her daughter typed it, in the script she typed it in, because that's the one word nobody should get creative with.

Or she can press a very large button. The buttons don't go anywhere near the AI, they write the dose straight to the record. If the model is down or slow or just having a bad day, the tablet still gets logged.

She can snooze too. Ten minutes, twenty, whatever she says.

**If nobody answers**, a second reminder goes out ten minutes later. If that one gets nothing either, then at around the twenty-minute mark the system stops trying and tells a human instead. The care team gets a push notification, and an email follows five minutes behind it.

The email doesn't put the medicine name in the subject line. It's going to land on somebody's lock screen, possibly in a room with other people in it.

**And the care team is an actual team.** One account covers everyone you look after, so your mother's mornings and your father's evenings live in the same place. You can invite your brother, your sister, the neighbour with a key. Each person gets told separately in their own message, so nobody ends up being the only one carrying it.

---

## Three numbers, not one

Back to that 80%.

An unanswered dose is four different things wearing the same word. She forgot, which is the case everyone assumes. Or she heard it and hasn't answered yet, and it's 8:02, so nobody has failed at anything. Or the phone was off, or flat, or in another room. Or it never got to her at all because no phone was ever set up.

Only the first one is about her. Two of them are about me.

So the dashboard doesn't show one number. It shows three: what the doctor prescribed, what we actually managed to ask her about, and what came back as an answer. They add up, which means a family can check my arithmetic instead of taking one number on trust.

A dose we never delivered doesn't get labelled *Missed*. It says **"Missed — no reminder sent."** Four extra words, and the meaning of the row moves from *she didn't* to *we didn't*.

When the numbers don't reconcile the dashboard says why, in a badge that names who's responsible: **ours to fix**. The bar segment for those doses isn't red either. It's hatched grey, deliberately not another shade of bad, because it isn't her failure.

One limit I should state plainly, and the product's own documentation states it too. CareBridge knows it had a registered device to send to. It doesn't know the notification arrived. Nothing short of an answer from her actually proves that, and I'd rather say so than let the word "delivered" do work it hasn't earned.

---

## How it's built

It's all Google Cloud. Two Cloud Run services, a FastAPI backend and a React dashboard, both built straight from source. Both sit at `--min-instances 0`, so a system nobody's currently using costs nothing to keep alive. The API caps at five instances and the web at three.

Here's the whole thing on one page:

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

**The tick.** Cloud Scheduler runs one job every minute against the reminder worker. That endpoint is guarded twice, with an OIDC identity token that Cloud Run checks and an application-level shared secret compared in constant time. Either one would probably be fine on its own. It's a URL that can make somebody's phone ring at 3am, so it has both.

**The read.** The worker asks Firestore which doses are due. Every dose is a small state machine (pending, reminder sent, snoozed, taken, declined, escalated, cancelled) and every transition gets validated inside a transaction. An illegal move returns a 409. A dose that's already taken can't be quietly reopened by a retry, or by the model, or by a caregiver double-tapping something.

**The push.** Firebase Cloud Messaging wakes the handset. Android gets data-only messages at high priority, which is deliberate: the system tray can't produce a full-screen wake on a locked phone, so the app has to own that behaviour rather than hand it to the OS. The tone is tagged as alarm audio so it sounds through silent and through Do Not Disturb, which is where an elderly person's phone tends to live.

**The answer, by two separate paths.** This is the part of the diagram I'd point at first. Speech goes to Gemini through the Agent Development Kit. A button press doesn't go near the model at all.

**The write.** Both paths end at the same transaction, and whatever decided it, the change gets re-validated server-side before anything is recorded.

**The ledger**, which is what her daughter reads at 11:40pm.

Some other things sit alongside that path. **Firebase Authentication** handles two quite different identities: caregivers sign in normally, while the elder's phone signs in with a custom token carrying an `elder_id` claim that's only minted after a pairing code is redeemed. Every call from that phone gets a revocation check, so "sign out all phones" takes effect immediately instead of whenever a cached token happens to expire. An elder device token is rejected outright if it ever shows up as a caregiver credential.

**Gemini 3.6 Flash** runs through the Agent Development Kit on Vertex AI. There are two agents and the split between them is the interesting bit. The companion agent talks to the elder and holds seven tools. The analyst agent that writes alert wording has zero tools and an eight-second timeout, so it can rephrase numbers it's handed and it can't touch a record. An alert never waits on a model; if the analyst is slow, deterministic wording ships instead.

**Cloud Text-to-Speech** speaks the agent's replies on the web client at 0.9× rate, which is slower than default and better for an older listener. It's cached so the same handful of phrases aren't re-synthesised and re-billed all day, it's behind a 5-second timeout with a browser fallback, and the endpoint requires a paired-elder token so only a real phone can spend synthesis quota.

**Cloud Storage** holds the photos and voice clips as time-limited signed URLs. **Secret Manager** holds the worker token and the mail password, granted per secret rather than project-wide, with the deploy output discarded so no token ends up in a build log.

The detail I'm most pleased with is the least interesting to look at. The deploy script doesn't only grant permissions, it removes them. Earlier versions had handed the API service account project-wide storage and token-signing rights, which was more than it ever needed. The script now narrows both down to the single media bucket and to the account signing as itself, and it deletes the old broad grants every time it runs.

Two things I should name so they don't get miscredited. Speech *recognition* isn't a Google Cloud service here, it's the browser's Web Speech API and Android's on-device recogniser. And the escalation email is ordinary SMTP, not a managed mail product.

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

Two attempts and then it stops. A system that keeps ringing an unanswered phone isn't being diligent, it's just being ignored, and what actually helps at that point is a person.

The email goes out one per recipient so a care team never gets accidentally introduced to itself. A single group email would put the neighbour's address in front of the whole family, which isn't anyone's to hand out.

---

## The agent's hardest job is not answering

Ask most people what the AI does here and they'll guess *understands what she said*. It's closer to the opposite. The most important thing this agent does is decline to interpret.

An elderly person answering a phone at 8pm says things like *okay*. Or *I will*. Or *mm*. Or nothing at all. Every one of those is a plausible yes, and every one is also a plausible *I didn't hear you*.

So the instruction is blunt about it:

> Never treat an ambiguous reply as a confirmation. "Okay", "alright", "mm", "I will" and silence are not confirmations.

When the agent can't tell, it asks one short question, *Have you taken it just now?*, and if that still doesn't settle it then it records nothing and says so. The reminder carries on exactly as it would have. If it keeps happening the family gets told.

The reasoning is written into the prompt, and it's the sentence the whole system turns on:

> A confirmation nobody actually gave is the worst thing this system can produce: the family stop worrying, the reminder stops, and the tablet is still on the table.

A false negative costs a repeated reminder. A false positive costs everything the product is for. That asymmetry is the whole design.

Three other rules earn their place. Nothing gets said that a tool didn't return (*if a tool did not return it, you do not know it*), which is how you stop a language model inventing a dose. Medicine names are never translated or spelled out phonetically. And times never get reformatted: the tools hand the model a time already phrased the way that family says it, in their language, and the model repeats it back rather than deciding for a second time whether 7pm counts as evening or night.

None of that is enforced by the model, though. It's prompt-level, and the documentation says so rather than implying otherwise. What's actually enforced sits underneath it:

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

The tools take no `elder_id` parameter, so identity comes from the authenticated caller and there's no phrasing that gets you into another household's records. Every status change the model asks for gets re-validated in the same transaction as everything else.

The intelligence is allowed to be helpful. It isn't allowed to be the last line of defence.

---

## What I'd fix next

The companion agent has no timeout. The analyst got one and the elder-facing path didn't, which means a slow model can block her turn until Cloud Run gives up at 120 seconds. The clients degrade reasonably and the buttons still work, so it isn't catastrophic, but it's the one real hole in a failure design I'm otherwise happy with. I know exactly where it is and haven't fixed it yet.

The alerts tab is scoped to the caregiver rather than to the elder you're currently looking at, so with two parents in one account the badge counts both. That's a bug, not a decision.

There's no rate limiting, no retention policy, and no monitoring beyond whatever Cloud Run captures by default. The database security rules exist in the repo but aren't deployed; clients never touch the database directly so nothing is exposed, but I'd rather say that precisely than let a file sitting in a folder imply more than it does.

That list isn't modesty. It's the same discipline as the rest of the product, pointed at myself. A system that won't guess what an elderly woman meant shouldn't be guessing about its own security posture either.

None of this made CareBridge more impressive in a demo. What it did was make one number, the one an anxious person checks at 11:40pm from several hundred miles away, mean what it says.

Which felt like the part worth getting right.

---

*CareBridge: FastAPI on Cloud Run, Firestore, Firebase Auth and Cloud Messaging, Cloud Scheduler, Cloud Storage, Secret Manager, Cloud Text-to-Speech, and Gemini 3.6 Flash via the Agent Development Kit on Vertex AI. A React dashboard for the family, an Android app for the elder's phone. English and Telugu, end to end. Code at [github.com/valetisreedevi/carebridge](https://github.com/valetisreedevi/carebridge).*
