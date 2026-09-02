# PRD implementation and validation status

This matrix separates repository capability from the evidence available for it.
“Implemented” means the production path exists; “Validated” means automated tests
and/or the authoritative final-evidence pipeline exercise it. It does not imply
production readiness or real-payment certification.

| Phase | Implementation status | Validation status | Evidence and limitation |
|---|---|---|---|
| 1 — Domain and use case | Implemented | Validated | Typed India mobility context/outcome separation, integer-paise `Money`, seven supported cities, and structured validation. |
| 2 — Baselines | Implemented | Validated | Exact Estimate and Fixed 20% share the strategy/evaluation contracts and identical outcomes. |
| 3 — Simulator | Implemented | Validated | Seeded synthetic India mobility generator, diagnostics, serialization, and reproducibility tests. Data is synthetic. |
| 4 — Prediction engine | Implemented | Validated with limitation | Q05–Q99 fare-ratio gradient boosting, leakage-safe features, crossing repair, persistence, and calibration metrics. Fresh evidence shows material Q97/Q99 under-coverage; recalibration and external validation are required before production claims. |
| 5 — Optimization | Implemented | Validated | Quantile CDF, expected-excess integration, deterministic candidates, normalized objective, true-minimum selection, and strategy adapter. |
| 6 — Risk profiles | Implemented | Validated with limitation | Aggressive, Balanced, and Conservative policy floors are evaluated on the full fresh cohort. Collapse diagnostics show the profiles frequently select the same objective optimum. |
| 7 — Personalization | Implemented | Validated with limitation | Completion-time-safe history, deterministic cold start, Base-vs-Personalized prediction/downstream comparisons, history-depth buckets, and observed segments. No merchant personalization or production customer data. |
| 8 — Dynamic re-optimization | Implemented | Validated | Versioned updates, frozen history, additional-block recommendations, confirmation safety, static-vs-dynamic metrics, and outcome benefit categories. Evaluation assumes simulated authorization success. |
| 9 — Explainability | Implemented | Validated | Structured evidence, deterministic rendering, guarded optional generation, numeric-consistency checks, fallback accounting, and privacy checks. |
| 10 — Reserve Pay execution | Mock implementation complete; Razorpay network mapping intentionally unavailable | Mock lifecycle validated | Provider-neutral create/increase/debit/release/status, idempotency, retry, failure preservation, settlement, and reconciliation. No real Razorpay API mapping is fabricated without verified documentation. |
| 11 — Dashboard | Implemented | Validated | Exactly three React screens backed by the FastAPI adapter; production build and component tests pass. Advanced evidence is shown inside the Evidence screen. |
| 12 — Agent layer | Implemented | Validated | Allowlisted bounded orchestration, success/failure audit trace, deterministic explanations, timing diagnostics, and exact direct-service equivalence across block, probability, profile, mode, and objective. Agents cannot move funds. |
| 13 — Evaluation and evidence | Implemented | Validated | One 20,000-ride authoritative artifact plus a generated Markdown summary, canonical dataset/evidence fingerprints, strategy/risk/personalization/dynamic/city/agent/explanation/mock proof, and fail-closed validation. |
| 14 — Final demonstration | Draft runbook available | Not PRD-validated | The checked-in preliminary runbook ties the problem, optimizer, dynamic failure safety, mock execution, and authoritative evidence into a 3–5 minute flow. A separate read-only PRD audit must decide Phase-14 readiness. |

## Current authoritative evidence

- JSON: `demo/evidence/final_evidence.json`
- Generated summary: `demo/evidence/final_evidence_summary.md`
- Default cohort: 20,000 fresh synthetic rides, seed `202613`
- Dynamic cohort: 5,000 synthetic rides, seed `202714`
- Agent cohort: 500 rides
- Models are loaded from trusted project artifacts; evidence generation does not retrain them.
- `demo/evidence/dashboard_evidence.json` is a deprecated Phase-11 regression fixture and is not authoritative.

## Boundaries retained

- Actual fare enters only retrospective evaluation and completed-ride settlement.
- Browser code presents backend results; it does not duplicate financial formulas.
- Mock execution is offline and makes no external payment-network call.
- MongoDB is optional. Demo/test operation requires no database and uses in-memory state and checked-in fixtures.
- All current training and evaluation data is synthetic.

## Completion check

```powershell
python -m unittest discover -s tests -v
python -m reserve_pay_optimizer prepare-final-evidence
cd frontend
pnpm test
pnpm run build
```

The evidence command validates every required section before atomically publishing
the JSON and Markdown files. Agent timing is observational and excluded from the
canonical evidence fingerprint; financial metrics and configuration are included.
