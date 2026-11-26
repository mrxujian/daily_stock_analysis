# -*- coding: utf-8 -*-
"""Tests for the volume confirmation gate (DSA v5 P0-3).

An out-of-band volume ratio only raises an alert + manual confirmation
(confirmer: Rio, evidence: Wind daily K-line). There is no substitute
confirmer. A pending request that times out (2h) or crosses the next
18:00 scheduled run pauses that run.
"""

import json
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from src.services.volume_confirmation import (
    STATUS_CONFIRMED,
    confirm_request,
    is_timed_out,
    load_confirmation_state,
    next_scheduled_run,
    request_confirmation,
    should_pause_next_run,
    touch_pending_confirmation,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    # 2026-11-25 is a Wednesday (trading day).
    return datetime(2026, 11, day, hour, minute, tzinfo=SHANGHAI)


class RequestConfirmationTestCase(unittest.TestCase):
    def test_round_trip_save_load(self):
        with TemporaryDirectory() as tmp:
            state_path = str(Path(tmp) / "data" / "volume_confirmation_state.json")
            record = request_confirmation(
                "600491",
                trade_date="2026-11-25",
                volume_change_ratio=62.07,
                reason="ratio outside 0.1-10x",
                state_path=state_path,
                now=_at(25, 10),
            )
            self.assertEqual(record.code, "600491")
            self.assertEqual(record.confirmer, "Rio")
            self.assertEqual(record.status, "pending")
            self.assertEqual(record.deadline_at, _at(25, 12).isoformat())
            loaded = load_confirmation_state(state_path)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.volume_change_ratio, 62.07)
            self.assertEqual(loaded.status, "pending")

    def test_missing_state_file_loads_none(self):
        self.assertIsNone(load_confirmation_state("/nonexistent/state.json"))

    def test_confirm_marks_confirmed(self):
        with TemporaryDirectory() as tmp:
            state_path = str(Path(tmp) / "state.json")
            record = request_confirmation(
                "600491",
                trade_date="2026-11-25",
                volume_change_ratio=0.05,
                reason="ratio outside 0.1-10x",
                state_path=state_path,
                now=_at(25, 10),
            )
            confirm_request(
                record,
                confirmed_by="Rio",
                evidence="Wind daily K-line 2026-11-25 volume 28,201,300 shares",
                state_path=state_path,
                now=_at(25, 11),
            )
            self.assertEqual(record.status, STATUS_CONFIRMED)
            self.assertEqual(record.confirmed_by, "Rio")
            self.assertFalse(should_pause_next_run(record, now=_at(25, 12, 30)))


class ShouldPauseNextRunTestCase(unittest.TestCase):
    def _pending(self, now):
        with TemporaryDirectory() as tmp:
            state_path = str(Path(tmp) / "state.json")
            return request_confirmation(
                "600491",
                trade_date="2026-11-25",
                volume_change_ratio=62.07,
                reason="ratio outside 0.1-10x",
                state_path=state_path,
                now=now,
            )

    def test_none_record_never_pauses(self):
        self.assertFalse(should_pause_next_run(None, now=_at(25, 10)))

    def test_pending_inside_window_before_next_run_does_not_pause(self):
        record = self._pending(_at(25, 10))
        # 10:00 request, 12:00 deadline, next run 18:00: no pause.
        self.assertFalse(is_timed_out(record, now=_at(25, 11)))
        self.assertFalse(should_pause_next_run(record, now=_at(25, 11)))

    def test_pending_timed_out_pauses(self):
        record = self._pending(_at(25, 10))
        self.assertTrue(is_timed_out(record, now=_at(25, 12, 30)))
        self.assertTrue(should_pause_next_run(record, now=_at(25, 12, 30)))

    def test_pending_crossing_next_run_pauses(self):
        # 16:30 request, 18:30 deadline crosses the 18:00 run.
        record = self._pending(_at(25, 16, 30))
        self.assertFalse(is_timed_out(record, now=_at(25, 17)))
        self.assertTrue(should_pause_next_run(record, now=_at(25, 17)))

    def test_next_scheduled_run(self):
        self.assertEqual(next_scheduled_run(_at(25, 10)), _at(25, 18))
        self.assertEqual(next_scheduled_run(_at(25, 18, 30)), _at(26, 18))


