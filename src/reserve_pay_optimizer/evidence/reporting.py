"""Human-readable summary rendered only from authoritative evidence JSON fields."""

from __future__ import annotations

from typing import Any


def render_evidence_markdown(artifact: dict[str, Any]) -> str:
    meta = artifact["metadata"]
    primary = artifact["primary_strategy_comparison"]
    prediction = artifact["prediction"]
    personalization = artifact["personalization"]
    risks = artifact["risk_profiles"]
    dynamic = artifact["dynamic"]
    cities = artifact["cities"]
    agents = artifact["agents"]
    explainability = artifact["explainability"]
    mock = artifact["reserve_pay_mock_validation"]
    lines = [
        "# Reserve Pay Block Optimizer — Final Evidence",
        "",
        "## Dataset Provenance",
        "",
        f"- Evidence status: **{meta['evidence_status']}**",
        f"- Project version: **{meta['project_version']}**",
        f"- Fresh synthetic records: **{meta['record_count']}** (seed `{meta['dataset_seed']}`)",
        f"- Dataset fingerprint: `{meta['dataset_fingerprint_sha256']}`",
        f"- Evidence fingerprint: `{meta['evidence_fingerprint_sha256']}`",
        "- Models were loaded from trusted project artifacts; no retraining was performed.",
        "",
        "## Primary Strategy Comparison",
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
        "## Prediction Calibration",
        "",
        f"- Records: {prediction['record_count']}",
        f"- Mean pinball loss (paise): {prediction['mean_pinball_loss_paise']}",
        "",
        "| Quantile | Target | Observed | Calibration error | Pinball loss (paise) |",
        "|---|---:|---:|---:|---:|",
    ]
    for quantile, value in prediction["quantiles"].items():
        lines.append(
            f"| Q{int(float(quantile) * 100):02d} | {value['target_coverage']} | "
            f"{value['observed_coverage']} | {value['calibration_error']} | "
            f"{value['pinball_loss_paise']} |"
        )
    lines += [
        "",
        "- High-quantile under-coverage is visible and is not described as production calibration.",
        "",
        "## Personalization",
        "",
        f"- Records: {personalization['test_records']}; minimum eligible history: "
        f"{personalization['minimum_personalization_history']} completed rides.",
        f"- Base mean pinball loss: {personalization['base_predictor']['mean_pinball_loss_paise']} paise; "
        f"personalized: {personalization['personalized_predictor']['mean_pinball_loss_paise']} paise.",
        f"- Base Q97/Q99 coverage: {personalization['comparison']['base_q97_coverage']} / "
        f"{personalization['comparison']['base_q99_coverage']}; personalized: "
        f"{personalization['comparison']['personalized_q97_coverage']} / "
        f"{personalization['comparison']['personalized_q99_coverage']}.",
        f"- Base fallback: {personalization['fallback_record_count']} "
        f"({personalization['fallback_percentage']}); personalized: "
        f"{personalization['personalized_record_count']} "
        f"({personalization['personalized_percentage']}).",
        "",
        "## Merchant Risk Profiles",
        "",
        "| Profile | Target | Realized success | Under-block | Average block (paise) | Average excess (paise) | Capital efficiency |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, value in risks["profiles"].items():
        lines.append(
            f"| {name} | {value['target_collection_probability']} | "
            f"{value['realized_collection_success']} | {value['under_block_rate']} | "
            f"{value['average_block_paise']} | {value['average_excess_paise']} | "
            f"{value['capital_efficiency']} |"
        )
    collapse = risks["collapse_analysis"]
    lines += [
        f"- All three profiles selected the same block on {collapse['all_three_same_count']} "
        f"records ({collapse['all_three_same_rate']}). This is a factual diagnostic, not hidden.",
        "",
        "## Dynamic Re-Optimization",
        "",
        f"- Static success: {dynamic['static']['collection_success_rate']}; dynamic success: "
        f"{dynamic['dynamic']['collection_success_rate']}.",
        f"- Average initial/final block (paise): "
        f"{dynamic['dynamic_diagnostics']['average_initial_block_paise']} / "
        f"{dynamic['dynamic_diagnostics']['average_final_authorized_block_paise']}.",
        "",
        "| Outcome category | Count | Rate |",
        "|---|---:|---:|",
    ]
    for key in (
        "static_failed_dynamic_succeeded", "both_succeeded", "both_failed",
        "static_succeeded_dynamic_failed", "dynamic_no_increase_required",
    ):
        lines.append(
            f"| {key} | {dynamic['benefit_breakdown'][key]} | "
            f"{dynamic['benefit_breakdown'][key + '_rate']} |"
        )
    lines += [
        "",
        "## India-Specific Results",
        "",
        "| City | Records | Optimized success | Average excess (paise) |",
        "|---|---:|---:|---:|",
    ]
    for city, value in cities.items():
        lines.append(
            f"| {city} | {value['record_count']} | "
            f"{value['optimized_collection_success_rate']} | "
            f"{value['optimized_average_excess_block_paise']} |"
        )
    lines += [
        "",
        "## Agent Validation",
        "",
        f"- Agent runs: {agents['runs']}; mismatches: {agents['decision_mismatches']}; "
        f"equivalence: {agents['decision_equivalence_rate']}; average tool calls: "
        f"{agents['average_tool_calls']}.",
        f"- Observed execution time (ms): average {agents['average_execution_time_ms']}; "
        f"median {agents['median_execution_time_ms']}; p95 {agents['p95_execution_time_ms']}.",
        "",
        "## Explainability Validation",
        "",
        f"- Explanation records: {explainability['record_count']}; numeric mismatches: "
        f"{explainability['numeric_consistency_failures']}; privacy violations: "
        f"{explainability['privacy_violations']}; template fallbacks: "
        f"{explainability['template_fallbacks']}; generated-text failures: "
        f"{explainability['generated_text_failures']}.",
        "",
        "## Mock Reserve Pay Validation",
        "",
        f"- Mock Reserve Pay scenarios: {mock['passed_scenarios']}/{mock['total_scenarios']} passed.",
    ]
    for scenario in mock["scenarios"]:
        lines.append(
            f"- `{scenario['scenario']}`: {'PASS' if scenario['passed'] else 'FAIL'} — "
            f"expected {scenario['expected_state']}."
        )
    lines += [
        "",
        "## Limitations",
        "",
    ]
    lines.extend(f"- {item}" for item in artifact["limitations"])
    return "\n".join(lines) + "\n"
