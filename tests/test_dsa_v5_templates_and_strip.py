# -*- coding: utf-8 -*-
"""Tests for the fixed missing-news template (DSA v5 P0-4) and for the
signal-attribution strip (DSA v5 P0-6).
"""

import unittest

from src.services.empty_news import missing_news_fixed_template
from src.utils.data_processing import (
    strip_dashboard_signal_attribution,
    strip_report_signal_attribution,
)


class MissingNewsTemplateTestCase(unittest.TestCase):
    def test_zero_hit_template_states_scope_time_and_evidence(self):
        text = missing_news_fixed_template(
            coverage_scope="ST龙元(600491) 近期新闻与公告",
            query_time="2026-11-26 09:36:00",
            source_available=True,
            news_result_count=0,
        )
        self.assertIn("ST龙元(600491)", text)
        self.assertIn("2026-11-26 09:36:00", text)
        self.assertIn("执行了检索但零命中", text)
        self.assertIn("不得据此得出", text)

    def test_never_ran_template_distinguishes_from_zero_hit(self):
        text = missing_news_fixed_template(
            coverage_scope="ST龙元(600491) 近期新闻与公告",
            query_time="2026-11-26 09:36:00",
            source_available=False,
            news_result_count=None,
        )
        self.assertIn("未执行检索", text)
        self.assertNotIn("执行了检索但零命中", text)

    def test_english_template(self):
        text = missing_news_fixed_template(
            coverage_scope="ST Longyuan (600491) recent news",
            query_time="2026-11-26 09:36:00",
            source_available=True,
            news_result_count=0,
            language="en",
        )
        self.assertIn("zero hits", text)
        self.assertIn("Do NOT conclude", text)


class StripSignalAttributionTestCase(unittest.TestCase):
    def test_strip_removes_key_from_dashboard_and_report(self):
        dashboard = {
            "signal_attribution": {
                "technical_indicators": 60,
                "news_sentiment": 20,
                "fundamentals": 10,
                "market_conditions": 10,
            },
            "core_conclusion": {"one_sentence": "hold"},
        }
        strip_dashboard_signal_attribution(dashboard)
        self.assertNotIn("signal_attribution", dashboard)
        self.assertIn("core_conclusion", dashboard)

        payload = {"dashboard": {"signal_attribution": {"technical_indicators": 50}}}
        strip_report_signal_attribution(payload)
        self.assertNotIn("signal_attribution", payload["dashboard"])

        # Non-dict inputs are no-ops.
        strip_dashboard_signal_attribution(None)
        strip_report_signal_attribution(None)
        strip_report_signal_attribution("not a dict")
