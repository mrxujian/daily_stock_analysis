# -*- coding: utf-8 -*-
"""Announcement / risk-list service for ST tickers (DSA v5 P1-1, P1-5).

Free announcement source: Eastmoney announcements API
(``np-anotice-stock.eastmoney.com/api/security/ann``), verified reachable
2026-11-26 from a plain ``requests`` call (no browser needed). The three
fixed regression samples (070/071/069) are all returned in the top 5 rows
for 600491.

Coverage is tracked by event validity / open items, not by a 7-day
publication window: pre-restructuring, lawsuits, overdue debt and
investor recruitment stay on the risk list until they end or lapse under
the per-category exit rules below.

Exit rules (DSA v5 P1-1 as tightened by the Lao De v5 verdict + Xiaozha
v5 review; the six conditions relayed by Rio 2026-11-26 06:10):

- A company announcement is only a CLUE. Removal from the risk list
  requires a court / manager / regulator verifiable document.
- Lawsuit: effective judgment, mediation paper or enforcement
  termination (document number + date required).
- Overdue debt: full repayment, or a creditor's written confirmation of
  release. Partial repayment never removes the item.
- Pre-restructuring / investor recruitment: a court, manager or company
  formal document confirming termination / lapse (document number +
  date required).
- Exit is evaluated per category; categories never substitute for each
  other ("satisfy the condition of the corresponding category").
- Never remove an item because the 7-day window passed, and never infer
  closure from the absence of new announcements.
- A correction keeps the original version, the revised version and the
  linkage (correction notice number, content, date); the list marks the
  item "corrected" and never overwrites the original with the revision.

ST hard gate (DSA v5 P1-5, condition 4): when the announcement source
fails its PoC or the runtime interface fails, the system outputs ONLY a
data-status report / coverage-insufficient note and NO investment
conclusion. The gate must never be switched off to keep giving
conclusions, and the system must never stall silently.

ST weight (condition 5): the announcement-coverage weight applies ONLY
after the hard gate passes, to scoring. It can never offset a hard-gate
failure. The raise value itself is precondition ⑤ (open): it must be
written down by Jazz and confirmed by Lao De before production use. The
code below carries the CURRENT value (the news block weight, 10) and
documents the formula; it does not invent a raised number.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

EASTMONEY_ANNOUNCEMENT_API = (
    "https://np-anotice-stock.eastmoney.com/api/security/ann"
)
ANNOUNCEMENT_TIMEOUT_SECONDS = 15
ANNOUNCEMENT_PAGE_SIZE = 30

CATEGORY_LAWSUIT = "lawsuit"
CATEGORY_OVERDUE = "overdue"
CATEGORY_RESTRUCTURING = "restructuring"
CATEGORY_RECRUITMENT = "recruitment"
CATEGORY_OTHER = "other"

COVERAGE_OK = "ok"
COVERAGE_FAILED = "failed"

# Fixed regression samples (must appear in the risk list when coverage is ok).
REGRESSION_SAMPLES = (
    {
        "notice_no": "临2026-070",
        "title_keyword": "新增诉讼",
        "notice_date": "2026-11-21",
        "category": CATEGORY_LAWSUIT,
    },
    {
        "notice_no": "临2026-071",
        "title_keyword": "债务逾期",
        "notice_date": "2026-11-21",
        "category": CATEGORY_OVERDUE,
    },
    {
        "notice_no": "临2026-069",
        "title_keyword": "公开招募预重整投资人",
        "notice_date": "2026-11-10",
        "category": CATEGORY_RECRUITMENT,
    },
)

# Current news-block weight in the data-quality score (see
# ``_QUALITY_BLOCK_WEIGHTS`` in analysis_context_builder.py). The RAISED
# ST weight is precondition ⑤ (open): it must be written down with a
# verifiable basis and confirmed by Lao De before production use. Until
# then the code uses the current value and never invents a raised number.
ST_ANNOUNCEMENT_BLOCK_WEIGHT_CURRENT = 10
ST_ANNOUNCEMENT_BLOCK_WEIGHT_RAISED = None  # pending precondition ⑤


@dataclass
class Announcement:
    """One announcement row from the free source."""

    title: str
    notice_date: str
    display_date: str
    art_code: str = ""
    category: str = CATEGORY_OTHER
    source_url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "notice_date": self.notice_date,
            "display_date": self.display_date,
            "art_code": self.art_code,
            "category": self.category,
            "source_url": self.source_url,
        }


@dataclass
class RiskItem:
    """One open risk-list item with its exit rule."""

    title: str
    notice_date: str
    notice_no: str
    category: str
    status: str = "open"
    exit_evidence: Optional[str] = None
    corrected: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "notice_date": self.notice_date,
            "notice_no": self.notice_no,
            "category": self.category,
            "status": self.status,
            "exit_evidence": self.exit_evidence,
            "corrected": self.corrected,
        }


def classify_announcement(title: str) -> str:
    """Classify an announcement title into a risk category.

    Recruitment is checked before restructuring: a "公开招募预重整投资人"
    notice (069) is an investor-recruitment notice, even though its title
    also contains "预重整".
    """
    text = title or ""
    if any(key in text for key in ("新增诉讼", "诉讼", "仲裁")):
        return CATEGORY_LAWSUIT
    if "债务逾期" in text:
        return CATEGORY_OVERDUE
    if "招募" in text and "投资人" in text:
        return CATEGORY_RECRUITMENT
    if any(key in text for key in ("预重整", "重整")):
        return CATEGORY_RESTRUCTURING
    return CATEGORY_OTHER


def fetch_announcements(code: str) -> Tuple[List[Announcement], str]:
    """Fetch announcements for ``code`` from the Eastmoney API.

    Returns (announcements, coverage) where coverage is "ok" when the
    interface answered with a usable list, else "failed". A failed fetch
    is never interpreted as "no announcements".
    """
    try:
        import requests
    except ImportError as exc:  # pragma: no cover - requests is a hard dep
        logger.warning("Announcement fetch unavailable: requests missing: %s", exc)
        return [], COVERAGE_FAILED

    params = {
        "sr": "-1",
        "page_size": ANNOUNCEMENT_PAGE_SIZE,
        "page_index": 1,
        "ann_type": "A",
        "stock_list": code,
        "f_node": "0",
        "s_node": "0",
    }
    try:
        response = requests.get(
            EASTMONEY_ANNOUNCEMENT_API,
            params=params,
            timeout=ANNOUNCEMENT_TIMEOUT_SECONDS,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if response.status_code != 200:
            logger.warning(
                "Announcement fetch failed: HTTP %s for %s",
                response.status_code,
                code,
            )
            return [], COVERAGE_FAILED
        payload = response.json()
        if not payload.get("success"):
            logger.warning("Announcement fetch failed: success flag false for %s", code)
            return [], COVERAGE_FAILED
        data = payload.get("data") or {}
        rows = data.get("list") or []
        announcements: List[Announcement] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            if not title:
                continue
            announcements.append(
                Announcement(
                    title=title,
                    notice_date=str(row.get("notice_date") or "")[:10],
                    display_date=str(row.get("display_time") or "")[:10],
                    art_code=str(row.get("art_code") or ""),
                    category=classify_announcement(title),
                )
            )
        logger.info(
            "Announcement fetch ok: code=%s rows=%d total_hits=%s",
            code,
            len(announcements),
            data.get("total_hits"),
        )
        return announcements, COVERAGE_OK
    except Exception as exc:
        logger.warning("Announcement fetch failed for %s: %s", code, exc)
        return [], COVERAGE_FAILED


def build_risk_list(
    code: str,
    announcements: List[Announcement],
) -> List[RiskItem]:
    """Build the open risk list from fetched announcements.

    Every announcement in a risk category stays open until its exit rule
    is satisfied (see ``evaluate_exit``). The three regression samples are
    matched by title keyword + notice date so a missing sample is visible
    instead of silently dropped.
    """
    items: List[RiskItem] = []
    for ann in announcements:
        if ann.category == CATEGORY_OTHER:
            continue
        notice_no = ""
        for sample in REGRESSION_SAMPLES:
            if sample["title_keyword"] in ann.title and sample["notice_date"] == ann.notice_date:
                notice_no = sample["notice_no"]
                break
        items.append(
            RiskItem(
                title=ann.title,
                notice_date=ann.notice_date,
                notice_no=notice_no,
                category=ann.category,
            )
        )
    return items


def regression_samples_present(risk_items: List[RiskItem]) -> Dict[str, bool]:
    """Check the three fixed regression samples are in the risk list."""
    present = {sample["notice_no"]: False for sample in REGRESSION_SAMPLES}
    for item in risk_items:
        if item.notice_no in present:
            present[item.notice_no] = True
    return present


def evaluate_exit(item: RiskItem, evidence: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    """Evaluate whether an open risk item may be removed.

    ``evidence`` must carry the verifiable document for the item's own
    category. A company announcement alone is only a clue and never
    suffices. Categories never substitute for each other.

    Returns (may_remove, reason).
    """
    if not evidence:
        return False, "no exit evidence supplied; announcement alone is only a clue"
    doc_type = str(evidence.get("document_type") or "")
    doc_no = str(evidence.get("document_no") or "")
    if not doc_no:
        return False, "exit evidence lacks a verifiable document number/date"

    if item.category == CATEGORY_LAWSUIT:
        if doc_type in ("court_judgment", "court_mediation", "enforcement_termination"):
            return True, f"court document {doc_no} confirms termination"
        return False, "lawsuit exit requires a court document, not a company announcement"
    if item.category == CATEGORY_OVERDUE:
        if doc_type == "full_repayment":
            return True, f"full repayment confirmed by {doc_no}"
        if doc_type == "creditor_release":
            return True, f"creditor written release {doc_no} confirms discharge"
        if doc_type == "partial_repayment":
            return False, "partial repayment never removes an overdue item"
        return False, "overdue exit requires full repayment or creditor written release"
    if item.category in (CATEGORY_RESTRUCTURING, CATEGORY_RECRUITMENT):
        if doc_type in ("court_document", "manager_document", "regulator_document"):
            return True, f"formal document {doc_no} confirms termination/lapse"
        return False, "restructuring/recruitment exit requires a court/manager/regulator document"
    return False, "unknown category; no exit rule applies"


@dataclass
class STHardGateResult:
    """Result of the ST announcement-block hard gate."""

    passed: bool
    output_mode: str  # "full" or "data_status_only"
    reason: str
    risk_items: List[RiskItem] = field(default_factory=list)
    missing_samples: List[str] = field(default_factory=list)


def evaluate_st_hard_gate(
    code: str,
    coverage: str,
    risk_items: List[RiskItem],
) -> STHardGateResult:
    """Evaluate the ST announcement-block hard gate (DSA v5 P1-5).

    - Coverage failed -> gate FAILED: output data-status report only, no
      investment conclusion, no silent stall.
    - Coverage ok -> gate passes with the risk list attached; open items
      are disclosed, never hidden. Missing regression samples are flagged
      in the reason so the gap is visible.
    The gate is never switched off to keep giving conclusions.
    """
    if coverage != COVERAGE_OK:
        return STHardGateResult(
            passed=False,
            output_mode="data_status_only",
            reason=(
                "announcement coverage failed; ST announcement block not "
                "verified, output data-status report only, no investment conclusion"
            ),
            risk_items=list(risk_items),
        )
    present = regression_samples_present(risk_items)
    missing = [no for no, ok in present.items() if not ok]
    reason = "announcement coverage ok; risk list attached"
    if missing:
        reason += f"; regression samples missing from risk list: {', '.join(missing)}"
    return STHardGateResult(
        passed=True,
        output_mode="full",
        reason=reason,
        risk_items=list(risk_items),
        missing_samples=missing,
    )


def st_weight_contribution(
    block_score: float,
    *,
    gate_passed: bool,
    total_weight: int = 100,
) -> Optional[float]:
    """ST announcement-block weight contribution to the quality score.

    The weight applies ONLY after the hard gate passes. When the gate
    fails there is no score at all (hard gate, no offset by other blocks).

    Formula: contribution = block_score * weight / total_weight, with
    weight = ST_ANNOUNCEMENT_BLOCK_WEIGHT_CURRENT (10, the current news
    block weight). The raised value is precondition ⑤ (open) and must be
    written down with a verifiable basis and confirmed by Lao De before
    production use; this function never invents it.
    """
    if not gate_passed:
        return None
    return float(block_score) * ST_ANNOUNCEMENT_BLOCK_WEIGHT_CURRENT / float(total_weight)
