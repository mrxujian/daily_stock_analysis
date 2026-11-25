# -*- coding: utf-8 -*-
"""Tests for the announcement risk list and ST hard gate (DSA v5 P1-1, P1-5).

- A company announcement is only a clue; removal requires a court /
  manager / regulator verifiable document.
- Overdue debt: full repayment or creditor written release; partial
  repayment never removes the item.
- Exit is per category; categories never substitute for each other.
- ST hard gate: coverage failure -> data-status report only, no
  investment conclusion, no silent stall.
- ST weight applies only after the gate passes, never offsets a failure.
"""

import unittest

from src.services.announcement_risk import (
    CATEGORY_LAWSUIT,
    CATEGORY_OVERDUE,
    CATEGORY_RECRUITMENT,
    CATEGORY_RESTRUCTURING,
    COVERAGE_FAILED,
    COVERAGE_OK,
    ST_ANNOUNCEMENT_BLOCK_WEIGHT_CURRENT,
    Announcement,
    RiskItem,
    build_risk_list,
    classify_announcement,
    evaluate_exit,
    evaluate_st_hard_gate,
    regression_samples_present,
    st_weight_contribution,
)


def _ann(title, notice_date):
    return Announcement(
        title=title,
        notice_date=notice_date,
        display_date=notice_date,
        art_code="",
        category=classify_announcement(title),
    )


class ClassifyAnnouncementTestCase(unittest.TestCase):
    def test_lawsuit(self):
        self.assertEqual(
            classify_announcement("关于新增诉讼事项的公告"), CATEGORY_LAWSUIT
        )

    def test_overdue(self):
        self.assertEqual(
            classify_announcement("关于债务逾期事项的公告"), CATEGORY_OVERDUE
        )

    def test_restructuring(self):
        self.assertEqual(
            classify_announcement("关于法院决定对公司启动预重整的公告"),
            CATEGORY_RESTRUCTURING,
        )

    def test_recruitment(self):
        self.assertEqual(
            classify_announcement("关于公开招募预重整投资人的公告"),
            CATEGORY_RECRUITMENT,
        )


class BuildRiskListTestCase(unittest.TestCase):
    def test_regression_samples_matched_by_keyword_and_date(self):
        anns = [
            _ann("关于新增诉讼事项的公告", "2026-11-21"),
            _ann("关于债务逾期事项的公告", "2026-11-21"),
            _ann("关于公开招募预重整投资人的公告", "2026-11-10"),
            _ann("关于日常经营事项的公告", "2026-11-20"),
        ]
        items = build_risk_list("600491", anns)
        self.assertEqual(len(items), 3)
        present = regression_samples_present(items)
        self.assertTrue(all(present.values()), present)

    def test_missing_sample_is_visible(self):
        items = build_risk_list("600491", [_ann("关于新增诉讼事项的公告", "2026-11-21")])
        present = regression_samples_present(items)
        self.assertTrue(present["临2026-070"])
        self.assertFalse(present["临2026-071"])
        self.assertFalse(present["临2026-069"])


class EvaluateExitTestCase(unittest.TestCase):
    def _item(self, category):
        return RiskItem(
            title="test", notice_date="2026-11-21", notice_no="临2026-070",
            category=category,
        )

    def test_no_evidence_never_removes(self):
        may, _ = evaluate_exit(self._item(CATEGORY_LAWSUIT), None)
        self.assertFalse(may)
        may, _ = evaluate_exit(self._item(CATEGORY_LAWSUIT), {})
        self.assertFalse(may)

    def test_announcement_alone_is_only_a_clue(self):
        may, reason = evaluate_exit(
            self._item(CATEGORY_LAWSUIT),
            {"document_type": "company_announcement", "document_no": "临2026-072"},
        )
        self.assertFalse(may)
        self.assertIn("court document", reason)

    def test_lawsuit_court_judgment_removes(self):
        may, _ = evaluate_exit(
            self._item(CATEGORY_LAWSUIT),
            {"document_type": "court_judgment", "document_no": "(2026)浙01民初123号"},
        )
        self.assertTrue(may)

    def test_overdue_partial_repayment_never_removes(self):
        may, reason = evaluate_exit(
            self._item(CATEGORY_OVERDUE),
            {"document_type": "partial_repayment", "document_no": "还款凭证001"},
        )
        self.assertFalse(may)
        self.assertIn("never removes", reason)

    def test_overdue_full_repayment_and_creditor_release_remove(self):
        may, _ = evaluate_exit(
            self._item(CATEGORY_OVERDUE),
            {"document_type": "full_repayment", "document_no": "结清证明001"},
        )
        self.assertTrue(may)
        may, _ = evaluate_exit(
            self._item(CATEGORY_OVERDUE),
            {"document_type": "creditor_release", "document_no": "债权人确认函001"},
        )
        self.assertTrue(may)

    def test_categories_never_substitute(self):
        # A court judgment does not discharge an overdue-debt item.
        may, _ = evaluate_exit(
            self._item(CATEGORY_OVERDUE),
            {"document_type": "court_judgment", "document_no": "(2026)浙01民初123号"},
        )
        self.assertFalse(may)
        # Full repayment does not close a recruitment item.
        may, _ = evaluate_exit(
            self._item(CATEGORY_RECRUITMENT),
            {"document_type": "full_repayment", "document_no": "结清证明001"},
        )
        self.assertFalse(may)

    def test_restructuring_needs_formal_document(self):
        may, _ = evaluate_exit(
            self._item(CATEGORY_RESTRUCTURING),
            {"document_type": "manager_document", "document_no": "管理人函〔2026〕1号"},
        )
        self.assertTrue(may)


class STHardGateTestCase(unittest.TestCase):
    def test_coverage_failed_gives_data_status_only(self):
        gate = evaluate_st_hard_gate("600491", COVERAGE_FAILED, [])
        self.assertFalse(gate.passed)
        self.assertEqual(gate.output_mode, "data_status_only")
        self.assertIn("no investment conclusion", gate.reason)

    def test_coverage_ok_passes_with_risk_list(self):
        items = build_risk_list(
            "600491", [_ann("关于新增诉讼事项的公告", "2026-11-21")]
        )
        gate = evaluate_st_hard_gate("600491", COVERAGE_OK, items)
        self.assertTrue(gate.passed)
        self.assertEqual(gate.output_mode, "full")
        self.assertEqual(len(gate.risk_items), 1)
        self.assertIn("临2026-071", gate.missing_samples)


class STWeightTestCase(unittest.TestCase):
    def test_weight_never_offsets_gate_failure(self):
        self.assertIsNone(st_weight_contribution(80.0, gate_passed=False))

    def test_weight_applies_after_gate_passes(self):
        expected = 80.0 * ST_ANNOUNCEMENT_BLOCK_WEIGHT_CURRENT / 100.0
        self.assertAlmostEqual(
            st_weight_contribution(80.0, gate_passed=True), expected
        )
        self.assertEqual(ST_ANNOUNCEMENT_BLOCK_WEIGHT_CURRENT, 10)
