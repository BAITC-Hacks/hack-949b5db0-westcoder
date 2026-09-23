"""Choose reproducible demos from actual rows, never manufacture profiles."""
from datetime import timedelta
from collections import Counter
from dataclasses import asdict, replace
from .models import EventRequest, iso_date, CALENDAR_START, CALENDAR_END
from .filters import hard_filter


def build_demos(dataset):
    rows = dataset.contractors
    found = []
    counts = Counter(category for c in rows for category in c.categories)
    if not counts:
        return []
    popular = "Фотограф" if "Фотограф" in counts else min(counts, key=lambda c: (-counts[c], c))
    rare = "Флорист" if "Флорист" in counts else min(counts, key=lambda c: (counts[c], c))
    for category, title, target in ((popular, "Популярная категория", 4), (rare, "Редкая категория", 1)):
        profiles = [c for c in rows if category in c.categories and c.city and c.event_formats and c.price_from_kzt is not None]
        if not profiles:
            continue
        city = "Алматы" if any(c.city == "Алматы" for c in profiles) else profiles[0].city
        profiles = [c for c in profiles if c.city == city]
        formats = sorted({f for c in profiles for f in c.event_formats})
        event_format = "свадьба" if "свадьба" in formats else formats[0]
        profiles = [c for c in profiles if event_format in c.event_formats]
        languages = {language for c in profiles for language in c.languages}
        known_hours = [c.max_hours for c in profiles if c.max_hours is not None and c.max_hours > 0]
        hours = min(6, max(known_hours)) if known_hours else None
        best = None
        for day in range((iso_date(CALENDAR_END) - iso_date(CALENDAR_START)).days + 1):
            event = EventRequest(city, (iso_date(CALENDAR_START) + timedelta(days=day)).isoformat(),
                                 event_format, category, max(600000, min(c.price_from_kzt for c in profiles)),
                                 hours if known_hours else 6 if category in ("Флорист", "Декоратор", "Подарки и сувениры") else None,
                                 "русский" if "русский" in languages else None)
            count = len(hard_filter(rows, event)[0])
            if best is None or count > best[0]:
                best = (count, event)
            if count >= target:
                break
        found.append({"title": title, "request": asdict(best[1]), "expected_eligible": best[0]})
    found = [demo for demo in found if demo["expected_eligible"]]
    if not found:
        for candidate in rows:
            if (not candidate.city or not candidate.categories or not candidate.event_formats
                    or candidate.price_from_kzt is None):
                continue
            event = EventRequest(candidate.city, CALENDAR_START, candidate.event_formats[0],
                                 candidate.categories[0], candidate.price_from_kzt)
            for day in range((iso_date(CALENDAR_END) - iso_date(CALENDAR_START)).days + 1):
                changed = replace(event, date=(iso_date(CALENDAR_START) + timedelta(days=day)).isoformat())
                count = len(hard_filter(rows, changed)[0])
                if count:
                    found.append({"title": "Пример подбора", "request": asdict(changed), "expected_eligible": count})
                    break
            if found:
                break
    if not found:
        return []
    first = EventRequest.parse(found[0]["request"])
    eligible = hard_filter(rows, first)[0]
    minimum_price = min((c.price_from_kzt for c in eligible), default=0)
    empty = {**found[0]["request"], "budget_kzt": max(0, min(50000, minimum_price - 1))}
    # A free contractor may still pass a zero budget: do not advertise a false empty demo.
    if not hard_filter(rows, EventRequest.parse(empty))[0]:
        found.append({"title": "Никто не подходит", "request": empty, "expected_eligible": 0})
    absent = next(((city, category) for city in dataset.metadata()["cities"]
                  for category in dataset.metadata()["categories"]
                  if not any(c.city == city and category in c.categories for c in rows)), None)
    if absent:
        found.append({"title": "Категории нет", "request": {**empty, "city": absent[0], "category": absent[1]}, "expected_eligible": 0})
    return found
