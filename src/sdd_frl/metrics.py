from __future__ import annotations

from typing import Any

PATTERNS = (
    "repeated_clarification",
    "repeated_execution",
    "unmet_expectation",
)
EFFICIENCY_KEYS = (
    "turn_count",
    "clarification_count",
    "repeated_clarification_count",
    "execution_attempt_count",
    "rework_count",
)


def rounded(value: float) -> float:
    return round(value, 6)


def median(values: list[int]) -> int | float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return rounded((ordered[middle - 1] + ordered[middle]) / 2)


def distribution(values: list[int]) -> dict[str, Any]:
    ordered = sorted(values)
    total = sum(ordered)
    return {
        "sample_count": len(ordered),
        "total": total,
        "average": rounded(total / len(ordered)) if ordered else None,
        "median": median(ordered),
        "values": ordered,
    }


def rate(numerator: int, denominator: int) -> float | None:
    return rounded(numerator / denominator) if denominator else None


def build_metrics(
    *,
    run: dict[str, Any],
    findings: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    tasks = findings["task_episodes"]
    complete = [item for item in tasks if item["context_status"] == "complete"]
    task_counts = {
        "total": len(tasks),
        "complete": len(complete),
        "truncated": len(tasks) - len(complete),
        "achieved": sum(item["outcome_status"] == "achieved" for item in tasks),
        "not_achieved": sum(item["outcome_status"] == "not_achieved" for item in tasks),
        "unknown": sum(item["outcome_status"] == "unknown" for item in tasks),
        "known_outcome": sum(item["outcome_status"] != "unknown" for item in tasks),
    }
    efficiency = {
        key: distribution([item["counts"][key] for item in complete])
        for key in EFFICIENCY_KEYS
    }
    complete_ids = {item["task_episode_id"] for item in complete}
    pattern_counts = {
        pattern: len({
            item["task_episode_id"]
            for item in findings["problem_instances"]
            if item["pattern"] == pattern and item["task_episode_id"] in complete_ids
        })
        for pattern in PATTERNS
    }
    params = run["parameters"]
    return {
        "schema_version": "1.0.0",
        "contract_revision": params["contract_revision"],
        "contract_bundle_hash": params["contract_bundle_hash"],
        "run_id": run["run_id"],
        "project_id": params["project_id"],
        "generated_at": generated_at,
        "target_scope": {
            "improvement_target_ids": params["improvement_target_ids"],
            "target_set_hash": params["target_set_hash"],
            "contract_revision": params["contract_revision"],
            "contract_bundle_hash": params["contract_bundle_hash"],
        },
        "task_counts": task_counts,
        "attainment_rate": rate(task_counts["achieved"], task_counts["known_outcome"]),
        "outcome_coverage": rate(task_counts["known_outcome"], task_counts["total"]),
        "efficiency": efficiency,
        "pattern_task_counts": pattern_counts,
        "pattern_rates": {
            key: rate(value, len(complete))
            for key, value in pattern_counts.items()
        },
    }


def build_trend(
    *,
    run: dict[str, Any],
    metrics: dict[str, Any],
    baseline: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    baseline_task_counts = {
        key: sum(item["task_counts"][key] for item in baseline)
        for key in (
            "total",
            "complete",
            "truncated",
            "achieved",
            "not_achieved",
            "unknown",
            "known_outcome",
        )
    }
    available = (
        metrics["task_counts"]["complete"] >= 3
        and baseline_task_counts["complete"] >= 3
    )

    def delta(current: float | int | None, previous: float | int | None, enabled: bool = True):
        if not available or not enabled or current is None or previous is None:
            return None
        return rounded(float(current) - float(previous))

    efficiency_values = {
        key: [
            value
            for item in baseline
            for value in item["efficiency"][key]["values"]
        ]
        for key in EFFICIENCY_KEYS
    }
    pattern_counts = {
        pattern: sum(item["pattern_task_counts"][pattern] for item in baseline)
        for pattern in PATTERNS
    }
    baseline_attainment = rate(
        baseline_task_counts["achieved"],
        baseline_task_counts["known_outcome"],
    )
    baseline_coverage = rate(
        baseline_task_counts["known_outcome"],
        baseline_task_counts["total"],
    )
    enough_known = (
        metrics["task_counts"]["known_outcome"] >= 3
        and baseline_task_counts["known_outcome"] >= 3
    )
    return {
        "schema_version": "1.0.0",
        "contract_revision": run["parameters"]["contract_revision"],
        "contract_bundle_hash": run["parameters"]["contract_bundle_hash"],
        "run_id": run["run_id"],
        "project_id": run["parameters"]["project_id"],
        "generated_at": generated_at,
        "status": "available" if available else "insufficient_data",
        "interpretation": "observational_only",
        "target_scope": metrics["target_scope"],
        "baseline_run_ids": [item["run_id"] for item in baseline[:7]],
        "current_valid_task_count": metrics["task_counts"]["complete"],
        "baseline_valid_task_count": baseline_task_counts["complete"],
        "target_change_detected": any(
            item["target_scope"]["target_set_hash"]
            != metrics["target_scope"]["target_set_hash"]
            for item in baseline
        ),
        "deltas": {
            "attainment_rate": delta(metrics["attainment_rate"], baseline_attainment, enough_known),
            "outcome_coverage": delta(metrics["outcome_coverage"], baseline_coverage),
            "turn_count_median": delta(
                metrics["efficiency"]["turn_count"]["median"],
                median(efficiency_values["turn_count"]),
            ),
            "clarification_count_median": delta(
                metrics["efficiency"]["clarification_count"]["median"],
                median(efficiency_values["clarification_count"]),
            ),
            "repeated_clarification_count_median": delta(
                metrics["efficiency"]["repeated_clarification_count"]["median"],
                median(efficiency_values["repeated_clarification_count"]),
            ),
            "execution_attempt_count_median": delta(
                metrics["efficiency"]["execution_attempt_count"]["median"],
                median(efficiency_values["execution_attempt_count"]),
            ),
            "rework_count_median": delta(
                metrics["efficiency"]["rework_count"]["median"],
                median(efficiency_values["rework_count"]),
            ),
            "repeated_clarification_rate": delta(
                metrics["pattern_rates"]["repeated_clarification"],
                rate(pattern_counts["repeated_clarification"], baseline_task_counts["complete"]),
            ),
            "repeated_execution_rate": delta(
                metrics["pattern_rates"]["repeated_execution"],
                rate(pattern_counts["repeated_execution"], baseline_task_counts["complete"]),
            ),
            "unmet_expectation_rate": delta(
                metrics["pattern_rates"]["unmet_expectation"],
                rate(pattern_counts["unmet_expectation"], baseline_task_counts["complete"]),
            ),
        },
    }
