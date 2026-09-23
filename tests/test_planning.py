from dataclasses import replace
from decimal import Decimal
from io import BytesIO
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend.brief import BriefParser, local_draft
from backend.dataset import Dataset, normalize
from backend.models import ValidationError, CALENDAR_START, CALENDAR_END
from backend.planning import plan_options
from backend.team import build_team


TEXT = 'Свадьба в Алматы 26.09.2026. Бюджет 2 млн тенге. Фотограф и ведущий на 6 часов. Русский язык.'


class BriefTests(unittest.TestCase):
    def setUp(self):
        self.meta = Dataset().metadata()

    def test_local_brief_extracts_facts(self):
        result = BriefParser().parse({'text': TEXT}, self.meta)
        draft = result['draft']
        self.assertEqual(result['mode'], 'local')
        self.assertEqual(draft['city'], 'Алматы')
        self.assertEqual(draft['date'], '2026-09-26')
        self.assertEqual(draft['budget_kzt'], 2_000_000)
        self.assertEqual(draft['duration_hours'], 6)
        self.assertEqual(set(draft['roles']), {'Фотограф', 'Ведущий'})
        self.assertEqual(result['missing'], [])

    def test_missing_values_and_guest_counts_are_not_invented(self):
        result = BriefParser().parse({'text': 'Праздник на 100 гостей, без ведущего. Нужен фотограф.'}, self.meta)
        self.assertIsNone(result['draft']['budget_kzt'])
        self.assertIsNone(result['draft']['date'])
        self.assertEqual(result['draft']['roles'], ['Фотограф'])
        self.assertIn('date', result['missing'])

    def test_currency_fractional_amount_and_invalid_date(self):
        draft = local_draft('Фотограф в Алматы 31.02.2026, 650 123,45 ₸, 0,25 часа.', self.meta)
        self.assertEqual(draft['budget_kzt'], 650123.45)
        self.assertEqual(draft['duration_hours'], .25)
        self.assertIsNone(draft['date'])
        self.assertIsNone(local_draft('В Алматы 2027-01-02 нужен фотограф.', self.meta)['date'])
        self.assertIsNone(local_draft('Фотограф, бюджет -100 тенге.', self.meta)['budget_kzt'])

    def test_ai_is_opt_in_and_key_is_required(self):
        for parser in (BriefParser(api_key='test'), BriefParser(enabled=True)):
            with patch.object(parser, '_generate', side_effect=AssertionError('No network')):
                self.assertEqual(parser.parse({'text': TEXT}, self.meta)['mode'], 'local')

    def test_openai_wire_format_and_structured_response(self):
        parser = BriefParser(enabled=True, api_key='test-only-key')
        draft = local_draft(TEXT, self.meta)
        response = {'status': 'completed', 'output': [{'type': 'message', 'content': [
            {'type': 'output_text', 'text': json.dumps(draft)}]}]}
        with patch('backend.brief.urlopen', return_value=BytesIO(json.dumps(response).encode())) as transport:
            result = parser.parse({'text': TEXT}, self.meta)
        self.assertEqual(result['mode'], 'openai')
        request = transport.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.openai.com/v1/responses')
        body = json.loads(request.data)
        self.assertFalse(body['store'])
        self.assertEqual(body['input'], TEXT)
        self.assertTrue(body['text']['format']['strict'])
        self.assertNotIn('test-only-key', json.dumps(result))

    def test_invalid_ai_output_and_provider_errors_fall_back(self):
        draft = local_draft(TEXT, self.meta)
        for bad in ({**draft, 'city': 'Invented city'}, {**draft, 'budget_kzt': True},
                    {**draft, 'roles': ['Фотограф', 'Фотограф']}, {**draft, 'budget_kzt': float('inf')},
                    {**draft, 'date': '2027-01-01'}, {'raw': 'not a draft'}):
            parser = BriefParser(enabled=True, api_key='test')
            with patch.object(parser, '_generate', return_value=bad):
                result = parser.parse({'text': TEXT}, self.meta)
            self.assertEqual(result['mode'], 'fallback')
            self.assertEqual(result['draft'], draft)
        with patch.object(parser, '_generate', side_effect=RuntimeError('secret provider error')):
            self.assertNotIn('secret', json.dumps(parser.parse({'text': TEXT}, self.meta)))

    def test_incomplete_or_refused_ai_does_not_overwrite_local_draft(self):
        for response in ({'status': 'incomplete'}, {'status': 'completed', 'output': [
            {'type': 'message', 'content': [{'type': 'refusal', 'refusal': 'No'}]}]}):
            parser = BriefParser(enabled=True, api_key='test')
            with patch('backend.brief.urlopen', return_value=BytesIO(json.dumps(response).encode())):
                self.assertEqual(parser.parse({'text': TEXT}, self.meta)['mode'], 'fallback')

    def test_rate_limit_and_validation(self):
        parser = BriefParser(enabled=True, api_key='test')
        with patch.object(parser, '_generate', return_value=local_draft(TEXT, self.meta)) as generate:
            for _ in range(11):
                result = parser.parse({'text': TEXT}, self.meta)
        self.assertEqual(generate.call_count, 10)
        self.assertEqual(result['mode'], 'fallback')
        for payload in (None, {}, [], {'text': 'short'}, {'text': 'x' * 1501}, {'text': True}):
            with self.assertRaises(ValidationError):
                parser.parse(payload, self.meta)


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.dataset = Dataset()
        self.payload = {'city': 'Алматы', 'date': '2026-09-26', 'event_format': 'свадьба',
                        'budget_kzt': 2_000_000, 'roles': [{'category': 'Фотограф'}, {'category': 'Ведущий'}]}

    def test_alternatives_are_real_unique_teams_within_reserve(self):
        result = plan_options(self.dataset, self.payload)
        self.assertEqual(result['spendable_kzt'], 1_800_000)
        self.assertEqual(result['reserve_kzt'], 200_000)
        self.assertTrue(result['alternatives'])
        for option in result['alternatives']:
            self.assertNotEqual(option['date'], self.payload['date'])
            self.assertLessEqual(abs(option['offset_days']), 7)
            team = build_team(self.dataset, {**self.payload, 'date': option['date'], 'budget_kzt': result['spendable_kzt']})
            self.assertEqual(team['status'], 'matched')
            self.assertEqual(team['total_from_kzt'], option['total_from_kzt'])
            self.assertEqual(len({c['id'] for c in option['members']}), 2)
            self.assertLessEqual(option['total_from_kzt'], result['spendable_kzt'])
        self.assertEqual(result, plan_options(self.dataset, self.payload))

    def test_calendar_bounds_and_reserve_validation(self):
        for date in (CALENDAR_START, CALENDAR_END):
            result = plan_options(self.dataset, {**self.payload, 'date': date})
            self.assertEqual(result['checked_dates'], 7)
            self.assertTrue(all(CALENDAR_START <= o['date'] <= CALENDAR_END for o in result['alternatives']))
        for reserve in (-1, 31, True, '10', float('nan'), 10**400):
            with self.assertRaises(ValidationError):
                plan_options(self.dataset, {**self.payload, 'reserve_percent': reserve})

    def test_zero_budget_and_no_matching_date(self):
        result = plan_options(self.dataset, {**self.payload, 'date': '2026-09-23', 'budget_kzt': 0})
        self.assertEqual(result['alternatives'], [])
        self.assertEqual(result['current']['status'], 'over_budget')

    def test_fractional_reserve_does_not_overstate_spendable_amount(self):
        result = plan_options(self.dataset, {**self.payload, 'budget_kzt': 100.05})
        self.assertEqual(result['reserve_kzt'], 10.01)
        self.assertEqual(result['spendable_kzt'], 90.04)
        self.assertEqual(Decimal(str(result['reserve_kzt']))+Decimal(str(result['spendable_kzt'])), Decimal('100.05'))

    def test_one_multirole_contractor_cannot_fill_two_roles(self):
        profile = normalize({'id': 'A', 'anon_name': 'A', 'city': 'Алматы', 'price_from_kzt': 1,
                             'categories': ['Фотограф', 'Ведущий'], 'busy_dates': [], 'event_formats': ['свадьба']})
        fixture = SimpleNamespace(contractors=(profile,), fingerprint='test')
        result = plan_options(fixture, self.payload)
        self.assertEqual(result['current']['status'], 'no_team')
        self.assertEqual(result['alternatives'], [])
