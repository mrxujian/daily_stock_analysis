# -*- coding: utf-8 -*-
"""Tests for the DSA v5 P0-2 contract: closed daily bars only.

The realtime quote must never be appended as a virtual daily bar and must
never overwrite the last closed bar's close. MA / RSI / deviation are
computed from closed daily bars only.
"""

import unittest
from datetime import date
from types import SimpleNamespace

import pandas as pd

from src.core.pipeline import StockAnalysisPipeline


def _make_pipeline():
    p = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    p.config = SimpleNamespace(enable_realtime_technical_indicators=True)
    return p


def _make_df(dates_and_closes):
    rows = [
        {"code": "600491", "date": d, "open": c, "high": c, "low": c, "close": c, "volume": 100, "amount": 0, "pct_chg": 0}
        for d, c in dates_and_closes
    ]
    return pd.DataFrame(rows)


class AugmentRealtimeClosedBarsOnlyTestCase(unittest.TestCase):
    """_augment_historical_with_realtime returns the frame unchanged."""

    def test_no_virtual_row_appended_for_today(self):
        """A realtime quote for today must not become a new daily bar."""
        df = _make_df([(date(2026, 11, 24), 1.13), (date(2026, 11, 25), 1.14)])
        quote = SimpleNamespace(price=1.08, open_price=1.14, high=1.15, low=1.07, volume=200, amount=None, change_pct=-5.0, pre_close=None)

        result = _make_pipeline()._augment_historical_with_realtime(df, quote, "600491")

        self.assertEqual(len(result), 2)
        self.assertEqual(list(result["date"]), [date(2026, 11, 24), date(2026, 11, 25)])
        self.assertEqual(list(result["close"]), [1.13, 1.14])

    def test_last_closed_bar_close_not_overwritten(self):
        """The last closed bar keeps its close even when a quote exists."""
        df = _make_df([(date(2026, 11, 25), 1.14)])
        quote = SimpleNamespace(price=1.08, open_price=1.14, high=1.15, low=1.07, volume=200, amount=None, change_pct=-5.0, pre_close=None)

        result = _make_pipeline()._augment_historical_with_realtime(df, quote, "600491")

        self.assertEqual(len(result), 1)
        self.assertEqual(float(result.iloc[-1]["close"]), 1.14)

    def test_empty_frame_and_missing_quote_pass_through(self):
        """Degenerate inputs are returned unchanged."""
        pipeline = _make_pipeline()
        empty = pd.DataFrame()
        self.assertTrue(pipeline._augment_historical_with_realtime(empty, None, "600491").empty)
        df = _make_df([(date(2026, 11, 25), 1.14)])
        self.assertEqual(len(pipeline._augment_historical_with_realtime(df, None, "600491")), 1)
