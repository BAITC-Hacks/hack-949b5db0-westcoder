import hashlib
import json
from dataclasses import asdict, replace
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest
from backend.dataset import Dataset, DEFAULT_DATASET, normalize
from backend.demos import build_demos
from backend.filters import failures, hard_filter
from backend.models import EventRequest, ValidationError, iso_date, CALENDAR_START
from backend.scoring import score
from backend.service import RecommendationService


class RecommendationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = Dataset()
        cls.service = RecommendationService(cls.dataset)
        cls.demos = build_demos(cls.dataset)
        cls.event = EventRequest.parse(cls.demos[0]["request"])
        cls.profile = hard_filter(cls.dataset.contractors, cls.event)[0][0]

    def test_source_is_exact_original(self):
        self.assertEqual(len(self.dataset.contractors), 66)
        self.assertEqual(hashlib.sha256(DEFAULT_DATASET.read_bytes()).hexdigest(),
                         "6a724b6b7dfb5973343e68ba18dadb60fc807d87e3d78f03ee86fb26cb089f7d")

    def test_all_demos(self):
        for demo, expected in zip(self.demos, ("matched", "matched", "no_candidates", "category_not_found")):
            with self.subTest(demo=demo["title"]):
                result = self.service.recommend(demo["request"])
                self.assertEqual(result["status"], expected)
                self.assertEqual(result["eligible_candidates"], demo["expected_eligible"])
                self.assertLessEqual(len(result["recommendations"]), 3)

    def test_busy_never_passes_entire_calendar_and_catalog(self):
        for candidate in self.dataset.contractors:
            for offset in range(100):
                day = (iso_date(CALENDAR_START) + timedelta(days=offset)).isoformat()
                event = EventRequest(candidate.city, day, candidate.event_formats[0],
                                     candidate.categories[0], candidate.price_from_kzt)
                eligible = hard_filter([candidate], event)[0]
                self.assertEqual(bool(eligible), day not in candidate.busy_dates,
                                 f"{candidate.id} {day}")

    def test_every_returned_candidate_meets_all_constraints(self):
        for demo in self.demos:
            event = EventRequest.parse(demo["request"])
            result = self.service.recommend(demo["request"])
            for item in result["recommendations"]:
                candidate = next(c for c in self.dataset.contractors if c.id == item["id"])
                self.assertEqual(failures(candidate, event), [])
                self.assertTrue(0 <= item["score"] <= 100)

    def test_each_hard_constraint(self):
        cases = [("city", "Нет города", "wrong_city"), ("category", "Нет категории", "wrong_category"),
                 ("event_format", "Нет формата", "wrong_format"), ("budget_kzt", 0, "over_budget"),
                 ("duration_hours", 1000, "too_short"), ("language", "Несуществующий", "wrong_language")]
        for field, value, reason in cases:
            with self.subTest(field=field):
                failed = failures(self.profile, replace(self.event, **{field:value}))
                self.assertIn(reason, [r for _, r in failed])
        self.assertIn(("available", "busy"), failures(replace(self.profile, busy_dates=(self.event.date,)), self.event))

    def test_inclusive_price_and_hours(self):
        event = replace(self.event, budget_kzt=self.profile.price_from_kzt, duration_hours=self.profile.max_hours)
        self.assertEqual(failures(self.profile, event), [])

    def test_normalization_and_unknowns(self):
        result = self.service.recommend({**asdict(self.event), "city":"  аЛМаТы  ", "category":"фотограф"})
        self.assertEqual(result["status"], "matched")
        for key in ("city", "category"):
            self.assertEqual(self.service.recommend({**asdict(self.event), key:"Unknown"})["status"], "category_not_found")

    def test_duration_null_semantics(self):
        candidate = replace(self.profile, max_hours=None)
        self.assertIn(("duration", "duration_unknown"), failures(candidate, self.event))
        self.assertEqual(failures(candidate, replace(self.event, duration_hours=None)), [])
        florist_event = replace(self.event, category="Флорист")
        florist = replace(candidate, categories=("Флорист",))
        self.assertEqual(failures(florist, florist_event), [])

    def test_missing_fields_and_empty_arrays(self):
        candidate = normalize({"id":"test-only"})
        self.assertIsNone(candidate.price_from_kzt)
        self.assertEqual(hard_filter([candidate], self.event)[0], [])
        self.assertIn(("available","availability_unknown"), failures(candidate, self.event))
        candidate = normalize({**asdict(self.profile), "busy_dates":[], "languages":[], "synthetic":"False"})
        self.assertTrue(candidate.availability_known)
        self.assertFalse(candidate.synthetic)
        self.assertIn(("language", "wrong_language"), failures(candidate, self.event))
        bad = normalize({**asdict(self.profile), "busy_dates":"2026-02-30"})
        self.assertFalse(bad.availability_known)

    def test_validation(self):
        invalid = [{}, None, [], {**asdict(self.event),"date":"2026-02-30"},
                   {**asdict(self.event),"date":"2026-9-26"}, {**asdict(self.event),"date":"2027-01-01"},
                   {**asdict(self.event),"budget_kzt":-1}, {**asdict(self.event),"budget_kzt":True},
                   {**asdict(self.event),"budget_kzt":float('nan')}, {**asdict(self.event),"budget_kzt":float('inf')},
                   {**asdict(self.event),"budget_kzt":"300000"}, {**asdict(self.event),"duration_hours":0},
                   {**asdict(self.event),"language":[]}, {**asdict(self.event),"city":None}]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                EventRequest.parse(payload)

    def test_extremely_large_numbers_are_validation_errors(self):
        for key in ("budget_kzt", "duration_hours"):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                EventRequest.parse({**asdict(self.event), key:10**400})
        self.assertIsNone(normalize({"id":"fixture", "price_from_kzt":10**400}).price_from_kzt)

    def test_repeatability_and_tie_breaker(self):
        first = self.service.recommend(asdict(self.event))
        for _ in range(5):
            self.assertEqual(self.service.recommend(asdict(self.event)), first)
        # Test fixtures are copies in memory; no added production profiles.
        copied = [replace(self.profile, id=id_) for id_ in ("Z", "B", "A", "C")]
        dataset = type("Fixture", (), {"contractors":copied, "fingerprint":"fixture"})()
        result = RecommendationService(dataset).recommend(asdict(self.event))
        self.assertEqual([c["id"] for c in result["recommendations"]], ["A", "B", "C"])

    def test_different_dates_change_results(self):
        first = self.service.recommend(asdict(self.event))
        second = self.service.recommend({**asdict(self.event), "date":"2026-09-27"})
        self.assertNotEqual([r["id"] for r in first["recommendations"]], [r["id"] for r in second["recommendations"]])

    def test_funnel_conservation(self):
        for demo in self.demos:
            result = self.service.recommend(demo["request"])
            counts = list(result["filter_stats"].values())
            self.assertEqual(counts, sorted(counts, reverse=True))
            self.assertEqual(sum(result["excluded_reasons"].values()) + result["eligible_candidates"], 66)
            self.assertEqual(len(result["excluded_candidates"]), sum(result["excluded_reasons"].values()))

    def test_suggestions_are_real_and_change_only_declared_fields(self):
        for demo in self.demos:
            original = demo["request"].copy()
            result = self.service.recommend(original)
            for suggestion in result["suggestions"]:
                self.assertTrue(1 <= len(suggestion["changes"]) <= 3)
                self.assertTrue(set(suggestion["changes"]) <= {"budget_kzt", "date", "language", "duration_hours"})
                revised = {**original, **suggestion["changes"]}
                count = len(hard_filter(self.dataset.contractors, EventRequest.parse(revised))[0])
                self.assertEqual(count, suggestion["eligible_candidates"])
                self.assertEqual(count - result["eligible_candidates"], suggestion["additional_candidates"])
                self.assertGreater(count, result["eligible_candidates"])
            self.assertEqual(original, demo["request"])

    def test_weights_and_explanations(self):
        result = self.service.recommend(asdict(self.event))
        texts = []
        for candidate in result["recommendations"]:
            breakdown = candidate["score_breakdown"]
            self.assertAlmostEqual(sum(part["weight"] for part in breakdown.values()), 100, places=2)
            self.assertNotIn("semantic", breakdown)
            self.assertIn(candidate["name"], candidate["explanation"])
            self.assertIn(self.event.date, candidate["explanation"])
            texts.append(candidate["explanation"].replace(candidate["name"], ""))
        self.assertEqual(len(texts), len(set(texts)))
        cheap = score(replace(self.profile, price_from_kzt=100000), self.event)[0]
        costly = score(replace(self.profile, price_from_kzt=500000), self.event)[0]
        self.assertGreater(cheap, costly)

    def test_json_and_jsonl_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            for suffix in (".json", ".jsonl"):
                path = Path(directory) / ("fixture" + suffix)
                rows = [asdict(self.profile)]
                path.write_text(json.dumps(rows if suffix == ".json" else rows[0]), encoding="utf-8")
                self.assertEqual(Dataset(path).contractors[0].id, self.profile.id)

    def test_demos_use_alternative_catalog_values(self):
        fixture = replace(self.profile, city="Другой город", categories=("Другая категория",),
                          event_formats=("Другой формат",), languages=(), price_from_kzt=1234,
                          max_hours=0.25, busy_dates=())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.json"
            for candidate in (fixture, replace(fixture, price_from_kzt=0)):
                path.write_text(json.dumps([asdict(candidate)]), encoding="utf-8")
                dataset = Dataset(path)
                service = RecommendationService(dataset)
                demos = build_demos(dataset)
                self.assertTrue(demos)
                for demo in demos:
                    request = demo["request"]
                    self.assertEqual(request["city"], candidate.city)
                    self.assertIn(request["category"], candidate.categories)
                    self.assertIn(request["event_format"], candidate.event_formats)
                    self.assertEqual(service.recommend(request)["eligible_candidates"], demo["expected_eligible"])

    def test_money_does_not_round_fractional_prices_to_integer(self):
        from backend.explanations import money
        self.assertEqual(money(1234.5), "1 234,5 ₸")
        self.assertEqual(money(1234), "1 234 ₸")


if __name__ == "__main__":
    unittest.main()
