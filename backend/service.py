from dataclasses import asdict, replace
from datetime import timedelta
from .dataset import Dataset, ROOT
from .models import EventRequest, CALENDAR_START, CALENDAR_END, iso_date
from .filters import hard_filter
from .scoring import score
from .explanations import explain
from .relaxation import suggestions
from .semantic import SemanticMatcher
from .preferences import assess_preferences
from .brief import BriefParser


class RecommendationService:
    def __init__(self, dataset=None, semantic=None, brief_parser=None):
        self.dataset = dataset or Dataset()
        self.semantic = semantic or SemanticMatcher(ROOT / ".cache", enabled=False)
        self.brief_parser = brief_parser or BriefParser()

    def brief(self, payload):
        return self.brief_parser.parse(payload, self.dataset.metadata())

    def plan(self, payload):
        from .planning import plan_options
        return plan_options(self.dataset, payload)

    def recommend(self, payload):
        event = EventRequest.parse(payload)
        eligible, stats, excluded, details = hard_filter(self.dataset.contractors, event)
        similarities, mode = self.semantic.similarities(event, eligible, self.dataset.fingerprint,
                                                      refresh=payload.get("refresh_semantic", False))
        ranked = []
        for candidate in eligible:
            preference = assess_preferences(candidate.description, event.preferences)
            similarity = similarities.get(candidate.id) if similarities is not None else preference["value"]
            value, breakdown = score(candidate, event, similarity)
            ranked.append((value, candidate.id, candidate, breakdown, preference))
        ranked.sort(key=(lambda row: (row[2].price_from_kzt, row[1])) if event.sort_by == "price" else (lambda row: (-row[0], row[1])))
        recommendations = []
        for value, _, candidate, breakdown, preference in ranked[:3]:
            reasons, warnings, explanation = explain(candidate, event)
            recommendations.append({**asdict(candidate), "name": candidate.anon_name,
                                    "category": event.category, "score": value,
                                    "score_breakdown": breakdown, "reasons": reasons,
                                    "warnings": warnings, "explanation": explanation,
                                    "preference_evidence": preference["evidence"],
                                    "preference_conflicts": preference["conflicts"],
                                    "preference_unverified": preference["unverified"]})
        stats["recommended"] = len(recommendations)
        status = "matched" if eligible else "category_not_found" if not stats["category"] else "no_candidates"
        if status == "category_not_found":
            message = f"В каталоге для города «{event.city}» нет категории «{event.category}»."
        elif status == "no_candidates":
            message = f"В городе «{event.city}» есть {stats['category']} профилей этой категории, но ни один не проходит все условия."
        else:
            message = f"Найдено {len(eligible)} подходящих кандидатов. Показано {len(recommendations)}."
        return {"status": status, "message": message, "request": asdict(event),
                "total_candidates": stats["category"], "eligible_candidates": len(eligible),
                "recommendations": recommendations, "filter_stats": stats,
                "excluded_reasons": excluded, "excluded_candidates": details,
                "suggestions": suggestions(self.dataset.contractors, event, eligible),
                "semantic_mode": mode, "semantic_retry_allowed": mode in ("unavailable", "cache_unavailable"),
                "preference_mode": "embeddings" if mode == "embeddings" else "keywords" if event.preferences else "none",
                "dataset_sha256": self.dataset.fingerprint}

    def calendar(self, payload):
        event = EventRequest.parse(payload)
        days = []
        day, end = iso_date(CALENDAR_START), iso_date(CALENDAR_END)
        while day <= end:
            changed = replace(event, date=day.isoformat())
            eligible = hard_filter(self.dataset.contractors, changed)[0]
            days.append({"date": changed.date, "count": len(eligible)})
            day += timedelta(days=1)
        return {"request": asdict(event), "days": days,
                "calendar_start": CALENDAR_START, "calendar_end": CALENDAR_END}

    def team(self, payload):
        from .team import build_team
        return build_team(self.dataset, payload)
