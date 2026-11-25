# -*- coding: utf-8 -*-
"""
SkillRouter — rule-based skill selection.

Selects which trading skills to apply based on:
1. User-explicit request (highest priority)
2. Market regime detection from technical data in ``AgentContext``
3. Centralised default fallback
"""

from __future__ import annotations

import logging
from typing import List, Optional

from src.agent.protocols import AgentContext
from src.agent.skills.defaults import (
    get_default_router_skill_ids,
    get_regime_skill_ids,
)

logger = logging.getLogger(__name__)


class SkillRouter:
    """Select applicable skills for a given analysis context."""

    def select_skills(
        self,
        ctx: AgentContext,
        max_count: int = 3,
    ) -> List[str]:
        requested_skills = ctx.meta.get("skills_requested") or ctx.meta.get("strategies_requested", [])
        if requested_skills:
            logger.info("[SkillRouter] user-requested skills: %s", requested_skills)
            return requested_skills[:max_count]

        routing_mode = self._get_routing_mode()
        if routing_mode == "manual":
            selected = self._get_manual_skills(max_count=max_count)
            logger.info("[SkillRouter] manual mode — using skills: %s", selected)
            return selected

        available_skills = self._get_available_skills()
        skill_catalog = available_skills or None
        available_ids = {skill.name for skill in available_skills}
        regime = self._detect_regime(ctx)
        if regime:
            selected = get_regime_skill_ids(
                regime,
                skill_catalog,
                max_count=max_count,
                available_skill_ids=available_ids or None,
            )
            if selected:
                logger.info("[SkillRouter] regime=%s -> skills: %s", regime, selected)
                return selected

        # DSA v5 P0-8: no technical view, no default skill. When the
        # regime is unknown (no MA alignment, no usable trend_score),
        # falling back to the default bull_trend skill produced a
        # bullish conclusion on a bearish trend. Return an empty list;
        # the orchestrator treats an empty selection as "no technical
        # view" instead of silently inheriting a bull bias.
        logger.info(
            "[SkillRouter] no regime detected (regime=%s); "
            "returning empty skill list, no default fallback",
            regime,
        )
        return []

    def select_strategies(
        self,
        ctx: AgentContext,
        max_count: int = 3,
    ) -> List[str]:
        """Compatibility wrapper for legacy strategy-based callers."""
        return self.select_skills(ctx, max_count=max_count)

    def _detect_regime(self, ctx: AgentContext) -> Optional[str]:
        for op in ctx.opinions:
            if op.agent_name != "technical":
                continue
            raw = op.raw_data or {}

            ma_alignment = str(raw.get("ma_alignment", "")).lower()
            # DSA v5 P0-8: a missing trend_score is "unknown", never a
            # default 50. A default 50 silently pushed bearish trends
            # into the sideways branch (35-65) and then into the
            # bull_trend default skill.
            trend_score = raw.get("trend_score")
            try:
                trend_score = float(trend_score) if trend_score is not None else None
            except (TypeError, ValueError):
                trend_score = None
            volume_status = str(raw.get("volume_status", "")).lower()

            # Direction first: MA alignment decides the regime; the score
            # only confirms it when no alignment is available. Bearish
            # alignment never falls through to sideways, even with a
            # middling score.
            if ma_alignment == "bullish":
                return "trending_up"
            if ma_alignment == "bearish":
                return "trending_down"
            if ma_alignment == "neutral":
                return "sideways"
            if trend_score is not None:
                if trend_score >= 70:
                    return "trending_up"
                if trend_score <= 30:
                    return "trending_down"
                if 35 <= trend_score <= 65:
                    return "sideways"
                if volume_status == "heavy" and 30 < trend_score < 70:
                    return "volatile"
            # Alignment unknown and no usable score: regime unknown.
            # The caller must not fall back to a default skill.
            return None

        if ctx.meta.get("sector_hot"):
            return "sector_hot"
        return None

    @staticmethod
    def _get_routing_mode() -> str:
        try:
            from src.config import get_config

            config = get_config()
            return getattr(config, "agent_skill_routing", "auto")
        except Exception:
            logger.warning("Failed to get routing mode, falling back to auto", exc_info=True)
            return "auto"

    @staticmethod
    def _get_available_ids() -> set:
        return {skill.name for skill in SkillRouter._get_available_skills()}

    @staticmethod
    def _get_available_skills() -> list:
        try:
            from src.agent.factory import _SKILL_MANAGER_PROTOTYPE

            if _SKILL_MANAGER_PROTOTYPE is not None:
                return list(_SKILL_MANAGER_PROTOTYPE.list_skills())

            from src.agent.factory import get_skill_manager

            sm = get_skill_manager()
            return list(sm.list_skills())
        except Exception:
            logger.warning("Failed to get available skills", exc_info=True)
            return []

    @classmethod
    def _get_manual_skills(cls, max_count: int) -> List[str]:
        configured: List[str] = []
        try:
            from src.config import get_config

            config = get_config()
            configured = [
                skill_id
                for skill_id in getattr(config, "agent_skills", []) or []
                if isinstance(skill_id, str) and skill_id
            ]
        except Exception:
            logger.warning("Failed to get manual skills config", exc_info=True)
            configured = []

        available_skills = cls._get_available_skills()
        skill_catalog = available_skills or None
        available = {skill.name for skill in available_skills}
        selected = [skill_id for skill_id in configured if skill_id in available][:max_count]
        if selected:
            return selected

        return get_default_router_skill_ids(
            skill_catalog,
            max_count=max_count,
            available_skill_ids=available or None,
        )


StrategyRouter = SkillRouter
_DEFAULT_STRATEGIES = tuple(get_default_router_skill_ids())
_DEFAULT_SKILLS = _DEFAULT_STRATEGIES
