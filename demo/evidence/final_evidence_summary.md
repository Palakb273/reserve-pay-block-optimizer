# Reserve Pay Block Optimizer — Final Evidence

## Dataset Provenance

- Evidence status: **complete**
- Project version: **0.14.0**
- Fresh synthetic records: **20000** (seed `202613`)
- Dataset fingerprint: `4189c9ceb1ca07b92b4b741a07f76ab5062e694dcbe67cd435954d2de1d2725e`
- Evidence fingerprint: `619559aa9352e2f2d9718260eec44b4f7f71d4b99759c18110f7b1ccf091a05c`
- Models were loaded from trusted project artifacts; no retraining was performed.

## Primary Strategy Comparison

| Strategy | Collection success | Under-block rate | Average excess (paise) | Capital efficiency |
|---|---:|---:|---:|---:|
| exact_estimate | 0.345950 | 0.654050 | 428 | 0.984527 |
| fixed_buffer_20 | 0.989750 | 0.010250 | 4792 | 0.855735 |
| optimized_balanced | 0.925400 | 0.074600 | 3035 | 0.903340 |

## Prediction Calibration

- Records: 20000
- Mean pinball loss (paise): 384.606036

| Quantile | Target | Observed | Calibration error | Pinball loss (paise) |
|---|---:|---:|---:|---:|
| Q05 | 0.050000 | 0.058000 | 0.008000 | 185.518260 |
| Q10 | 0.100000 | 0.099150 | -0.000850 | 314.832705 |
| Q25 | 0.250000 | 0.214700 | -0.035300 | 578.130650 |
| Q50 | 0.500000 | 0.400550 | -0.099450 | 763.641525 |
| Q75 | 0.750000 | 0.603800 | -0.146200 | 662.350500 |
| Q90 | 0.900000 | 0.761900 | -0.138100 | 418.348880 |
| Q93 | 0.930000 | 0.800450 | -0.129550 | 340.603020 |
| Q95 | 0.950000 | 0.832550 | -0.117450 | 278.211600 |
| Q97 | 0.970000 | 0.871750 | -0.098250 | 202.319802 |
| Q99 | 0.990000 | 0.926000 | -0.064000 | 102.103421 |

- High-quantile under-coverage is visible and is not described as production calibration.

## Personalization

- Records: 20000; minimum eligible history: 3 completed rides.
- Base mean pinball loss: 419.460793 paise; personalized: 384.606036 paise.
- Base Q97/Q99 coverage: 0.825500 / 0.894800; personalized: 0.871750 / 0.926000.
- Base fallback: 13209 (0.660450); personalized: 6791 (0.339550).

## Merchant Risk Profiles

| Profile | Target | Realized success | Under-block | Average block (paise) | Average excess (paise) | Capital efficiency |
|---|---:|---:|---:|---:|---:|---:|
| aggressive | 0.930000 | 0.925400 | 0.074600 | 31400 | 3035 | 0.903343 |
| balanced | 0.970000 | 0.925400 | 0.074600 | 31400 | 3035 | 0.903340 |
| conservative | 0.990000 | 0.926000 | 0.074000 | 31444 | 3078 | 0.902117 |
- All three profiles selected the same block on 19621 records (0.981050). This is a factual diagnostic, not hidden.

## Dynamic Re-Optimization

- Static success: 0.919000; dynamic success: 0.969200.
- Average initial/final block (paise): 31298 / 31823.

| Outcome category | Count | Rate |
|---|---:|---:|
| static_failed_dynamic_succeeded | 251 | 0.050200 |
| both_succeeded | 4595 | 0.919000 |
| both_failed | 154 | 0.030800 |
| static_succeeded_dynamic_failed | 0 | 0.000000 |
| dynamic_no_increase_required | 2285 | 0.457000 |

## India-Specific Results

| City | Records | Optimized success | Average excess (paise) |
|---|---:|---:|---:|
| bengaluru | 2852 | 0.923212 | 4407 |
| chennai | 2898 | 0.936163 | 3042 |
| delhi | 2881 | 0.917043 | 2777 |
| hyderabad | 2838 | 0.926709 | 2875 |
| kolkata | 2871 | 0.933821 | 2685 |
| mumbai | 2866 | 0.918702 | 3004 |
| pune | 2794 | 0.921976 | 2449 |

## Agent Validation

- Agent runs: 500; mismatches: 0; equivalence: 1.000000; average tool calls: 4.0.
- Observed execution time (ms): average 18.064; median 17.86; p95 20.12.

## Explainability Validation

- Explanation records: 500; numeric mismatches: 0; privacy violations: 0; template fallbacks: 0; generated-text failures: 0.

## Mock Reserve Pay Validation

- Mock Reserve Pay scenarios: 15/15 passed.
- `create_success`: PASS — expected authorized.
- `idempotent_create`: PASS — expected same result; no duplicate block.
- `increase_success`: PASS — expected authorized amount increased exactly once.
- `failed_increase_no_mutation`: PASS — expected authorized amount unchanged.
- `transient_retry_success`: PASS — expected authorized after retry with the same idempotency key.
- `permanent_failure_surfaced`: PASS — expected rejected once without retry.
- `idempotency_conflict`: PASS — expected conflict rejected without execution.
- `partial_debit`: PASS — expected partially_debited with remaining authorization.
- `full_settlement`: PASS — expected actual fare fully debited within authorization.
- `release_remaining_amount`: PASS — expected unused remaining authorization released.
- `final_status_and_accounting`: PASS — expected released and accounting invariant balanced.
- `under_block_shortfall`: PASS — expected explicit shortfall with no over-debit.
- `dynamic_additional_authorization_success`: PASS — expected provider success confirms dynamic target.
- `dynamic_additional_authorization_failure_no_mutation`: PASS — expected failed provider execution preserves authorized session state.
- `stale_success_reconciliation_visible`: PASS — expected reconciliation_required without latest-session mutation.

## Limitations

- All evaluated rides are generated by the deterministic synthetic simulator; no production merchant, Razorpay, Uber, Ola, or customer data is used.
- Observed calibration and collection success are empirical estimates, not guarantees.
- Q97 and Q99 under-coverage on this fresh synthetic cohort is material; production use requires recalibration and external validation.
- Dynamic evaluation assumes simulated additional authorizations succeed; the separate mock lifecycle validates execution failure behavior offline.
- Risk-profile recommendations frequently collapse to the same candidate because the objective optimum can satisfy multiple policy floors.
- Agent timing is observational and excluded from the canonical evidence fingerprint.
- The Razorpay network mapping remains intentionally unimplemented without verified Reserve Pay API documentation.
- Merchant-history personalization and persistent production storage are unavailable.
