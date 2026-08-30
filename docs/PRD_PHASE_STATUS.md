# PRD implementation status

This file maps the 14 phases in the source product-requirements document to
the implemented repository. “Complete” means the capability exists, is wired
through the supported entry points where applicable, and is covered by tests.

| Phase | Status | Repository evidence |
|---|---|---|
| 1 — Domain and use case | Complete | Typed India mobility context/outcome separation, integer-paise `Money`, validation, supported cities, and mobility-only boundaries. |
| 2 — Baselines | Complete | Exact Estimate and Fixed 20% strategies share the typed strategy/evaluation contracts. |
| 3 — Simulator | Complete | Seeded synthetic India mobility generator, customer pool, diagnostics, serialization, and CLI workflow. |
| 4 — Prediction engine | Complete | Q05–Q99 conditional fare-ratio gradient-boosting models, leakage-safe features, calibration, crossing repair, persistence, and trusted-artifact checks. |
| 5 — Optimization | Complete | Quantile-derived CDF, expected excess integration, candidate search, normalized objective, diagnostics, and optimized strategy adapter. |
| 6 — Risk profiles | Complete | Aggressive, Balanced, and Conservative policies constrain the existing optimizer without duplicating its objective. |
| 7 — Personalization | Complete | Completion-time-safe customer history, personalized quantile models, and deterministic cold-start fallback. Merchant personalization remains explicitly unavailable rather than fabricated. |
| 8 — Dynamic re-optimization | Complete | Stateful in-ride updates, frozen history, versioned decisions, additional-block recommendations, and explicit confirmation semantics. |
| 9 — Explainability | Complete | Structured evidence, deterministic concise/detailed renderers, validation, and optional provider-neutral generation boundary. |
| 10 — Reserve Pay execution | Complete | Provider-neutral lifecycle, deterministic mock provider, idempotency, retry, settlement, reconciliation, and an intentionally unguessed Razorpay transport boundary. |
| 11 — Dashboard | Complete | Exactly three React screens (Optimizer, What-if Simulator, Evidence) backed by FastAPI and existing Python services. |
| 12 — Agent layer | Complete | Allowlisted Reserve Intelligence and Explanation agents, bounded orchestration, audit traces, API/CLI access, and direct-decision equivalence checks. Agents cannot move funds. |
| 13 — Evaluation and evidence | Complete | Fresh 20,000-ride default cohort, strategy comparison, Q05–Q99 calibration, per-city metrics, Wilson and seeded-bootstrap intervals, dynamic evaluation, agent consistency, fingerprints, and a fail-closed artifact contract. |
| 14 — Final demonstration | Complete | A checked-in 3–5 minute runbook ties the user problem, live optimizer, dynamic failure safety, mock execution, and authoritative evidence into one reproducible story. |

## Product boundaries retained

- Monetary values remain integer paise outside the statistical model boundary.
- Actual final fare is unavailable to prediction, optimization, policy,
  personalization, and dynamic decisions. It enters only retrospective
  evaluation and completed-ride settlement.
- All current training and evaluation data is synthetic. No production
  Razorpay, merchant, Uber, Ola, or customer data is claimed.
- Razorpay network mappings are not fabricated without verified Reserve Pay API
  documentation; the complete offline lifecycle uses `MockReserveProvider`.
- Browser code presents results and calls the API. It does not reproduce
  prediction, policy, or optimization formulas.
- The agent layer orchestrates approved deterministic tools and has no
  autonomous payment authority.

## Authoritative completion check

Run from the repository root:

```powershell
python -m unittest discover -s tests -v
python -m reserve_pay_optimizer prepare-final-evidence
cd frontend
pnpm test
pnpm build
```

The evidence command writes `demo/evidence/final_evidence.json`. Its provenance
contains the simulator seeds, cohort sizes, model metadata, dataset fingerprint,
and explicit synthetic-data limitations.
