# She hears her daughter's voice at 8pm

It is 11:40pm. A woman in another city opens an app to check on her mother.

**8 of 10 doses taken.** A progress ring. Green above some threshold, amber below. Tonight it is amber.

She scrolls back through the week looking for a pattern. She wonders about the evening tablets. She wonders whether this is the start of something, and whether it is time to talk about moving closer. She does not call. It is late, and asking *did you take your tablets* is its own small insult.

Here is what actually happened.

Her mother's phone never finished pairing. The setup flow lost her on the notification permission screen — the one with two buttons that look the same. Two reminders were raised. Neither left the server for a device that existed.

The app did not say that. It said **80%**.

That number is not a fact about an eighty-year-old woman. It is a fact about the software, wearing her name.

CareBridge is what I built after sitting with that problem. Medicine reminders that play in a family member's own recorded voice. This post is what it does, how it is put together, and which parts of Google Cloud carry which job.

---

## One dose, end to end

**You record the reminder once.** Not a text field — your actual voice, saying the actual sentence. *Amma, it's eight o'clock, time for your blood pressure tablet.*

You add the dose, the times, and whether it is taken with food. And a photo of the strip, because a white tablet looks like every other white tablet.

If it is a ten-day course, you say so. Ten days means ten days. It stops on its own, so nobody has to remember to stop it.

**You pair her phone with a code.** Ten characters, good for 72 hours, single use. It is redeemed inside a database transaction, so the same code cannot be spent twice. A wrong code, a spent code and an expired code all produce the identical refusal. There is nothing to learn by guessing.

Then, before you trust it with anything, you press **Test the locked screen**. Ten seconds later her phone does exactly what it will do at 8pm. You watch it happen once, in the room, instead of finding out on a night that matters.

**8pm arrives.** Her phone is locked, face-down, on silent. It lights up anyway. A tone rings for about two and a half seconds first. The phone is across the room. A voice that starts before she is looking at it is a voice she misses. Then your recording plays.

**She answers however she can.** She can speak — the screen, the prompt and the listening are all in Telugu if that is the household's language. Or she can press one very large button. The buttons do not go anywhere near the AI. They write the dose directly. If the model is down, or slow, or having a bad day, the tablet still gets recorded.

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

Two Cloud Run services. A FastAPI backend and a React dashboard, each built straight from source. Both sit at `--min-instances 0`, so a system nobody is currently using costs nothing to keep alive. The API caps at five instances, the web at three.

**Firestore is the record.** Every dose is a small state machine — pending, reminder sent, snoozed, taken, declined, escalated, cancelled — and every transition is validated *inside* a transaction. An illegal move gets a 409. A dose that is already taken cannot be quietly reopened, not by a retry, not by the model, not by a caregiver pressing something twice.

**Cloud Scheduler is the heartbeat.** One job, every minute, calling the reminder worker. That endpoint is guarded twice: an OIDC identity token that Cloud Run itself checks, and an application-level shared secret compared in constant time. Either alone would probably do. It is a URL that can make somebody's phone ring at 3am, so it has both.

**Firebase Cloud Messaging wakes the handset.** Android gets data-only messages, at high priority, deliberately. The system tray cannot produce a full-screen wake on a locked phone. So the app owns that behaviour instead of handing it to the OS.

The reminder tone is tagged as alarm audio. It sounds through silent and through Do Not Disturb — which is where an elderly person's phone usually lives.

**Firebase Authentication handles two very different identities.** Caregivers sign in normally. The elder's phone signs in with a custom token carrying an `elder_id` claim, minted only after a pairing code is redeemed. Every call from that phone is verified with a revocation check, so *Sign out all phones* takes effect immediately rather than whenever a cached token happens to expire. An elder device token is explicitly rejected if it is ever presented as a caregiver credential.

**Gemini 3.6 Flash, through the Agent Development Kit, on Vertex AI.** Two agents, and the split is the interesting part. The companion agent talks to the elder and holds seven tools. The analyst agent that writes alert wording has **zero tools** and an eight-second timeout — it can rephrase numbers it is handed, and it cannot touch a record. An alert never waits on a model. If the analyst is slow, deterministic wording ships instead.

The model can move a dose through its lifecycle only by calling a tool that re-validates the move server-side, inside that transaction. It has no `elder_id` parameter to pass. Identity comes from the authenticated caller, so there is no phrasing that reaches another household's records.

**Cloud Text-to-Speech** speaks the agent's replies on the web client. At 0.9× rate, for an older listener. Cached, so the same handful of phrases are not re-synthesised and re-billed all day. Behind a 5-second timeout, with a browser fallback. And the endpoint requires a paired-elder token, so only a real phone can spend synthesis quota.

**Cloud Storage** holds the photos and the voice clips, served as time-limited signed URLs. **Secret Manager** holds the worker token and the mail password. Access is granted per secret, not project-wide. The deploy output is discarded, so no token is ever echoed into a build log.

The detail I am most pleased with is the least glamorous. The deploy script does not only grant permissions — it **removes** them. Earlier versions had given the API service account project-wide storage and token-signing rights. The script now narrows both to the single media bucket and to the account signing as itself, and actively deletes the old broad grants every time it runs. The infrastructure repairs its own history.

Two things worth naming so they are not miscredited. Speech *recognition* is not a Google Cloud service here — it is the browser's Web Speech API and Android's on-device recogniser. And the escalation email is ordinary SMTP, not a managed mail product.

---

## What I would fix next

The companion agent has no timeout. The analyst got one, and the elder-facing path did not — a slow model can block her turn until Cloud Run gives up at 120 seconds. The clients degrade gracefully and the big buttons still work, but it is the one genuine hole in an otherwise careful failure design, and I know exactly where it is.

The alerts tab is scoped to the caregiver, not to the elder you are currently looking at. With two parents in one account, the badge counts both. It is a real bug, not a design choice.

There is no rate limiting, no retention policy, and no monitoring beyond whatever Cloud Run captures by default.

The database security rules exist in the repository, but they are not deployed. Clients never touch the database directly, so nothing is exposed. I would still rather say that precisely than let a file in a folder imply more than it does.

---

None of this made CareBridge more impressive in a demo.

It made one number — the one an anxious person checks at 11:40pm, several hundred miles from her mother — mean what it says.

That seemed like the part worth getting right.

---

*CareBridge: FastAPI on Cloud Run, Firestore, Firebase Auth and Cloud Messaging, Cloud Scheduler, Cloud Storage, Secret Manager, Cloud Text-to-Speech, and Gemini 3.6 Flash via the Agent Development Kit on Vertex AI. A React dashboard for the family, an Android app for the elder's phone. English and Telugu, end to end. The code is at [github.com/valetisreedevi/carebridge](https://github.com/valetisreedevi/carebridge).*
