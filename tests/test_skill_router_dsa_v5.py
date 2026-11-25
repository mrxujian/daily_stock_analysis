# -*- coding: utf-8 -*-
"""Tests for the DSA v5 P0-8 router changes.

- Direction first: MA alignment decides the regime; a bearish alignment
  never falls through to sideways, even with a middling score.
- A missing trend_score is "unknown", never a default 50.
- No technical view -> no default skill (empty list, not bull_trend).
"""

import unittest
from unittest.mock import patch

from src.agent.protocols import AgentContext, AgentOpinion
from src.agent.skills.router import SkillRouter


def _ctx(ma_alignment=None, trend_score=None, volume_status="normal"):
    ctx = AgentContext()
    raw = {"volume_status": volume_status}
    if ma_alignment is not None:
        raw["ma_alignment"] = ma_alignment
    if trend_score is not None:
        raw["trend_score"] = trend_score
    ctx.add_opinion(AgentOpinion(
        agent_name="technical",
        signal="hold",
        confidence=0.5,
        raw_data=raw,
    ))
    return ctx


class DetectRegimeTestCase(unittest.TestCase):
    def test_bearish_with_middling_score_is_trending_down(self):
        # The 2026-11-25 audit case: bearish trend with a mid score was
        # routed to sideways and then to the bull_trend default skill.
        router = SkillRouter()
        self.assertEqual(router._detect_regime(_ctx("bearish", 50)), "trending_down")
        self.assertEqual(router._detect_regime(_ctx("bearish", 80)), "trending_down")

    def test_bullish_direction_first(self):
        router = SkillRouter()
        self.assertEqual(router._detect_regime(_ctx("bullish", 40)), "trending_up")
        self.assertEqual(router._detect_regime(_ctx("bullish", 80)), "trending_up")

    def test_missing_score_is_unknown_not_default_50(self):
        router = SkillRouter()
        # No alignment and no score: regime unknown, not sideways.
        self.assertIsNone(router._detect_regime(_ctx()))
        # Neutral alignment is still sideways.
        self.assertEqual(router._detect_regime(_ctx("neutral", None)), "sideways")

    def test_no_technical_opinion_is_none(self):
        router = SkillRouter()
        self.assertIsNone(router._detect_regime(AgentContext()))


class SelectSkillsNoDefaultTestCase(unittest.TestCase):
    @patch("src.agent.skills.router.SkillRouter._get_routing_mode", return_value="auto")
    @patch("src.agent.skills.router.SkillRouter._get_available_skills", return_value=[])
    def test_no_regime_returns_empty_list(self, _mock_skills, _mock_mode):
        router = SkillRouter()
        self.assertEqual(router.select_skills(AgentContext()), [])
        self.assertEqual(router.select_skills(_ctx()), [])


class BullBaselineGatingTestCase(unittest.TestCase):
    """The bull baseline is injected only for a bullish MA alignment."""

    def test_trading_policy_only_for_bullish_alignment(self):
        from src.agent.skills.defaults import get_default_trading_skill_policy

        self.assertIn(
            "严进策略",
            get_default_trading_skill_policy(
                explicit_skill_selection=False, ma_alignment="bullish"
            ),
        )
        self.assertEqual(
            get_default_trading_skill_policy(
                explicit_skill_selection=False, ma_alignment="bearish"
            ),
            "",
        )
        self.assertEqual(
            get_default_trading_skill_policy(
                explicit_skill_selection=False, ma_alignment="neutral"
            ),
            "",
        )
        self.assertEqual(
            get_default_trading_skill_policy(explicit_skill_selection=False),
            "",
        )
        self.assertEqual(
            get_default_trading_skill_policy(
                explicit_skill_selection=True, ma_alignment="bullish"
            ),
            "",
        )

    def test_technical_policy_only_for_bullish_alignment(self):
        from src.agent.skills.defaults import get_default_technical_skill_policy

        self.assertIn(
            "Bullish alignment",
            get_default_technical_skill_policy(
                explicit_skill_selection=False, ma_alignment="bullish"
            ),
        )
        self.assertEqual(
            get_default_technical_skill_policy(
                explicit_skill_selection=False, ma_alignment="bearish"
            ),
            "",
        )
        self.assertEqual(
            get_default_technical_skill_policy(explicit_skill_selection=False),
            "",
        )
