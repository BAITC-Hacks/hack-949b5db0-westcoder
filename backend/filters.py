from .models import same, contains, duration_not_applicable

# Order defines the funnel. Each excluded profile is counted exactly once.
STAGES = ("city", "category", "available", "format", "budget", "duration", "language")


def failures(candidate, event):
    checks = [
        ("city", "wrong_city", same(candidate.city, event.city)),
        ("category", "wrong_category", contains(candidate.categories, event.category)),
        ("available", "busy" if candidate.availability_known else "availability_unknown",
         candidate.availability_known and event.date not in candidate.busy_dates),
        ("format", "wrong_format", contains(candidate.event_formats, event.event_format)),
        ("budget", "price_unknown" if candidate.price_from_kzt is None else "over_budget",
         candidate.price_from_kzt is not None and candidate.price_from_kzt <= event.budget_kzt),
        ("duration", "duration_invalid" if not candidate.duration_data_valid else "duration_unknown" if candidate.max_hours is None else "too_short",
         event.duration_hours is None or candidate.duration_data_valid and (
             duration_not_applicable(candidate, event)
             or candidate.max_hours is not None and candidate.max_hours >= event.duration_hours)),
        ("language", "wrong_language", event.language is None or contains(candidate.languages, event.language)),
    ]
    return [(stage, reason) for stage, reason, passed in checks if not passed]


def hard_filter(candidates, event):
    stats = {"initial": len(candidates), **{stage: 0 for stage in STAGES}}
    excluded, eligible, details = {}, [], []
    for candidate in candidates:
        failed = failures(candidate, event)
        first_stage = failed[0][0] if failed else None
        for stage in STAGES:
            if stage == first_stage:
                break
            stats[stage] += 1
        if failed:
            reason = failed[0][1]
            excluded[reason] = excluded.get(reason, 0) + 1
            details.append({"id": candidate.id, "name": candidate.anon_name,
                            "reason": reason, "all_reasons": [r for _, r in failed]})
        else:
            eligible.append(candidate)
    return eligible, stats, excluded, details
