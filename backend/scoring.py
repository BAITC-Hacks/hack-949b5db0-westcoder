"""Explicit weights, no randomness and no hidden quality claims."""
WEIGHTS = {"budget": 35, "format": 25, "language": 15, "duration": 10, "semantic": 15}


def score(candidate, event, semantic=None):
    # Entry prices are not quotes. Budget score measures remaining headroom only.
    budget = (1 - candidate.price_from_kzt / event.budget_kzt) * 100 if event.budget_kzt else 100
    components = {"budget": round(max(0, min(100, budget)), 4), "format": 100.0}
    if event.language is not None:
        components["language"] = 100.0
    if event.duration_hours is not None:
        components["duration"] = 100.0
    if semantic is not None:
        components["semantic"] = round(max(0, min(1, semantic)) * 100, 4)
    denominator = sum(WEIGHTS[key] for key in components)
    total = round(sum(value * WEIGHTS[key] for key, value in components.items()) / denominator, 2)
    breakdown = {key: {"value": value, "weight": round(WEIGHTS[key] / denominator * 100, 4)}
                 for key, value in components.items()}
    return total, breakdown
