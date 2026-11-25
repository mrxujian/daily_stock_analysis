# -*- coding: utf-8 -*-
"""Manual confirmation gate for anomalous volume ratios (DSA v5 P0-3).

When a volume-change ratio is out of the 0.1-10x band, or the volume unit
is unverified, the pipeline must:

1. raise an alert and record a confirmation request (confirmer: Rio,
   evidence: Wind daily K-line volume in shares);
2. block that run's report sending / conclusion output until confirmed;
3. if the 2-hour window expires without confirmation, mark the request
   "timeout", keep the report blocked, and pause the NEXT scheduled task
   (single timeout pauses the next run; recovery requires Jason's explicit
   approval);
4. if the 2-hour window crosses the next scheduled task time, pause that
   task first; never let it auto-run in an unconfirmed state.

There is NO substitute confirmer. Jazz implements the pipeline and cannot
stand in for the independent reviewer (Rio). Unconfirmed means blocked.

The request record is a plain JSON file so the workflow pre-check step can
read it from the checkout before the next run starts.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

CONFIRMATION_WINDOW_HOURS = 2
CONFIRMATION_TIMEZONE = "Asia/Shanghai"
SCHEDULED_RUN_TIME = dtime(18, 0)  # daily 18:00 Asia/Shanghai

STATUS_PENDING = "pending"
STATUS_CONFIRMED = "confirmed"
STATUS_TIMEOUT = "timeout"


@dataclass
class VolumeConfirmationRequest:
    """One manual-confirmation request for an anomalous volume ratio."""

    code: str
    trade_date: str
    volume_change_ratio: Optional[float]
    reason: str
    requested_at: str  # ISO 8601 with offset, Asia/Shanghai
    deadline_at: str  # ISO 8601 with offset, Asia/Shanghai
    confirmer: str = "Rio"
    status: str = STATUS_PENDING
    confirmed_at: Optional[str] = None
    confirmed_by: Optional[str] = None
    evidence: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VolumeConfirmationRequest":
        return cls(
            code=str(data.get("code", "")),
            trade_date=str(data.get("trade_date", "")),
            volume_change_ratio=data.get("volume_change_ratio"),
            reason=str(data.get("reason", "")),
            requested_at=str(data.get("requested_at", "")),
            deadline_at=str(data.get("deadline_at", "")),
            confirmer=str(data.get("confirmer", "Rio")),
            status=str(data.get("status", STATUS_PENDING)),
            confirmed_at=data.get("confirmed_at"),
            confirmed_by=data.get("confirmed_by"),
            evidence=data.get("evidence"),
        )


def _now_shanghai() -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo(CONFIRMATION_TIMEZONE))


def _parse_iso(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        from zoneinfo import ZoneInfo

        parsed = parsed.replace(tzinfo=ZoneInfo(CONFIRMATION_TIMEZONE))
    return parsed


def compute_deadline(requested_at: datetime) -> datetime:
    """2-hour deadline; if it lands on a non-trading day, move it to the
    next trading day at the same time (holiday/suspension rollover)."""
    deadline = requested_at + timedelta(hours=CONFIRMATION_WINDOW_HOURS)
    try:
        from src.core.trading_calendar import get_next_trading_date, is_market_open

        market = "cn"
        while not is_market_open(market, deadline.date()):
            nxt = get_next_trading_date(market, deadline.date())
            if nxt is None:
                break
            deadline = datetime.combine(nxt, deadline.time(), tzinfo=deadline.tzinfo)
    except Exception as exc:  # trading calendar unavailable: plain 2h deadline
        logger.warning("Volume confirmation deadline rollover unavailable: %s", exc)
    return deadline


def next_scheduled_run(now: Optional[datetime] = None) -> datetime:
    """Next daily 18:00 Asia/Shanghai run time strictly after ``now``."""
    current = now or _now_shanghai()
    candidate = datetime.combine(current.date(), SCHEDULED_RUN_TIME, tzinfo=current.tzinfo)
    if candidate <= current:
        candidate = candidate + timedelta(days=1)
    return candidate


def request_confirmation(
    code: str,
    *,
    trade_date: str,
    volume_change_ratio: Optional[float],
    reason: str,
    state_path: str,
    now: Optional[datetime] = None,
) -> VolumeConfirmationRequest:
    """Record a confirmation request and persist it to ``state_path``."""
    current = now or _now_shanghai()
    deadline = compute_deadline(current)
    record = VolumeConfirmationRequest(
        code=code,
        trade_date=trade_date,
        volume_change_ratio=volume_change_ratio,
        reason=reason,
        requested_at=current.isoformat(),
        deadline_at=deadline.isoformat(),
    )
    save_confirmation_state(state_path, record)
    logger.warning(
        "Volume confirmation requested: code=%s ratio=%s deadline=%s",
        code,
        volume_change_ratio,
        deadline.isoformat(),
    )
    return record


def save_confirmation_state(state_path: str, record: VolumeConfirmationRequest) -> None:
    path = Path(state_path)
    if path.parent and str(path.parent):
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(record.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_confirmation_state(state_path: str) -> Optional[VolumeConfirmationRequest]:
    path = Path(state_path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Volume confirmation state unreadable at %s: %s", state_path, exc)
        return None
    if not isinstance(data, dict):
        return None
    return VolumeConfirmationRequest.from_dict(data)


def is_timed_out(
    record: VolumeConfirmationRequest,
    now: Optional[datetime] = None,
) -> bool:
    """True when the 2-hour window expired without confirmation."""
    if record.status == STATUS_CONFIRMED:
        return False
    deadline = _parse_iso(record.deadline_at)
    if deadline is None:
        return False
    current = now or _now_shanghai()
    return current > deadline


def should_pause_next_run(
    record: Optional[VolumeConfirmationRequest],
    now: Optional[datetime] = None,
) -> bool:
    """True when the next scheduled run must pause instead of auto-running.

    Pauses when a request is still pending AND its window has expired, or
    its window crosses the next scheduled run time (18:00). Confirmed
    requests never pause a run.
    """
    if record is None or record.status != STATUS_PENDING:
        return False
    current = now or _now_shanghai()
    if is_timed_out(record, current):
        return True
    deadline = _parse_iso(record.deadline_at)
    if deadline is None:
        return False
    return deadline > next_scheduled_run(current)


def confirm_request(
    record: VolumeConfirmationRequest,
    *,
    confirmed_by: str,
    evidence: str,
    state_path: str,
    now: Optional[datetime] = None,
) -> VolumeConfirmationRequest:
    """Record a confirmation (confirmer must be the independent reviewer)."""
    current = now or _now_shanghai()
    record.status = STATUS_CONFIRMED
    record.confirmed_at = current.isoformat()
    record.confirmed_by = confirmed_by
    record.evidence = evidence
    save_confirmation_state(state_path, record)
    logger.info(
        "Volume confirmation recorded: code=%s by=%s",
        record.code,
        confirmed_by,
    )
    return record
