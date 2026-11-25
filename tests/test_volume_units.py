# -*- coding: utf-8 -*-
"""Tests for the volume unit contract (DSA v5 P0-3).

Canonical unit inside the pipeline is shares. efinance daily K-lines are
in lots (verified: 2026-11-24 282013 lots = Wind 28,201,300 shares);
STAR Market volumes are already shares; efinance realtime volume is
unverified and must never enter a ratio.
"""

import unittest

from data_provider.volume_units import (
    VOLUME_UNIT_LOTS,
    VOLUME_UNIT_SHARES,
    VOLUME_UNIT_UNVERIFIED,
    is_star_market,
    is_verified_shares_unit,
    lots_to_shares,
    volume_ratio_needs_confirmation,
)


class LotsToSharesTestCase(unittest.TestCase):
    def test_lots_multiplied_by_100(self):
        self.assertEqual(lots_to_shares(282013, "600491"), 28201300)
        self.assertEqual(lots_to_shares(454316, "600491"), 45431600)

    def test_star_market_passes_through(self):
        self.assertEqual(lots_to_shares(1000, "688001"), 1000)
        self.assertEqual(lots_to_shares(1000, "sh688001"), 1000)
        self.assertEqual(lots_to_shares(1000, "689123"), 1000)

    def test_non_numeric_returned_unchanged(self):
        self.assertIsNone(lots_to_shares(None, "600491"))
        self.assertEqual(lots_to_shares("n/a", "600491"), "n/a")

    def test_is_star_market(self):
        self.assertTrue(is_star_market("688001"))
        self.assertTrue(is_star_market("sh689123"))
        self.assertFalse(is_star_market("600491"))
        self.assertFalse(is_star_market("000001"))


class VerifiedSharesUnitTestCase(unittest.TestCase):
    def test_only_explicit_shares_counts(self):
        self.assertTrue(is_verified_shares_unit(VOLUME_UNIT_SHARES))
        self.assertFalse(is_verified_shares_unit(VOLUME_UNIT_LOTS))
        self.assertFalse(is_verified_shares_unit(VOLUME_UNIT_UNVERIFIED))
        self.assertFalse(is_verified_shares_unit(None))
        self.assertFalse(is_verified_shares_unit(""))


class VolumeRatioConfirmationTestCase(unittest.TestCase):
    def test_in_band_needs_no_confirmation(self):
        self.assertFalse(volume_ratio_needs_confirmation(0.62))
        self.assertFalse(volume_ratio_needs_confirmation(1.0))
        self.assertFalse(volume_ratio_needs_confirmation(9.99))

    def test_out_of_band_needs_confirmation(self):
        # The 2026-11-25 audit case: 0.62x misread as 62.07x.
        self.assertTrue(volume_ratio_needs_confirmation(62.07))
        self.assertTrue(volume_ratio_needs_confirmation(0.05))
        self.assertTrue(volume_ratio_needs_confirmation(10.01))

    def test_none_needs_no_confirmation(self):
        self.assertFalse(volume_ratio_needs_confirmation(None))
