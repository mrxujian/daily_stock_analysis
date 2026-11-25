# -*- coding: utf-8 -*-
"""Volume unit contract for DSA data providers (DSA v5 P0-3).

Canonical unit for every volume figure inside the pipeline is shares (股).

- efinance daily K-lines report volume in lots (手); verified by
  DSA-UNIT-CHECK-20261125-01: 2026-11-24 daily value 282013 lots equals
  Wind 28,201,300 shares, 2026-11-23 value 454316 lots equals
  45,431,600 shares.
- Tencent daily K-lines report volume in lots for most A-shares, but in
  shares for STAR Market stocks (688/689); see ``_lots_to_shares`` in
  ``data_provider/tencent_fetcher.py`` (Refs #2350).
- efinance realtime volume unit is UNVERIFIED (the unit check could not
  fetch it: JSONDecodeError, empty response) and must stay disabled until
  verified and reconciled against the same-day closing daily volume.
  Never use an unknown-unit field-contract assertion as a substitute for
  the actual measurement (DSA v5 P0-3).

A ratio in the 0.1-10x band is NOT a unit criterion: genuine volume
surges, contractions, resume-after-suspension days and event days can
legitimately exceed it. An out-of-band ratio only triggers an alert plus
manual confirmation; it never hard-downgrades and never substitutes for
the unit assertion (DSA v5 P0-3).
"""

from __future__ import annotations

from typing import Any, Optional

SHARES_PER_LOT = 100

VOLUME_UNIT_SHARES = "shares"
VOLUME_UNIT_LOTS = "lots"
VOLUME_UNIT_UNVERIFIED = "unverified"

# Volume-change ratio band that triggers an alert + manual confirmation.
# NOT a unit criterion (see module docstring).
VOLUME_CHANGE_ALERT_LOW = 0.1
VOLUME_CHANGE_ALERT_HIGH = 10.0


def is_star_market(code: str) -> bool:
    """Whether the code is a STAR Market stock (688/689), whose volume is shares."""
    text = (code or "").strip().lower()
    if text[:2] in ("sh", "sz", "bj"):
        text = text[2:]
    return text.startswith(("688", "689"))


def lots_to_shares(volume: Any, code: str = "") -> Any:
    """Convert a lots-denominated volume to shares.

    STAR Market (688/689) volumes are already in shares and pass through
    unchanged; every other A-share volume is multiplied by 100.
    Non-numeric input is returned unchanged so callers keep their own
    missing-value handling.
    """
    try:
        value = float(volume)
    except (TypeError, ValueError):
        return volume
    return value if is_star_market(code) else value * SHARES_PER_LOT


def is_verified_shares_unit(unit: Optional[str]) -> bool:
    """True only when the unit is explicitly verified as shares."""
    return unit == VOLUME_UNIT_SHARES


def volume_ratio_needs_confirmation(ratio: Optional[float]) -> bool:
    """Whether a volume-change ratio is outside the alert band.

    Out-of-band only means "alert + manual confirmation"; it says nothing
    about the unit and must not be used as a unit test.
    """
    if ratio is None:
        return False
    try:
        value = float(ratio)
    except (TypeError, ValueError):
        return False
    return value < VOLUME_CHANGE_ALERT_LOW or value > VOLUME_CHANGE_ALERT_HIGH
