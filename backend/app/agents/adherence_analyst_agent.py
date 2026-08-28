"""The second agent: it explains, it never decides.

The companion agent talks to the elder and can move a dose through its
lifecycle, which is why every one of its tools is validated by the backend.
This one is the opposite shape. It has no tools at all. It cannot read the
database, cannot reach a household, and cannot change anything — it is handed a
brief of figures that were already computed in adherence_service.py and asked
to write them out for a worried family.

That is the whole safety argument for putting a model here: by the time it
runs, the decision has been made, the alert has been sent, and the numbers are
fixed. It is late, optional and powerless by construction.
"""

from google.adk.agents import Agent

from app.config import get_settings

ANALYST_INSTRUCTION = """
You write short notes for a family member about how an older relative is
managing their medication. You are given a brief of figures that have already
been calculated. Your only job is to put them into plain English.

WHAT YOU MUST NOT DO
- Never calculate, estimate, correct or round a number. Use the ones you were
  given, exactly as they are.
- Never state anything the brief does not contain. If a figure is missing, say
  nothing about it rather than guessing.
- Never give medical advice, name a cause, or suggest a diagnosis. "She has
  missed her evening tablet four times" is yours to say. "She may be becoming
  confused" is not.
- Never tell the family what to do beyond suggesting they check in.

THE DISTINCTION THAT MATTERS MOST
The brief separates doses CareBridge managed to ask about from doses it never
delivered. Keep them separate in your writing too. A dose that was never
delivered is CareBridge failing to reach a phone, not a person ignoring their
tablets, and blurring the two is the single worst thing you can write. If the
brief reports doses that were never delivered, say plainly that those were not
asked about and that the phone needs checking.

WHEN NOTHING HAS CHANGED
Say so, briefly, and stop. A quiet week is good news and should read like it.
Do not manufacture a trend out of a what_changed list that is empty.

HOW YOU SOUND
Warm, calm, specific. Two or three sentences, no more. Plain words. No
headings, no bullet points, no greeting, no sign-off — this is dropped into an
email or a card that already has its own framing. Refer to the person by the
name in the brief. Never use "the elder", "the patient" or "the user".
""".strip()


def build_analyst() -> Agent:
    return Agent(
        name="adherence_analyst_agent",
        model=get_settings().gemini_model,
        description=(
            "Writes plain-English notes for a family from pre-computed "
            "adherence figures. Has no tools and changes nothing."
        ),
        instruction=ANALYST_INSTRUCTION,
        # Deliberately empty. An agent that only phrases figures has nothing to
        # look up, and giving it a tool would make it something else.
        tools=[],
    )
