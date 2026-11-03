import hashlib
import json
from collections import Counter

import pytest

from deepresearch_kb.semantic_claims import SemanticConfig
from evals.deepresearch_kb.claim_support.run import CASES, HERE, calibrate, split_of


def test_claim_dataset_has_sixty_reasoned_examples_and_fixed_split():
    cases = json.loads(CASES.read_text())["cases"]
    assert len(cases) == len({c["id"] for c in cases}) == 60
    assert Counter(c["type"] for c in cases) == dict.fromkeys(
        ["literal", "paraphrase", "negation", "related"], 15)
    for case in cases:
        assert case["rationale"] and case["evidence"] and case["source"]["sha256"]
        expected = "test" if int(hashlib.sha256(case["id"].encode()).hexdigest(), 16) % 5 < 2 else "dev"
        assert split_of(case["id"]) == expected


def test_threshold_is_dev_calibrated_and_matches_production_config():
    calibration = json.loads((HERE / "calibration.json").read_text())
    assert all(split_of(key) == "dev" for key in calibration["dev_ids"])
    assert calibration["threshold"] == SemanticConfig().min_similarity
    dev_results = json.loads((HERE / "results_dev.json").read_text())
    cases = [c for c in json.loads(CASES.read_text())["cases"] if split_of(c["id"]) == "dev"]
    assert calibrate(cases, dev_results["cosine_scores"])["threshold"] == calibration["threshold"]


def test_calibration_rejects_test_examples():
    cases = json.loads(CASES.read_text())["cases"]
    test_case = next(c for c in cases if split_of(c["id"]) == "test")
    with pytest.raises(ValueError, match="dev cases only"):
        calibrate([test_case], {test_case["id"]: .9})
