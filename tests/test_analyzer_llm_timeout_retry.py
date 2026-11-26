# -*- coding: utf-8 -*-
"""Tests for LLM single-call timeout retry + fallback in Analyzer._call_litellm_impl.

Covers the fix for the two failed trial runs (run 45720075769 and
run 45728100232): a hung Gemini call consumed the whole 300s per-stock
budget because the LiteLLM call had no per-call timeout and the fallback
loop only advances on exceptions. The fix bounds each attempt to the
configured per-call timeout, retries the same model on timeout-like
failures, then falls through to the next configured model.
"""
import sys
from concurrent.futures import CancelledError
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Stub heavy dependencies before project imports
for _mod in ("litellm", "google.generativeai", "google.genai", "anthropic"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

import pytest

from src.config import Config


class FakeAPITimeoutError(Exception):
    """Stand-in for litellm.Timeout / openai.APITimeoutError (name-based)."""


class FakeRateLimitError(Exception):
    """Stand-in for a rate-limit error: must NOT be retried on the same model."""


def _response(text, model="gemini/gemini-3.6-flash"):
    return SimpleNamespace(
        model=model,
        usage=None,
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
    )


def _make_analyzer(**config_overrides):
    cfg_kwargs = {
        "litellm_model": "gemini/gemini-3.6-flash",
        "litellm_fallback_models": ["gemini/gemini-3.5-flash-lite"],
        "llm_call_timeout_seconds": 90.0,
        "llm_call_max_attempts": 3,
        "llm_call_retry_backoff_seconds": 2.0,
        "gemini_request_delay": 0,
        "report_integrity_enabled": False,
    }
    cfg_kwargs.update(config_overrides)
    from src.analyzer import GeminiAnalyzer

    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    analyzer._router = None
    analyzer._litellm_available = True
    analyzer._config_override = Config(**cfg_kwargs)
    return analyzer


def _call(analyzer, generation_config=None):
    return analyzer._call_litellm_impl(
        "prompt",
        generation_config or {"temperature": 0.7, "max_tokens": 100},
        system_prompt="system",
    )


class TestLLMCallTimeoutRetry:
    def test_timeout_then_success_retries_same_model(self):
        analyzer = _make_analyzer()
        calls = []

        def dispatch(model, kwargs, **_):
            calls.append((model, kwargs.get("timeout")))
            if len([c for c in calls if c[0] == model]) == 1:
                raise TimeoutError("Request timed out")
            return _response("ok", model=model)

        with patch.object(analyzer, "_dispatch_litellm_completion", side_effect=dispatch), \
                patch("time.sleep") as mock_sleep:
            text, model_used, _usage = _call(analyzer)

        assert text == "ok"
        assert model_used == "gemini/gemini-3.6-flash"
        assert len(calls) == 2
        assert all(timeout == 90.0 for _model, timeout in calls)
        mock_sleep.assert_called_once_with(2.0)

    def test_primary_timeouts_three_times_falls_back(self):
        analyzer = _make_analyzer(llm_call_retry_backoff_seconds=0.0)
        calls = []

        def dispatch(model, kwargs, **_):
            calls.append(model)
            if model == "gemini/gemini-3.6-flash":
                raise FakeAPITimeoutError("litellm timeout")
            return _response("fallback-ok", model=model)

        with patch.object(analyzer, "_dispatch_litellm_completion", side_effect=dispatch):
            text, model_used, _usage = _call(analyzer)

        assert text == "fallback-ok"
        assert model_used == "gemini/gemini-3.5-flash-lite"
        assert calls.count("gemini/gemini-3.6-flash") == 3
        assert calls.count("gemini/gemini-3.5-flash-lite") == 1

    def test_all_models_timeout_raises(self):
        from src.analyzer import _AllModelsFailedError

        analyzer = _make_analyzer(llm_call_retry_backoff_seconds=0.0)
        calls = []

        def dispatch(model, kwargs, **_):
            calls.append(model)
            raise TimeoutError("timed out")

        with patch.object(analyzer, "_dispatch_litellm_completion", side_effect=dispatch):
            with pytest.raises(_AllModelsFailedError):
                _call(analyzer)

        assert calls.count("gemini/gemini-3.6-flash") == 3
        assert calls.count("gemini/gemini-3.5-flash-lite") == 3

    def test_normal_call_single_attempt(self):
        analyzer = _make_analyzer()
        calls = []

        def dispatch(model, kwargs, **_):
            calls.append((model, kwargs.get("timeout")))
            return _response("ok", model=model)

        with patch.object(analyzer, "_dispatch_litellm_completion", side_effect=dispatch):
            text, model_used, _usage = _call(analyzer)

        assert text == "ok"
        assert len(calls) == 1
        assert calls[0][1] == 90.0

    def test_rate_limit_not_retried_same_model(self):
        analyzer = _make_analyzer(llm_call_retry_backoff_seconds=0.0)
        calls = []

        def dispatch(model, kwargs, **_):
            calls.append(model)
            if model == "gemini/gemini-3.6-flash":
                raise FakeRateLimitError("rate limit exceeded")
            return _response("fallback-ok", model=model)

        with patch.object(analyzer, "_dispatch_litellm_completion", side_effect=dispatch):
            text, model_used, _usage = _call(analyzer)

        assert text == "fallback-ok"
        assert calls == ["gemini/gemini-3.6-flash", "gemini/gemini-3.5-flash-lite"]

    def test_cancelled_error_not_retried_same_model(self):
        analyzer = _make_analyzer(llm_call_retry_backoff_seconds=0.0)
        calls = []

        def dispatch(model, kwargs, **_):
            calls.append(model)
            if model == "gemini/gemini-3.6-flash":
                raise CancelledError("Stock analysis cancelled")
            return _response("fallback-ok", model=model)

        with patch.object(analyzer, "_dispatch_litellm_completion", side_effect=dispatch):
            text, model_used, _usage = _call(analyzer)

        assert text == "fallback-ok"
        assert calls == ["gemini/gemini-3.6-flash", "gemini/gemini-3.5-flash-lite"]

    def test_empty_response_not_retried(self):
        analyzer = _make_analyzer(llm_call_retry_backoff_seconds=0.0)
        calls = []

        def dispatch(model, kwargs, **_):
            calls.append(model)
            if model == "gemini/gemini-3.6-flash":
                return _response("", model=model)
            return _response("fallback-ok", model=model)

        with patch.object(analyzer, "_dispatch_litellm_completion", side_effect=dispatch):
            text, model_used, _usage = _call(analyzer)

        assert text == "fallback-ok"
        assert calls == ["gemini/gemini-3.6-flash", "gemini/gemini-3.5-flash-lite"]

    def test_generation_config_timeout_takes_smaller_value(self):
        analyzer = _make_analyzer()
        seen = []

        def dispatch(model, kwargs, **_):
            seen.append(kwargs.get("timeout"))
            return _response("ok", model=model)

        with patch.object(analyzer, "_dispatch_litellm_completion", side_effect=dispatch):
            text, _model, _usage = _call(analyzer, {"temperature": 0.7, "max_tokens": 100, "timeout": 30})

        assert text == "ok"
        assert seen == [30.0]
