"""Compare feasible teams on nearby dates, keeping every constraint explicit."""
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING

from .models import CALENDAR_START, CALENDAR_END, ValidationError, finite_number, iso_date
from .team import build_team


def plan_options(dataset, payload):
    if not isinstance(payload, dict):
        raise ValidationError({'request': 'Ожидается JSON-объект.'})
    reserve = payload.get('reserve_percent', 10)
    if not finite_number(reserve) or not 0 <= reserve <= 30:
        raise ValidationError({'reserve_percent': 'Резерв должен быть от 0 до 30%.'})
    original = build_team(dataset, payload)  # Validate the same contract as /api/team.
    total = Decimal(str(original['request']['budget_kzt']))
    reserve_kzt = min(total, (total * Decimal(str(reserve))).to_integral_value(rounding=ROUND_CEILING) / 100)
    spendable = total - reserve_kzt
    request = {**original['request'], 'budget_kzt': float(spendable)}
    current = build_team(dataset, request)
    options = []
    day = iso_date(request['date'])
    for offset in range(-7, 8):
        date = (day + timedelta(days=offset)).isoformat()
        if offset == 0 or not CALENDAR_START <= date <= CALENDAR_END:
            continue
        team = build_team(dataset, {**request, 'date': date})
        if team['status'] == 'matched':
            options.append({'date': date, 'offset_days': offset, 'total_from_kzt': team['total_from_kzt'],
                            'members': [{'id': c['id'], 'name': c['name'], 'category': c['category']} for c in team['members']]})
    options.sort(key=lambda o: (o['total_from_kzt'], abs(o['offset_days']), o['date']))
    return {'request': original['request'], 'reserve_percent': reserve, 'reserve_kzt': float(reserve_kzt),
            'spendable_kzt': float(spendable), 'current': current, 'alternatives': options[:3],
            'checked_dates': sum(CALENDAR_START <= (day + timedelta(days=i)).isoformat() <= CALENDAR_END for i in range(-7, 8) if i),
            'note': 'Проверены даты в пределах ±7 дней. Суммы — цены «от», резерв не гарантирует окончательную стоимость.'}
