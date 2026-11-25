# -*- coding: utf-8 -*-
"""Tests for LLM number verification (DSA v5 P0-7).

- An LLM-stated MA value must match the computed value from closed daily
  bars within 0.01; a mismatch is a hard failure.
- Sniper points outside a plausible band around the spot price fail.
- RSI is recorded only: the system computes RSI(6/12/24) via Wilder and
  has no RSI(14) reference, so RSI never hard-fails and its algorithm is
  never hard-coded (precondition 1 open).
"""

import unittest

from src.analyzer import AnalysisResult, validate_llm_numbers

TREND = {
    "ma5": 1.11,
    "ma10": 1.173,
    "ma20": 1.238,
    "current_price": 1.14,
    "rsi_6": 30.0,
    "rsi_12": 28.0,
    "rsi_24": 25.0,
}


def _result(ma_analysis="", technical_analysis="", dashboard=None):
    return AnalysisResult(
        code="600491",
        name="ST龙元",
        sentiment_score=50,
        trend_prediction="观望",
        operation_advice="观望",
        ma_analysis=ma_analysis,
        technical_analysis=technical_analysis,
        dashboard=dashboard or {},
    )


class ValidateLLMNumbersTestCase(unittest.TestCase):
    def test_matching_ma_claims_pass(self):
        result = _result(ma_analysis="MA5 1.11，MA10 1.173，MA20 1.238，均线空头排列。")
        check = validate_llm_numbers(result, {"trend_result": TREND})
        self.assertEqual(check["status"], "passed")
        self.assertIsNone(check["reason"])

    def test_mismatched_ma_claim_fails(self):
        # The 2026-11-25 audit case: report said 1.102/1.149/1.225,
        # external recomputation said 1.110/1.173/1.238. MA5 differs by
        # 0.008 (inside the 0.01 tolerance) but MA10/MA20 differ by
        # 0.024/0.013, so the check fails on those.
        result = _result(ma_analysis="MA5 1.102，MA10 1.149，MA20 1.225。")
        check = validate_llm_numbers(result, {"trend_result": TREND})
        self.assertEqual(check["status"], "failed")
        assert check["reason"] is not None
        self.assertIn("ma10", check["reason"])
        self.assertIn("ma20", check["reason"])

    def test_no_ma_claims_is_not_a_failure(self):
        result = _result(ma_analysis="均线空头排列，短期偏弱。")
        check = validate_llm_numbers(result, {"trend_result": TREND})
        self.assertEqual(check["status"], "no_claims")

    def test_sniper_point_outside_band_fails(self):
        dashboard = {
            "battle_plan": {
                "sniper_points": {
                    "ideal_buy": 1.10,
                    "stop_loss": 0.10,
                    "take_profit": 1.20,
                }
            }
        }
        result = _result(dashboard=dashboard)
        check = validate_llm_numbers(result, {"trend_result": TREND})
        self.assertEqual(check["status"], "failed")
        assert check["reason"] is not None
        self.assertIn("stop_loss", check["reason"])

    def test_sniper_points_inside_band_pass_and_are_labelled_model_opinion(self):
        dashboard = {
            "battle_plan": {
                "sniper_points": {
                    "ideal_buy": 1.10,
                    "stop_loss": 1.05,
                    "take_profit": 1.20,
                }
            }
        }
        result = _result(dashboard=dashboard)
        check = validate_llm_numbers(result, {"trend_result": TREND})
        self.assertEqual(check["status"], "no_claims")
        point_checks = [c for c in check["checks"] if c["kind"] == "sniper_point"]
        self.assertTrue(point_checks)
        self.assertTrue(
            all(c.get("label") == "模型观点、不可程序验真" for c in point_checks)
        )

    def test_rsi_recorded_only_never_fails(self):
        result = _result(technical_analysis="RSI 25.9，处于超卖区。")
        check = validate_llm_numbers(result, {"trend_result": TREND})
        self.assertNotEqual(check["status"], "failed")
        self.assertEqual(check["rsi"]["llm_claimed"], 25.9)
        self.assertIsNone(check["rsi"]["system_rsi_14"])
        self.assertEqual(check["rsi"]["status"], "unverifiable")
