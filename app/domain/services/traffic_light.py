from enum import StrEnum


class TrafficLight(StrEnum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


def classify_balance(balance_cents: int, yellow_threshold_cents: int) -> TrafficLight:
    if balance_cents >= 0:
        return TrafficLight.GREEN
    if balance_cents >= -abs(yellow_threshold_cents):
        return TrafficLight.YELLOW
    return TrafficLight.RED

