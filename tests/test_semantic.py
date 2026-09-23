from dataclasses import asdict, replace
import tempfile
import json
import sqlite3
from contextlib import closing
import unittest
from unittest.mock import patch
from backend.dataset import Dataset
from backend.demos import build_demos
from backend.models import EventRequest
from backend.filters import hard_filter
from backend.semantic import SemanticMatcher, cosine
from backend.service import RecommendationService


class SemanticTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.dataset = Dataset()
        self.event = EventRequest.parse(build_demos(self.dataset)[0]["request"])
        self.candidates = hard_filter(self.dataset.contractors, self.event)[0]
        self.matcher = SemanticMatcher(self.directory.name, enabled=True, api_key="unit-test-key")

    def test_cosine(self):
        self.assertEqual(cosine([1,0], [1,0]), 1)
        self.assertEqual(cosine([1,0], [0,1]), 0)
        with self.assertRaises(ValueError): cosine([1], [1,0])
        with self.assertRaises(ValueError): cosine([0,0], [0,0])
        with self.assertRaises(ValueError): cosine([float('nan')], [1])
        with self.assertRaises(ValueError): cosine([True], [1])
        self.assertEqual(cosine([1e300,0], [1e300,0]), 1)

    def test_real_vector_path_only_receives_eligible_descriptions_and_caches(self):
        with patch.object(self.matcher, "_embed", side_effect=lambda texts:[[1.0,float(i % 2)] for i,_ in enumerate(texts)]) as embed:
            service = RecommendationService(self.dataset, self.matcher)
            first = service.recommend(asdict(self.event))
            self.assertEqual(first["semantic_mode"], "embeddings")
            sent = embed.call_args.args[0]
            self.assertEqual(set(sent[1:]), {c.description for c in self.candidates})
            self.assertEqual(len(sent), len(self.candidates) + 1)
            self.assertEqual(first, service.recommend(asdict(self.event)))
            self.assertEqual(embed.call_count, 1)
        reloaded = SemanticMatcher(self.directory.name, enabled=True, api_key="unit-test-key")
        with patch.object(reloaded, "_embed", side_effect=AssertionError("Network must not be needed")):
            self.assertEqual(first, RecommendationService(self.dataset, reloaded).recommend(asdict(self.event)))

    def test_api_failure_falls_back_and_persists_decision(self):
        with patch.object(self.matcher, "_embed", side_effect=TimeoutError):
            first = RecommendationService(self.dataset,self.matcher).recommend(asdict(self.event))
        offline = RecommendationService(self.dataset).recommend(asdict(self.event))
        self.assertEqual(first["recommendations"], offline["recommendations"])
        self.assertEqual(first["semantic_mode"], "unavailable")
        with patch.object(self.matcher, "_embed", side_effect=AssertionError):
            self.assertEqual(first, RecommendationService(self.dataset,self.matcher).recommend(asdict(self.event)))

    def test_invalid_vectors_fall_back(self):
        with patch.object(self.matcher, "_embed", return_value=[[float('nan')]] * (len(self.candidates)+1)):
            scores, mode = self.matcher.similarities(self.event,self.candidates,self.dataset.fingerprint)
        self.assertIsNone(scores)
        self.assertEqual(mode,"unavailable")

    def test_nearby_budgets_have_separate_cache_entries(self):
        with patch.object(self.matcher, "_embed", side_effect=lambda texts:[[1.0,1.0] for _ in texts]):
            for budget in (299999.9, 300000.1):
                event = replace(self.event, budget_kzt=budget)
                eligible = hard_filter(self.dataset.contractors, event)[0]
                scores, mode = self.matcher.similarities(event, eligible, self.dataset.fingerprint)
                self.assertEqual(mode, "embeddings")
                self.assertEqual(set(scores), {c.id for c in eligible})

    def test_corrupt_cached_decision_never_crashes_recommendations(self):
        with patch.object(self.matcher, "_embed", side_effect=lambda texts:[[1.0,1.0] for _ in texts]):
            self.matcher.similarities(self.event, self.candidates, self.dataset.fingerprint)
        for invalid in ({}, [], {"mode":"embeddings", "scores":{}},
                        {"mode":"embeddings", "scores":{c.id:float('nan') for c in self.candidates}}):
            with self.subTest(invalid=invalid):
                with closing(sqlite3.connect(self.matcher.cache_dir / "embeddings.sqlite3")) as db, db:
                    db.execute("UPDATE decisions SET value=?", (json.dumps(invalid),))
                result = RecommendationService(self.dataset,self.matcher).recommend(asdict(self.event))
                self.assertNotEqual(result["semantic_mode"], "embeddings")
                self.assertTrue(all("semantic" not in c["score_breakdown"] for c in result["recommendations"]))

    def test_missing_key_and_disabled(self):
        for enabled, expected in ((False,"disabled"),(True,"missing_key")):
            matcher = SemanticMatcher(self.directory.name,enabled=enabled,api_key="")
            scores, mode = matcher.similarities(self.event,self.candidates,self.dataset.fingerprint)
            self.assertIsNone(scores)
            self.assertEqual(mode,expected)

    def test_semantics_cannot_resurrect_busy_profile(self):
        busy = replace(self.candidates[0],busy_dates=(self.event.date,))
        dataset = type("Fixture", (), {"contractors":[busy], "fingerprint":"busy-fixture"})()
        with patch.object(self.matcher,"_embed",side_effect=AssertionError("Must never run")):
            result = RecommendationService(dataset,self.matcher).recommend(asdict(self.event))
            self.assertEqual(result["recommendations"],[])


if __name__ == "__main__":
    unittest.main()
