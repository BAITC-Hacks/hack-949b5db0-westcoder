"""Choose reproducible demos from actual rows, never manufacture profiles."""
from datetime import timedelta
from dataclasses import asdict
from .models import EventRequest, iso_date, CALENDAR_START
from .filters import hard_filter


def build_demos(dataset):
    rows = dataset.contractors
    found = []
    for category, title, target in (("Фотограф", "Популярная категория", 4), ("Флорист", "Редкая категория", 1)):
        best = None
        for day in range(60):
            event = EventRequest("Алматы", (iso_date(CALENDAR_START) + timedelta(days=day)).isoformat(),
                                 "свадьба", category, 600000, 6, "русский")
            count = len(hard_filter(rows, event)[0])
            if best is None or count > best[0]:
                best = (count, event)
            if count >= target:
                break
        found.append({"title": title, "request": asdict(best[1]), "expected_eligible": best[0]})
    empty = {**found[0]["request"], "budget_kzt": 50000}
    found.append({"title": "Никто не подходит", "request": empty, "expected_eligible": 0})
    found.append({"title": "Категории нет", "request": {**empty, "city": "Зарубежье"}, "expected_eligible": 0})
    return found
