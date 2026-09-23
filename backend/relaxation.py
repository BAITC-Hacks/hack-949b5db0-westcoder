from dataclasses import replace
from datetime import timedelta
from .filters import failures
from .models import CALENDAR_START, CALENDAR_END, iso_date
from .explanations import money
import json


def suggestions(candidates, event, eligible):
    baseline_ids = {c.id for c in eligible}
    result = []

    seen = set()

    def offer_changes(changes, label):
        signature = json.dumps(changes, sort_keys=True)
        if signature in seen:
            return
        seen.add(signature)
        changed = replace(event, **changes)
        ids = {c.id for c in candidates if not failures(c, changed)}
        extra = len(ids - baseline_ids)
        increase = len(ids) - len(baseline_ids)
        if increase > 0:
            result.append({"changes": changes, "additional_candidates": increase,
                           "new_candidates": extra, "eligible_candidates": len(ids),
                           "text": f"{label} — подходящих станет {len(ids)} (+{increase})."})

    def offer(field, value, label):
        offer_changes({field: value}, label)

    prices = sorted({c.price_from_kzt for c in candidates if c.price_from_kzt is not None
                     and c.price_from_kzt > event.budget_kzt
                     and all(stage == "budget" for stage, _ in failures(c, event))})
    if prices:
        offer("budget_kzt", prices[0], f"Увеличить бюджет до {money(prices[0])}")
    for offset in (1, -1, 2, -2, 3, -3, 7, -7):
        day = (iso_date(event.date) + timedelta(days=offset)).isoformat()
        if CALENDAR_START <= day <= CALENDAR_END:
            offer("date", day, f"Перенести мероприятие на {day}")
        if sum("date" in r["changes"] for r in result) >= 2:
            break
    if event.language:
        offer("language", None, "Не ограничивать язык")
    if event.duration_hours:
        limits = sorted({c.max_hours for c in candidates if c.max_hours is not None
                         and 0 < c.max_hours < event.duration_hours
                         and all(stage == "duration" for stage, _ in failures(c, event))}, reverse=True)
        if limits:
            offer("duration_hours", limits[0], f"Сократить длительность до {limits[0]:g} ч")
    singles = result[:4]
    result = []
    # Build concrete alternatives from near matches and verify the whole catalog.
    for candidate in candidates:
        failed = failures(candidate, event)
        reasons = {reason for _, reason in failed}
        if not 2 <= len(failed) <= 3 or not reasons <= {"over_budget", "too_short", "wrong_language", "busy"}:
            continue
        changes, labels = {}, []
        if "over_budget" in reasons:
            changes["budget_kzt"] = candidate.price_from_kzt
            labels.append(f"Бюджет {money(candidate.price_from_kzt)}")
        if "too_short" in reasons:
            if not candidate.max_hours:
                continue
            changes["duration_hours"] = candidate.max_hours
            labels.append(f"длительность {candidate.max_hours:g} ч")
        if "wrong_language" in reasons:
            changes["language"] = None
            labels.append("любой язык")
        if "busy" in reasons:
            available = [(abs((iso_date(day) - iso_date(event.date)).days), day)
                         for offset in range((iso_date(CALENDAR_END) - iso_date(CALENDAR_START)).days + 1)
                         if (day := (iso_date(CALENDAR_START) + timedelta(days=offset)).isoformat()) not in candidate.busy_dates]
            if not available:
                continue
            changes["date"] = min(available)[1]
            labels.append(f"дата {changes['date']}")
        offer_changes(changes, ", ".join(labels))
    result.sort(key=lambda r: (len(r["changes"]),
                              r["changes"].get("budget_kzt", event.budget_kzt) - event.budget_kzt,
                              -r["additional_candidates"], r["text"]))
    combined = singles + result[:2]
    for item in combined:
        if len(item["changes"]) == 1:
            item["field"], item["value"] = next(iter(item["changes"].items()))
    return combined
