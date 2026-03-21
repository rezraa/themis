# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""Knowledge loader for Themis.

Loads test_strategies.json, agent_patterns.json, decision_rules.json, and
frameworks.json and provides pure retrieval, structural signal matching
(exact substring against decision_rules), and constraint filtering.

No fuzzy keyword matching.  No tokenization.  No Jaccard scoring.
"""

from __future__ import annotations

import json
from pathlib import Path

_KNOWLEDGE_DIR = Path(__file__).parent

# ---------------------------------------------------------------------------
# Complexity / execution speed ranking — lower index = faster / lighter.
# ---------------------------------------------------------------------------
_SETUP_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2}
_MAINTENANCE_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2}
_EXECUTION_RANK: dict[str, int] = {"fast": 0, "medium": 1, "slow": 2}


class KnowledgeLoader:
    """Loads and queries the Themis knowledge base (test strategies,
    agent patterns, decision rules, frameworks).

    All matching is structural / exact / data-driven.  No fuzzy keyword overlap.
    """

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def __init__(self, knowledge_dir: Path | None = None) -> None:
        self._dir = knowledge_dir or _KNOWLEDGE_DIR

        with open(self._dir / "test_strategies.json", encoding="utf-8") as f:
            self._strategies_data = json.load(f)

        with open(self._dir / "agent_patterns.json", encoding="utf-8") as f:
            self._agent_patterns_data = json.load(f)

        with open(self._dir / "decision_rules.json", encoding="utf-8") as f:
            self._decision_rules_data = json.load(f)

        with open(self._dir / "frameworks.json", encoding="utf-8") as f:
            self._frameworks_data = json.load(f)

        # Build convenience indices.
        self._strategies: list[dict] = self._strategies_data["strategies"]
        self._agent_patterns: list[dict] = self._agent_patterns_data["patterns"]
        self._rules: list[dict] = self._decision_rules_data["rules"]
        self._frameworks: list[dict] = self._frameworks_data["frameworks"]

        # Index: strategy_id -> strategy_dict
        self._strategy_index: dict[str, dict] = {
            s["id"]: s for s in self._strategies
        }

        # Index: pattern_id -> pattern_dict
        self._pattern_index: dict[str, dict] = {
            p["id"]: p for p in self._agent_patterns
        }

        # Index: framework_id -> framework_dict
        self._framework_index: dict[str, dict] = {
            f["id"]: f for f in self._frameworks
        }

        # Build rule index: normalised structural_signal -> rule
        # Used for exact substring matching in match_structural_signals().
        self._rule_signal_index: dict[str, dict] = {}
        for rule in self._rules:
            signal = rule.get("structural_signal", "").lower().strip()
            if signal:
                self._rule_signal_index[signal] = rule

    # ------------------------------------------------------------------
    # Pure retrieval — strategies
    # ------------------------------------------------------------------

    def get_strategy(self, strategy_id: str) -> dict | None:
        """Get a test strategy by ID."""
        return self._strategy_index.get(strategy_id)

    def get_strategies_by_ids(self, ids: list[str]) -> list[dict]:
        """Batch retrieval of strategies by ID."""
        results: list[dict] = []
        for sid in ids:
            s = self._strategy_index.get(sid)
            if s is not None:
                results.append(s)
        return results

    def get_all_strategies(self) -> list[dict]:
        """Get all test strategies."""
        return list(self._strategies)

    def get_strategies_by_category(self, category: str) -> list[dict]:
        """Get all strategies in a given category."""
        return [s for s in self._strategies if s.get("category") == category]

    # ------------------------------------------------------------------
    # Pure retrieval — agent patterns
    # ------------------------------------------------------------------

    def get_pattern(self, pattern_id: str) -> dict | None:
        """Get an agent testing pattern by ID."""
        return self._pattern_index.get(pattern_id)

    def get_all_agent_patterns(self) -> list[dict]:
        """Get all agent-specific testing patterns."""
        return list(self._agent_patterns)

    def get_agent_patterns_by_severity(self, severity: str) -> list[dict]:
        """Get agent patterns filtered by severity (critical/high/medium/low)."""
        return [p for p in self._agent_patterns if p.get("severity") == severity]

    def get_agent_patterns_by_adapter(self, adapter: str) -> list[dict]:
        """Get agent patterns that support a given adapter (websocket, http,
        stdio, stream)."""
        return [
            p for p in self._agent_patterns
            if adapter in p.get("adapters", [])
        ]

    # ------------------------------------------------------------------
    # Pure retrieval — frameworks
    # ------------------------------------------------------------------

    def get_framework(self, framework_id: str) -> dict | None:
        """Get a framework by ID."""
        return self._framework_index.get(framework_id)

    def get_all_frameworks(self) -> list[dict]:
        """Get all frameworks."""
        return list(self._frameworks)

    def get_frameworks_by_language(self, language: str) -> list[dict]:
        """Get frameworks that support a given language."""
        return [
            f for f in self._frameworks
            if f.get("language") == language or f.get("language") == "multi"
        ]

    def get_frameworks_by_category(self, category: str) -> list[dict]:
        """Get frameworks that support a given testing category."""
        return [
            f for f in self._frameworks
            if category in f.get("categories", [])
        ]

    def get_frameworks_with_agent_support(self) -> list[dict]:
        """Get frameworks with native or plugin agent testing support."""
        return [
            f for f in self._frameworks
            if f.get("agent_testing_support") in ("native", "plugin")
        ]

    # ------------------------------------------------------------------
    # Alternatives
    # ------------------------------------------------------------------

    def get_alternatives(self, strategy_id: str) -> list[dict]:
        """Find alternative strategies for *strategy_id*.

        Returns a list of strategy dicts for each alternative.
        """
        strategy = self._strategy_index.get(strategy_id)
        if strategy is None:
            return []

        alt_ids: list[str] = strategy.get("alternatives", [])
        results: list[dict] = []

        for alt_id in alt_ids:
            alt = self._strategy_index.get(alt_id)
            if alt is not None:
                results.append(alt)
            else:
                results.append({"id": alt_id, "name": alt_id})

        return results

    # ------------------------------------------------------------------
    # Compatible frameworks for a strategy
    # ------------------------------------------------------------------

    def get_compatible_frameworks(self, strategy_id: str) -> list[dict]:
        """Get full framework details for all compatible frameworks of a
        strategy."""
        strategy = self._strategy_index.get(strategy_id)
        if strategy is None:
            return []

        framework_ids: list[str] = strategy.get("compatible_frameworks", [])
        results: list[dict] = []

        for fid in framework_ids:
            fw = self._framework_index.get(fid)
            if fw is not None:
                results.append(fw)

        return results

    # ------------------------------------------------------------------
    # Compact index
    # ------------------------------------------------------------------

    def get_compact_index(self) -> list[dict]:
        """Return id + name + category + structural_signals only, for each
        strategy.

        Useful for the agent to scan available strategies without pulling
        full details.
        """
        results: list[dict] = []
        for s in self._strategies:
            results.append({
                "id": s["id"],
                "name": s.get("name", s["id"]),
                "category": s.get("category", ""),
                "structural_signals": s.get("structural_signals", []),
            })
        return results

    # ------------------------------------------------------------------
    # Structural matching — exact against decision_rules.json
    # ------------------------------------------------------------------

    def match_structural_signals(self, signals: list[str]) -> list[dict]:
        """Given structural signals identified by the agent, find matching
        decision rules.

        Matching is exact substring on the ``structural_signal`` field of
        each rule — NOT fuzzy keyword overlap.

        Returns matching rules augmented with full strategy and framework
        details::

            [{"rule": {...}, "recommended_strategy": {...},
              "recommended_framework": {...},
              "alternatives": [...]}]
        """
        if not signals:
            return []

        results: list[dict] = []
        seen_rule_ids: set[str] = set()

        for signal in signals:
            signal_lower = signal.lower().strip()
            if not signal_lower:
                continue

            for rule_signal, rule in self._rule_signal_index.items():
                if rule["id"] in seen_rule_ids:
                    continue

                # Exact substring match: the agent's signal appears in the
                # rule's structural_signal, or vice versa.
                if signal_lower in rule_signal or rule_signal in signal_lower:
                    seen_rule_ids.add(rule["id"])

                    # Resolve recommended strategy
                    rec_strategy_id = rule.get("recommended_strategy", "")
                    rec_strategy = self.get_strategy(rec_strategy_id)

                    # Resolve recommended framework
                    rec_framework_id = rule.get("recommended_framework", "")
                    rec_framework = self.get_framework(rec_framework_id)

                    # Resolve alternatives
                    alt_ids = rule.get("alternatives", [])
                    alternatives = []
                    for alt_id in alt_ids:
                        alt_strat = self.get_strategy(alt_id)
                        if alt_strat:
                            alternatives.append(alt_strat)
                        else:
                            alternatives.append({"id": alt_id, "name": alt_id})

                    results.append({
                        "rule": rule,
                        "signal": signal,
                        "recommended_strategy": rec_strategy,
                        "recommended_framework": rec_framework,
                        "alternatives": alternatives,
                    })

        return results

    # ------------------------------------------------------------------
    # Constraint filtering — data-driven from strategy complexity
    # ------------------------------------------------------------------

    def filter_by_constraints(
        self,
        strategies: list[dict],
        constraints: dict,
    ) -> tuple[list[dict], list[dict]]:
        """Filter strategies by constraints.

        Args:
            strategies: List of strategy dicts (each must have ``complexity``
                with ``setup``, ``maintenance``, ``execution`` keys).
            constraints: Dict with optional keys:
                - ``language`` (str): target language
                - ``category`` (str): target category
                - ``max_setup`` (str): max setup complexity ("low"/"medium"/"high")
                - ``max_maintenance`` (str): max maintenance complexity
                - ``max_execution`` (str): max execution speed ("fast"/"medium"/"slow")
                - ``agent_testing_support`` (str): "native"/"plugin"/"none"

        Returns:
            (surviving, filtered_out) where each filtered_out entry has
            a ``filter_reason`` key explaining why it was removed.
        """
        language = constraints.get("language")
        category = constraints.get("category")
        max_setup = constraints.get("max_setup")
        max_maintenance = constraints.get("max_maintenance")
        max_execution = constraints.get("max_execution")
        agent_support = constraints.get("agent_testing_support")

        surviving: list[dict] = []
        filtered_out: list[dict] = []

        for strat in strategies:
            complexity = strat.get("complexity", {})
            reason = None

            # --- category filter ---
            if category and strat.get("category") != category:
                reason = f"category '{strat.get('category')}' != '{category}'"

            # --- setup complexity filter ---
            if reason is None and max_setup:
                setup = complexity.get("setup", "low")
                if _SETUP_RANK.get(setup, 0) > _SETUP_RANK.get(max_setup, 2):
                    reason = f"setup '{setup}' exceeds max '{max_setup}'"

            # --- maintenance complexity filter ---
            if reason is None and max_maintenance:
                maint = complexity.get("maintenance", "low")
                if _MAINTENANCE_RANK.get(maint, 0) > _MAINTENANCE_RANK.get(max_maintenance, 2):
                    reason = f"maintenance '{maint}' exceeds max '{max_maintenance}'"

            # --- execution speed filter ---
            if reason is None and max_execution:
                exec_speed = complexity.get("execution", "fast")
                if _EXECUTION_RANK.get(exec_speed, 0) > _EXECUTION_RANK.get(max_execution, 2):
                    reason = f"execution '{exec_speed}' exceeds max '{max_execution}'"

            # --- language filter (check compatible frameworks) ---
            if reason is None and language:
                fw_ids = strat.get("compatible_frameworks", [])
                has_lang = False
                for fid in fw_ids:
                    fw = self._framework_index.get(fid)
                    if fw and (fw.get("language") == language or fw.get("language") == "multi"):
                        has_lang = True
                        break
                if not has_lang:
                    reason = f"no compatible framework for language '{language}'"

            # --- agent testing support filter ---
            if reason is None and agent_support:
                fw_ids = strat.get("compatible_frameworks", [])
                has_support = False
                for fid in fw_ids:
                    fw = self._framework_index.get(fid)
                    if fw and fw.get("agent_testing_support") == agent_support:
                        has_support = True
                        break
                if not has_support:
                    reason = f"no framework with agent_testing_support='{agent_support}'"

            if reason:
                entry = dict(strat)
                entry["filter_reason"] = reason
                filtered_out.append(entry)
            else:
                surviving.append(strat)

        return surviving, filtered_out
