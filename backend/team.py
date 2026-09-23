"""Exact minimum-cost assignment. One contractor can fill at most one role."""
from dataclasses import asdict
from decimal import Decimal
from .models import EventRequest, ValidationError, normalized
from .filters import failures
from .explanations import explain
from .preferences import assess_preferences


def build_team(dataset, payload):
    if not isinstance(payload, dict):
        raise ValidationError({"request": "Ожидается JSON-объект."})
    roles = payload.get("roles")
    if not isinstance(roles, list) or not 1 <= len(roles) <= 5 or any(not isinstance(r, dict) for r in roles):
        raise ValidationError({"roles": "Выберите от одной до пяти ролей."})
    events = [EventRequest.parse({**payload, "category": role.get("category"),
                                  "duration_hours": role.get("duration_hours")}) for role in roles]
    if len({normalized(e.category) for e in events}) != len(events):
        raise ValidationError({"roles": "Каждая категория может быть выбрана только один раз."})
    eligible = [[c for c in dataset.contractors if c.price_from_kzt is not None
                 and all(stage == "budget" for stage, _ in failures(c, e))] for e in events]
    candidates = sorted({c.id: c for group in eligible for c in group}.values(), key=lambda c: c.id)
    memberships = [{c.id for c in group} for group in eligible]
    # mask -> (cost, IDs by role). Snapshot per contractor prevents duplicate use.
    empty = tuple("" for _ in roles)
    best = {0: (Decimal(0), empty)}
    for candidate in candidates:
        for mask, (cost, ids) in list(best.items()):
            for index, group in enumerate(memberships):
                if mask & (1 << index) or candidate.id not in group:
                    continue
                target = mask | (1 << index)
                assignment = list(ids)
                assignment[index] = candidate.id
                option = (cost + Decimal(str(candidate.price_from_kzt)), tuple(assignment))
                if target not in best or option < best[target]:
                    best[target] = option
    complete = best.get((1 << len(roles)) - 1)
    response = {"request": {**asdict(events[0]), "roles": [
        {"category": e.category, "duration_hours": e.duration_hours} for e in events]},
        "roles": [{"category": e.category, "eligible_candidates": len(group)} for e, group in zip(events, eligible)],
        "members": [], "total_from_kzt": None, "remaining_kzt": None,
        "minimum_required_kzt": float(complete[0]) if complete else None,
        "dataset_sha256": dataset.fingerprint,
        "note": "Сумма стартовых цен, не смета и не бронирование. Пакеты услуг и доступность требуют подтверждения."}
    if complete is None:
        response.update(status="no_team", message="Не удалось заполнить все роли разными подрядчиками. Проверьте бюджет, дату и часы каждой роли.")
    elif complete[0] > Decimal(str(events[0].budget_kzt)):
        response.update(status="over_budget", message="Самая доступная полная команда превышает общий бюджет.")
    else:
        response.update(status="matched", message="Собрана полная команда с минимальной суммой стартовых цен.",
                        total_from_kzt=float(complete[0]), remaining_kzt=float(Decimal(str(events[0].budget_kzt)) - complete[0]))
        by_id = {c.id: c for c in candidates}
        for event, id_ in zip(events, complete[1]):
            c = by_id[id_]
            reasons, warnings, explanation = explain(c, event)
            preference = assess_preferences(c.description, event.preferences)
            response["members"].append({**asdict(c), "name": c.anon_name, "category": event.category,
                "duration_hours": event.duration_hours, "reasons": reasons, "warnings": warnings,
                "explanation": explanation, "preference_evidence": preference["evidence"],
                "preference_conflicts": preference["conflicts"], "preference_unverified": preference["unverified"]})
    return response
