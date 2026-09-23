from dataclasses import asdict
from .dataset import Dataset, ROOT
from .models import EventRequest
from .filters import hard_filter
from .scoring import score
from .explanations import explain
from .relaxation import suggestions
from .semantic import SemanticMatcher


class RecommendationService:
    def __init__(self, dataset=None, semantic=None):
        self.dataset = dataset or Dataset()
        self.semantic = semantic or SemanticMatcher(ROOT / ".cache", enabled=False)

    def recommend(self, payload):
        event = EventRequest.parse(payload)
        eligible, stats, excluded, details = hard_filter(self.dataset.contractors, event)
        similarities, mode = self.semantic.similarities(event, eligible, self.dataset.fingerprint,
                                                      refresh=payload.get("refresh_semantic", False))
        ranked = []
        for candidate in eligible:
            value, breakdown = score(candidate, event, similarities.get(candidate.id) if similarities is not None else None)
            ranked.append((value, candidate.id, candidate, breakdown))
        ranked.sort(key=lambda row: (-row[0], row[1]))
        recommendations = []
        for value, _, candidate, breakdown in ranked[:3]:
            reasons, warnings, explanation = explain(candidate, event)
            recommendations.append({**asdict(candidate), "name": candidate.anon_name,
                                    "category": event.category, "score": value,
                                    "score_breakdown": breakdown, "reasons": reasons,
                                    "warnings": warnings, "explanation": explanation})
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
                "dataset_sha256": self.dataset.fingerprint}
