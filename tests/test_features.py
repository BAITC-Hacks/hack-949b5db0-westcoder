from dataclasses import asdict, replace
from itertools import permutations
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.dataset import Dataset, normalize
from backend.demos import build_demos
from backend.filters import hard_filter, failures
from backend.models import EventRequest, ValidationError
from backend.preferences import assess_preferences
from backend.semantic import SemanticMatcher
from backend.service import RecommendationService


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.dataset = Dataset()
        self.service = RecommendationService(self.dataset)
        self.payload = build_demos(self.dataset)[0]['request']

    def fixture(self, candidates):
        dataset = type('Fixture', (), {'contractors':tuple(candidates), 'fingerprint':'fixture'})()
        return RecommendationService(dataset)

    def profile(self, id_, categories=('Фотограф',), price=100):
        return normalize({'id':id_, 'anon_name':id_, 'categories':categories, 'city':'Алматы',
                          'price_from_kzt':price, 'busy_dates':[], 'event_formats':['свадьба'],
                          'languages':['русский'], 'max_hours':8, 'description':'Описание профиля.'})

    def team_payload(self, budget=1000):
        return {**self.payload, 'budget_kzt':budget, 'roles':[
            {'category':'Фотограф', 'duration_hours':6}, {'category':'Ведущий', 'duration_hours':2}]}

    def test_calendar_matches_independent_filter_for_all_days(self):
        with patch.object(self.service.semantic, 'similarities', side_effect=AssertionError('No embeddings for calendar')):
            result = self.service.calendar(self.payload)
        self.assertEqual(len(result['days']), 100)
        self.assertEqual(result['days'][0]['date'], '2026-09-23')
        self.assertEqual(result['days'][-1]['date'], '2026-12-31')
        for day in result['days']:
            request = EventRequest.parse({**self.payload,'date':day['date']})
            self.assertEqual(day['count'],len(hard_filter(self.dataset.contractors,request)[0]))

    def test_calendar_obeys_language_hours_budget_and_unknown_availability(self):
        candidate = self.profile('A')
        svc = self.fixture([candidate, replace(candidate,id='B',availability_known=False)])
        for changes, expected in (({},1),({'budget_kzt':99},0),({'language':'английский'},0),({'duration_hours':9},0)):
            result = svc.calendar({**self.payload,**changes})
            self.assertTrue(all(d['count']==expected for d in result['days']))

    def test_two_changes_rescue_empty_results_and_all_offers_are_exact(self):
        payload = {**self.payload,'budget_kzt':50000,'duration_hours':24}
        result = self.service.recommend(payload)
        self.assertEqual(result['eligible_candidates'],0)
        pairs = [s for s in result['suggestions'] if set(s['changes'])=={'budget_kzt','duration_hours'}]
        self.assertTrue(pairs)
        for s in result['suggestions']:
            changed = EventRequest.parse({**payload,**s['changes']})
            count = len(hard_filter(self.dataset.contractors,changed)[0])
            self.assertEqual(count,s['eligible_candidates'])
            self.assertGreater(count,0)

    def test_preferences_change_ranking_but_price_mode_stays_cheapest(self):
        quiet = replace(self.profile('quiet',price=200),description='Спокойная, деликатная подача.')
        loud = replace(self.profile('loud',price=100),description='Энергичное шоу и конкурсы.')
        svc = self.fixture([quiet,loud])
        request = {**self.payload,'budget_kzt':1000,'preferences':'спокойный','sort_by':'style'}
        result = svc.recommend(request)
        self.assertEqual(result['recommendations'][0]['id'],'quiet')
        self.assertEqual(result['preference_mode'],'keywords')
        self.assertIn('Спокойная',result['recommendations'][0]['preference_evidence'][0]['excerpt'])
        self.assertEqual(svc.recommend({**request,'sort_by':'price'})['recommendations'][0]['id'],'loud')
        blocked = self.fixture([replace(quiet,busy_dates=(request['date'],))]).recommend(request)
        self.assertEqual(blocked['recommendations'],[])

    def test_negation_and_unknown_preferences_are_not_invented(self):
        self.assertEqual(assess_preferences('Проводим конкурсы.','без конкурсов')['value'],0)
        self.assertTrue(assess_preferences('Проводим конкурсы.','без конкурсов')['conflicts'])
        self.assertEqual(assess_preferences('Работаем без конкурсов.','без конкурсов')['value'],1)
        unknown = assess_preferences('Свадебный ведущий.','без конкурсов')
        self.assertEqual(unknown['evidence'],[])
        self.assertTrue(unknown['unverified'])

    def test_preferences_validation(self):
        for changes in ({'preferences':[]},{'preferences':'x'*1501},{'sort_by':'random'},{'sort_by':[]}):
            with self.assertRaises(ValidationError):EventRequest.parse({**self.payload,**changes})

    def test_demos_handle_single_profile_complete_grid_and_no_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'catalog.json'
            path.write_text(json.dumps([asdict(self.profile('A'))]),encoding='utf-8')
            ds=Dataset(path)
            demos=build_demos(ds)
            self.assertTrue(demos)
            for demo in demos:
                self.assertEqual(RecommendationService(ds).recommend(demo['request'])['eligible_candidates'],demo['expected_eligible'])
            path.write_text(json.dumps([asdict(replace(self.profile('A'),availability_known=False,busy_dates=None))]),encoding='utf-8')
            self.assertEqual(build_demos(Dataset(path)),[])

    def test_team_reserves_unique_profiles_and_finds_global_minimum(self):
        # Greedy selection of A for photography would block the cheap host.
        a=self.profile('A',('Фотограф','Ведущий'),100)
        b=self.profile('B',price=110)
        c=self.profile('C',('Ведущий',),400)
        svc=self.fixture([a,b,c])
        result=svc.team(self.team_payload(300))
        self.assertEqual(result['status'],'matched')
        self.assertEqual(result['total_from_kzt'],210)
        self.assertEqual([m['id'] for m in result['members']],['B','A'])
        self.assertEqual(result['remaining_kzt'],90)
        events=[EventRequest.parse({**self.team_payload(300),**role}) for role in self.team_payload(300)['roles']]
        oracle=min(sum(c.price_from_kzt for c in combo) for combo in permutations([a,b,c],2)
                   if all(not failures(c,e) for c,e in zip(combo,events)))
        self.assertEqual(result['total_from_kzt'],oracle)

    def test_team_budget_boundary_and_minimum_even_when_each_price_exceeds_budget(self):
        svc=self.fixture([self.profile('A',price=100),self.profile('B',('Ведущий',),200)])
        self.assertEqual(svc.team(self.team_payload(300))['status'],'matched')
        for budget in (0,50,299):
            result=svc.team(self.team_payload(budget))
            self.assertEqual(result['status'],'over_budget')
            self.assertEqual(result['minimum_required_kzt'],300)
            self.assertEqual(result['members'],[])

    def test_team_cannot_use_one_profile_twice_or_busy_profile(self):
        a=self.profile('A',('Фотограф','Ведущий'))
        self.assertEqual(self.fixture([a]).team(self.team_payload())['status'],'no_team')
        b=replace(self.profile('B',('Ведущий',)),busy_dates=(self.payload['date'],))
        self.assertEqual(self.fixture([self.profile('C'),b]).team(self.team_payload())['status'],'no_team')

    def test_fractional_team_prices_at_exact_budget(self):
        svc=self.fixture([self.profile('A',price=0.1),self.profile('B',('Ведущий',),0.2)])
        result=svc.team(self.team_payload(0.3))
        self.assertEqual(result['status'],'matched')
        self.assertEqual(result['total_from_kzt'],0.3)
        self.assertEqual(result['remaining_kzt'],0)

    def test_team_respects_individual_hours_and_null_deliverables(self):
        photographer=self.profile('A')
        host=replace(self.profile('B',('Ведущий',)),max_hours=2)
        self.assertEqual(self.fixture([photographer,host]).team(self.team_payload())['status'],'matched')
        request=self.team_payload();request['roles'][1]['duration_hours']=3
        self.assertEqual(self.fixture([photographer,host]).team(request)['status'],'no_team')
        florist=replace(self.profile('C',('Флорист',)),max_hours=None)
        request['roles'][1]={'category':'Флорист','duration_hours':8}
        self.assertEqual(self.fixture([photographer,florist]).team(request)['status'],'matched')

    def test_team_validation(self):
        for roles in ([],[{}]*6,[None],[{'category':'Фотограф'},{'category':' фотограф '}],[{'category':'Фотограф','duration_hours':0}]):
            with self.assertRaises(ValidationError):self.service.team({**self.team_payload(),'roles':roles})

    def test_embedding_failure_retries_after_ttl_and_cache_keys_include_candidates(self):
        event=EventRequest.parse(self.payload)
        candidates=hard_filter(self.dataset.contractors,event)[0]
        with tempfile.TemporaryDirectory() as tmp:
            matcher=SemanticMatcher(tmp,enabled=True,api_key='test-key')
            with patch('backend.semantic.time.time',return_value=1000),patch.object(matcher,'_embed',side_effect=TimeoutError):
                self.assertEqual(matcher.similarities(event,candidates,'fp')[1],'unavailable')
            with patch('backend.semantic.time.time',return_value=1400),patch.object(matcher,'_embed',side_effect=lambda texts:[[1.,0.] for _ in texts]):
                self.assertEqual(matcher.similarities(event,candidates,'fp')[1],'embeddings')
                scores,_=matcher.similarities(event,candidates[:1],'fp')
                self.assertEqual(set(scores),{candidates[0].id})


if __name__=='__main__':unittest.main()
