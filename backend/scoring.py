"""Explicit weights, no randomness and no hidden quality claims."""
import re
from .models import normalized

WEIGHTS = {"budget": 20, "semantic": 80}


def description_match(candidate, event):
    # Transparent lexical overlap, not an embedding or a quality/reputation claim.
    # Four-letter prefixes match common inflections: свадьба / свадебный.
    def terms(text):
        return {word[:4] for word in re.findall(r"[^\W\d_]+", normalized(text)) if len(word) >= 3}
    query = terms(f"{event.category} {event.event_format}")
    matches = query & terms(candidate.description)
    words = re.findall(r"[^\W\d_]+", normalized(candidate.description))
    examples = [next(word for word in words if word[:4] == prefix) for prefix in sorted(matches)]
    return (100 * len(matches) / len(query) if query else 0), examples


def score(candidate, event, semantic=None):
    # Entry prices are not quotes. Budget score measures remaining headroom only.
    price = candidate.price_from_kzt
    if price is None:
        raise ValueError("Scoring requires a candidate with a known price.")
    budget = (1 - price / event.budget_kzt) * 100 if event.budget_kzt else 100
    components = {"budget": round(max(0, min(100, budget)), 4)}
    if semantic is not None and event.sort_by != "price":
        components["semantic"] = round(max(0, min(1, semantic)) * 100, 4)
    denominator = sum(WEIGHTS[key] for key in components)
    total = round(sum(value * WEIGHTS[key] for key, value in components.items()) / denominator, 2)
    breakdown = {key: {"value": value, "weight": round(WEIGHTS[key] / denominator * 100, 4)}
                 for key, value in components.items()}
    return total, breakdown
