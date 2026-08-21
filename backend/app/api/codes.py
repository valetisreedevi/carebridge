"""Short codes a family reads to each other.

Two things in CareBridge are handed over by voice: the invite that adds a
second caregiver, and the code that pairs an elder's phone. Both are
credentials, both get read down a telephone, and both have to normalise the
same way — so they share one alphabet rather than drifting apart.
"""

import hashlib
import secrets

# No 0/O/1/I. Someone is reading this aloud to a person who may be holding the
# phone at arm's length.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 10


def new_code() -> str:
    """A fresh code, grouped for reading: PAQYA-DDW4N."""
    raw = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
    return f"{raw[:5]}-{raw[5:]}"


def hash_code(code: str) -> str:
    """What gets stored. The code itself is kept nowhere.

    Whoever holds one can reach a family member's medication record, so a
    leaked database must not hand over working codes.

    Normalised first, because the person typing it did not see it written
    down: case, dashes and spaces are all forgiven.
    """
    normalised = code.strip().upper().replace("-", "").replace(" ", "")
    return hashlib.sha256(normalised.encode()).hexdigest()
