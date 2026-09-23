from .models import duration_not_applicable
from .scoring import description_match


def money(value):
    amount = f"{value:,.2f}".rstrip("0").rstrip(".")
    return amount.replace(",", " ").replace(".", ",") + " ₸"


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
            spare = candidate.max_hours - event.duration_hours
            reasons.append(f"Лимит {candidate.max_hours:g} ч покрывает ваши {event.duration_hours:g} ч; запас — {spare:g} ч.")
    if event.language:
        reasons.append(f"Указан нужный язык: {event.language}.")
    text_score, terms = description_match(candidate, event)
    if terms:
        reasons.append(f"Слова по теме вашего события в описании: «{'», «'.join(terms)}».")
    warnings = []
    if candidate.synthetic:
        warnings.append("Синтетический профиль для хакатона.")
    if candidate.city_imputed:
        warnings.append("Город проставлен при подготовке датасета.")
    if candidate.price_imputed:
        warnings.append("Цена проставлена при подготовке датасета.")
    if not candidate.duration_data_valid:
        warnings.append("Длительность отсутствует или содержит некорректное значение.")
    elif candidate.max_hours is None and not duration_not_applicable(candidate, event):
        warnings.append("Максимальная длительность не указана.")
    quote = candidate.description[:260]
    if len(candidate.description) > 260:
        quote = quote.rsplit(" ", 1)[0] + "…"
    explanation = f"{candidate.anon_name}: " + " ".join(reasons[1:])
    if quote:
        explanation += f" Из описания профиля: «{quote}»"
    return reasons, warnings, explanation
