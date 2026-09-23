from dataclasses import replace
from datetime import timedelta
from .filters import failures
from .models import CALENDAR_START, CALENDAR_END, iso_date
from .explanations import money


def suggestions(candidates, event, eligible):
    baseline_ids = {c.id for c in eligible}
    result = []

    def offer(field, value, label):
        changed = replace(event, **{field: value})
        ids = {c.id for c in candidates if not failures(c, changed)}
        extra = len(ids - baseline_ids)
        increase = len(ids) - len(baseline_ids)
        if increase > 0:
            result.append({"field": field, "value": value, "additional_candidates": increase,
                           "new_candidates": extra, "eligible_candidates": len(ids),
                           "text": f"{label} — подходящих станет {len(ids)} (+{increase})."})

    prices = sorted({c.price_from_kzt for c in candidates if c.price_from_kzt is not None
                     and c.price_from_kzt > event.budget_kzt
                     and all(stage == "budget" for stage, _ in failures(c, event))})
    if prices:
        offer("budget_kzt", prices[0], f"Увеличить бюджет до {money(prices[0])}")
    for offset in (1, -1, 2, -2, 3, -3, 7, -7):
        day = (iso_date(event.date) + timedelta(days=offset)).isoformat()
        if CALENDAR_START <= day <= CALENDAR_END:
            offer("date", day, f"Перенести мероприятие на {day}")
        if sum(r["field"] == "date" for r in result) >= 2:
            break
    if event.language:
        offer("language", None, "Не ограничивать язык")
    if event.duration_hours:
        limits = sorted({c.max_hours for c in candidates if c.max_hours is not None
                         and 0 < c.max_hours < event.duration_hours
                         and all(stage == "duration" for stage, _ in failures(c, event))}, reverse=True)
        if limits:
            offer("duration_hours", limits[0], f"Сократить длительность до {limits[0]:g} ч")
    return result[:4]
