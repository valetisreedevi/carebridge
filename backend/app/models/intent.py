from enum import Enum


class ElderIntent(str, Enum):
    TAKEN = "TAKEN"
    SNOOZE = "SNOOZE"
    DECLINED = "DECLINED"
    QUESTION = "QUESTION"
    CONFUSED = "CONFUSED"
    UNKNOWN = "UNKNOWN"
