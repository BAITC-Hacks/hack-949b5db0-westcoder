from .models import duration_not_applicable


def money(value):
    return f"{value:,.0f}".replace(",", " ") + " ₸"


def explain(candidate, event):
    savings = event.budget_kzt - candidate.price_from_kzt
    reasons = [
        f"{candidate.city} · категория «{event.category}».",
        f"На {event.date} занятость в календаре не указана.",
        f"Поддерживает формат «{event.event_format}».",
        f"Цена от {money(candidate.price_from_kzt)}; запас бюджета — {money(savings)}.",
    ]
    if event.duration_hours is not None:
        if duration_not_applicable(candidate, event):
            reasons.append("Услуга не привязана к часам присутствия (по условиям датасета).")
        else:
            reasons.append(f"Лимит {candidate.max_hours:g} ч покрывает ваши {event.duration_hours:g} ч.")
    if event.language:
        reasons.append(f"Указан нужный язык: {event.language}.")
    warnings = []
    if candidate.synthetic:
        warnings.append("Синтетический профиль для хакатона.")
    if candidate.city_imputed:
        warnings.append("Город проставлен при подготовке датасета.")
    if candidate.price_imputed:
        warnings.append("Цена проставлена при подготовке датасета.")
    if candidate.max_hours is None and not duration_not_applicable(candidate, event):
        warnings.append("Максимальная длительность не указана.")
    quote = candidate.description[:260]
    if len(candidate.description) > 260:
        quote = quote.rsplit(" ", 1)[0] + "…"
    explanation = f"{candidate.anon_name}: " + " ".join(reasons[1:])
    if quote:
        explanation += f" Из описания профиля: «{quote}»"
    return reasons, warnings, explanation