class TouchPendingConfirmationTestCase(unittest.TestCase):
    def test_touch_stamps_pending_record_and_keeps_status(self):
        with TemporaryDirectory() as tmp:
            state_path = str(Path(tmp) / "state.json")
            request_confirmation(
                "600491",
                trade_date="2026-11-26",
                volume_change_ratio=12.5,
                reason="verification seed",
                state_path=state_path,
                now=_at(26, 9),
            )
            stamped = touch_pending_confirmation(
                state_path, run_id="12345", now=_at(26, 12, 30)
            )
            self.assertIsNotNone(stamped)
            assert stamped is not None
            self.assertEqual(stamped.status, "pending")
            self.assertEqual(stamped.last_seen_at, _at(26, 12, 30).isoformat())
            self.assertEqual(stamped.last_seen_run_id, "12345")
            loaded = load_confirmation_state(state_path)
            assert loaded is not None
            self.assertEqual(loaded.last_seen_run_id, "12345")

    def test_touch_missing_file_returns_none_and_writes_nothing(self):
        with TemporaryDirectory() as tmp:
            state_path = str(Path(tmp) / "state.json")
            self.assertIsNone(touch_pending_confirmation(state_path, run_id="1"))
            self.assertFalse(Path(state_path).exists())

    def test_touch_confirmed_record_returns_none_and_writes_nothing(self):
        with TemporaryDirectory() as tmp:
            state_path = str(Path(tmp) / "state.json")
            record = request_confirmation(
                "600491",
                trade_date="2026-11-26",
                volume_change_ratio=0.05,
                reason="ratio outside 0.1-10x",
                state_path=state_path,
                now=_at(26, 9),
            )
            confirm_request(
                record,
                confirmed_by="Rio",
                evidence="Wind daily K-line",
                state_path=state_path,
                now=_at(26, 10),
            )
            self.assertIsNone(
                touch_pending_confirmation(state_path, run_id="1", now=_at(26, 12))
            )
            loaded = load_confirmation_state(state_path)
            assert loaded is not None
            self.assertIsNone(loaded.last_seen_at)
            self.assertIsNone(loaded.last_seen_run_id)

    def test_touch_old_record_without_new_fields(self):
        # Records written before the stamp fields existed must still load
        # and be stampable (from_dict defaults).
        with TemporaryDirectory() as tmp:
            state_path = str(Path(tmp) / "state.json")
            Path(state_path).write_text(
                json.dumps(
                    {
                        "code": "600491",
                        "trade_date": "2026-11-26",
                        "volume_change_ratio": 12.5,
                        "reason": "ratio outside 0.1-10x",
                        "requested_at": _at(26, 9).isoformat(),
                        "deadline_at": _at(26, 11).isoformat(),
                        "confirmer": "Rio",
                        "status": "pending",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            stamped = touch_pending_confirmation(
                state_path, run_id="7", now=_at(26, 12)
            )
            self.assertIsNotNone(stamped)
            assert stamped is not None
            self.assertEqual(stamped.last_seen_run_id, "7")

    def test_stamped_pending_expired_record_still_pauses(self):
        # Stamping must not change the pause decision: a pending request
        # whose window expired still pauses the next run.
        with TemporaryDirectory() as tmp:
            state_path = str(Path(tmp) / "state.json")
            request_confirmation(
                "600491",
                trade_date="2026-11-26",
                volume_change_ratio=12.5,
                reason="verification seed",
                state_path=state_path,
                now=_at(26, 9),
            )
            touch_pending_confirmation(state_path, run_id="1", now=_at(26, 12, 30))
            loaded = load_confirmation_state(state_path)
            assert loaded is not None
            self.assertEqual(loaded.status, "pending")
            self.assertTrue(should_pause_next_run(loaded, now=_at(26, 12, 30)))
