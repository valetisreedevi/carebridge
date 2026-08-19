from enum import Enum


class FoodInstruction(str, Enum):
    BEFORE_FOOD = "BEFORE_FOOD"
    AFTER_FOOD = "AFTER_FOOD"
    WITH_FOOD = "WITH_FOOD"
    ANY_TIME = "ANY_TIME"


FOOD_INSTRUCTION_TEXT = {
    FoodInstruction.BEFORE_FOOD: "before food",
    FoodInstruction.AFTER_FOOD: "after food",
    FoodInstruction.WITH_FOOD: "with food",
    FoodInstruction.ANY_TIME: "at any time",
}


class Frequency(str, Enum):
    DAILY = "DAILY"
