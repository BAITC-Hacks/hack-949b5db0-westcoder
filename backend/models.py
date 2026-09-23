from dataclasses import dataclass
from datetime import date
import math
import re

CALENDAR_START = "2026-09-23"
CALENDAR_END = "2026-12-31"


def normalized(value):
    return " ".join(str(value or "").split()).casefold().replace("ё", "е")


def same(left, right):
    return normalized(left) == normalized(right)


def contains(values, value):
    return any(same(item, value) for item in values)


def finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def duration_not_applicable(candidate, event):
    # The supplied PDF defines null for deliverables without hourly presence.
    return candidate.duration_data_valid and candidate.max_hours is None and contains(
        ("Флорист", "Декоратор", "Подарки и сувениры"), event.category)


def iso_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Дата должна иметь формат YYYY-MM-DD.")
    return date.fromisoformat(value)


class ValidationError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("Проверьте параметры мероприятия.")


@dataclass(frozen=True)
class Contractor:
    id: str
    anon_name: str
    categories: tuple[str, ...]
    city: str
    price_from_kzt: float | None
    event_formats: tuple[str, ...]
    languages: tuple[str, ...]
    max_hours: float | None
    busy_dates: tuple[str, ...]
    description: str
    synthetic: bool
    city_imputed: bool
    price_imputed: bool
    availability_known: bool = True
    duration_data_valid: bool = True


@dataclass(frozen=True)
class EventRequest:
    city: str
    date: str
    event_format: str
    category: str
    budget_kzt: float
    duration_hours: float | None = None
    language: str | None = None
    preferences: str = ""
    sort_by: str = "style"

    @classmethod
    def parse(cls, payload):
        if not isinstance(payload, dict):
            raise ValidationError({"request": "Ожидается JSON-объект."})
        errors, values = {}, {}
        if "refresh_semantic" in payload and not isinstance(payload["refresh_semantic"], bool):
            errors["refresh_semantic"] = "Ожидается true или false."
        for key in ("city", "date", "event_format", "category"):
            value = payload.get(key)
            if not isinstance(value, str) or not value.strip() or len(value) > 150:
                errors[key] = "Укажите непустую строку длиной до 150 символов."
            else:
                values[key] = value.strip()
        if "date" in values:
            try:
                iso_date(values["date"])
                if not CALENDAR_START <= values["date"] <= CALENDAR_END:
                    errors["date"] = f"Календарь датасета: {CALENDAR_START} — {CALENDAR_END}."
            except ValueError:
                errors["date"] = "Укажите существующую дату в формате YYYY-MM-DD."
        for key in ("budget_kzt", "duration_hours"):
            value = payload.get(key)
            if key == "duration_hours" and value is None:
                values[key] = None
                continue
            if (not finite_number(value) or value < 0
                    or (key == "duration_hours" and value == 0)):
                errors[key] = "Ожидается неотрицательное число." if key == "budget_kzt" else "Укажите положительное число часов."
            else:
                values[key] = value
        language = payload.get("language")
        if language is not None and (not isinstance(language, str) or len(language) > 100):
            errors["language"] = "Язык должен быть строкой."
        else:
            values["language"] = language.strip() or None if language is not None else None
        preferences = payload.get("preferences", "")
        if not isinstance(preferences, str) or len(preferences) > 1500:
            errors["preferences"] = "Опишите пожелания текстом до 1500 символов."
        else:
            values["preferences"] = preferences.strip()
        sort_by = payload.get("sort_by", "style")
        if sort_by not in ("price", "style"):
            errors["sort_by"] = "Выберите сортировку price или style."
        else:
            values["sort_by"] = sort_by
        if errors:
            raise ValidationError(errors)
        return cls(**values)
