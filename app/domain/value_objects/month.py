from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class Month:
    value: date

    @classmethod
    def from_any_date(cls, value: date) -> "Month":
        return cls(date(value.year, value.month, 1))

    def add_months(self, amount: int) -> "Month":
        year = self.value.year
        month = self.value.month + amount
        year += (month - 1) // 12
        month = ((month - 1) % 12) + 1
        return Month(date(year, month, 1))

