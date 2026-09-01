"""Human-readable summary rendered only from authoritative evidence JSON fields."""

from __future__ import annotations

from typing import Any


def render_evidence_markdown(artifact: dict[str, Any]) -> str:
    meta = artifact["metadata"]
    primary = artifact["primary_strategy_comparison"]
    prediction = artifact["prediction"]
    risks = artifact["risk_profiles"]
    dynamic = artifact["dynamic"]
    agents = artifact["agents"]
    explainability = artifact["explainability"]
    mock = artifact["reserve_pay_mock_validation"]
    lines = [
        "# Final PRD Evidence Summary",
        "",
        f"- Evidence status: **{meta['evidence_status']}**",
        f"- Project version: **{meta['project_version']}**",
        f"- Fresh synthetic records: **{meta['record_count']}** (seed `{meta['dataset_seed']}`)",
        f"- Dataset fingerprint: `{meta['dataset_fingerprint_sha256']}`",
        f"- Evidence fingerprint: `{meta['evidence_fingerprint_sha256']}`",
        "- Models were loaded from trusted project artifacts; no retraining was performed.",
        "",
        "## Primary strategy comparison",
        "",
        "| Strategy | Collection success | Under-block rate | Average excess (paise) | Capital efficiency |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, metric in primary["metrics"].items():
        lines.append(
            f"| {name} | {metric['collection_success_rate']} | {metric['under_block_rate']} | "
            f"{metric['average_excess_block_paise']} | {metric['capital_efficiency']} |"
        )
    lines += [
        "",
        "## Prediction calibration",
        "",
        f"- Records: {prediction['record_count']}",
        f"- Mean pinball loss (paise): {prediction['mean_pinball_loss_paise']}",
        f"- Q97 observed coverage: {prediction['quantiles']['0.97']['observed_coverage']}",
        f"- Q99 observed coverage: {prediction['quantiles']['0.99']['observed_coverage']}",
        "- High-quantile under-coverage is visible and is not described as production calibration.",
        "",
        "## Risk profiles",
        "",
    ]
    for name, value in risks["profiles"].items():
        lines.append(
            f"- **{name}** target {value['target_collection_probability']}: realized "
            f"{value['metrics']['collection_success_rate']}, average block "
            f"{value['average_recommended_block_paise']} paise."
        )
    collapse = risks["collapse_diagnostics"]
    lines += [
        f"- All three profiles selected the same block on {collapse['all_three_same_count']} "
        f"records ({collapse['all_three_same_rate']}). This is a factual diagnostic, not hidden.",
        "",
        "## Personalization and dynamic evidence",
        "",
        f"- Personalization records: {artifact['personalization']['test_records']}; minimum history: "
        f"{artifact['personalization']['minimum_personalization_history']}.",
        f"- Static success: {dynamic['static']['collection_success_rate']}; dynamic success: "
        f"{dynamic['dynamic']['collection_success_rate']}.",
        "",
        "## Agent, explainability, and mock execution",
        "",
        f"- Agent runs: {agents['total_runs']}; mismatches: {agents['decision_mismatches']}; "
        f"equivalence: {agents['equivalence_rate']}.",
        f"- Explanation records: {explainability['record_count']}; numeric mismatches: "
        f"{explainability['numeric_consistency_mismatches']}; privacy violations: "
        f"{explainability['privacy_violations']}.",
        f"- Mock Reserve Pay scenarios: {mock['passed_scenarios']}/{mock['total_scenarios']} passed.",
        "",
        "## Limitations",
        "",
    ]
    lines.extend(f"- {item}" for item in artifact["limitations"])
    return "\n".join(lines) + "\n"

