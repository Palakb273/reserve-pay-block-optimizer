# Reserve Pay Block Optimizer

This Python 3.11+ and React/TypeScript project defines, simulates, predicts, optimizes, dynamically revises, explains, executes, and demonstrates reserve blocks for India-first mobility payments. Phase 11 adds a polished three-screen decision dashboard over the unchanged Python financial engine.

## Problem

Ride-hailing platforms know an estimated fare before a ride, but the final fare can change with route, duration, traffic, surge, and other ride conditions. Blocking exactly the estimate may under-block. Adding a large arbitrary buffer may unnecessarily lock customer funds.

The eventual product will seek the smallest reasonable block that maintains the merchant's desired collection probability. That is a reserve optimization problem, not merely fare prediction.

## Phase 1 domain foundation

The decision-time `RideTransactionContext` contains transaction/customer IDs, exact estimated fare in integer paise, one of seven supported Indian cities, distance, estimated duration, surge, and a timezone-aware timestamp. It supports Delhi, Mumbai, Bengaluru, Hyderabad, Pune, Chennai, and Kolkata. City is contextual input only; no city-specific variance rule exists.

The post-ride `RideTransactionOutcome` separately contains `actual_amount`. A reserve strategy receives only `RideTransactionContext`; it cannot receive the outcome:

```text
RideTransactionContext -> ReserveStrategy -> ReserveDecision

After completion only:
RideTransactionContext + ReserveDecision + RideTransactionOutcome
                                               |
                                               v
                                          Evaluation
```

The JSON contract likewise keeps `transaction` and `outcome` in different objects. Supplying `actual_amount_paise` inside a transaction is rejected as an unknown decision-time field. This prevents future-data leakage.

## Phase 2 baselines

### Exact Estimate

```text
block_paise = estimated_amount_paise
```

Advantages:

- blocks no extra capital beyond the estimate;
- simple and deterministic.

Disadvantages:

- fails collection whenever the final amount exceeds the estimate.

### Fixed Buffer

The default buffer is 20%, but `FixedBufferStrategy` accepts another non-negative integer or `Decimal` percentage.

```text
unrounded_block = estimated_amount_paise * (1 + buffer_percentage / 100)
block_paise = ceiling(unrounded_block)
```

The calculation uses `Decimal`, never binary floating-point money. Fractional paise round upward so truncation cannot make the configured baseline smaller. For example, 1 paise with a 20% buffer produces 1.2 paise and therefore blocks 2 paise.

Advantages:

- reduces some under-blocking compared with the exact estimate.

Disadvantages:

- may lock additional customer funds that are not collected;
- still fails when the final amount exceeds the fixed buffer.

Neither baseline is assumed to be universally optimal.

## Phase 3 - Transaction simulator

Real production ride/payment data is unavailable during development, so Phase 3 generates reproducible synthetic `RideTransactionContext` and `RideTransactionOutcome` pairs. The generator uses the existing domain models and exports the existing Phase 2 evaluation-record shape.

> City and fare behaviour are synthetic modeling assumptions for demonstration and experimentation. They are not claimed to be production Razorpay, Uber, Ola, or city-level statistics.

The random seed controls all stochastic choices. The same configuration and seed produce the same typed records and byte-equivalent JSON content; a different seed changes the dataset. Transaction IDs remain deterministic (`SIM-000001`, `SIM-000002`, ...), while customer IDs are sampled from a configurable pool so repeat customers occur without introducing customer personalization.

### Generated decision-time features

- supported Indian city;
- timezone-aware India timestamp and derived day of week;
- distance sampled around the city's synthetic typical distance;
- estimated duration derived from distance, synthetic average speed, time band, weekday/weekend context, and small planning variation;
- bounded surge, with most rides at `1.00` and elevated surge less frequently;
- estimated fare stored as exact integer paise.

The simulator generates hidden route, traffic, and pricing-noise values only while realizing the outcome. They are never stored in `RideTransactionContext` or passed to a reserve strategy.

### Synthetic fare formula

The shared default fare assumptions are:

```text
base fare                    = 4,500 paise
distance rate                = 1,400 paise/km
duration rate                = 220 paise/minute
distance range               = 0.8 to 40.0 km
maximum surge                = 2.00

estimated_fare = ceiling(
    (base_fare
     + distance * distance_rate
     + estimated_duration * duration_rate)
    * surge_multiplier
)
```

This is an interpretable synthetic formula, not a reconstruction of any ride-hailing company's proprietary pricing.

### Actual-fare uncertainty

For each outcome, the generator samples bounded, city-profile-scaled route and traffic changes. Peak time bands increase the traffic uncertainty scale. It then computes:

```text
actual_distance = clamp(distance * (1 + route_change))

actual_duration = round(
    estimated_duration
    * (1 + traffic_change + 0.35 * route_change)
)

actual_fare = round_half_up(
    synthetic_fare(actual_distance, actual_duration, surge)
    * (1 + bounded_pricing_noise)
)
```

This relationship allows actual fares below, near, or above the estimate. Actual distance, actual duration, and pricing noise are latent outcome-generation details and are not exported as decision-time features.

### Synthetic city profiles

All values in this table are simulation assumptions:

| City | Typical distance km | Spread km | Avg speed km/h | Traffic variation | Route variation | Base surge probability |
|---|---:|---:|---:|---:|---:|---:|
| Delhi | 10.0 | 6.0 | 25.0 | 0.09 | 0.045 | 0.09 |
| Mumbai | 9.0 | 5.0 | 22.0 | 0.13 | 0.050 | 0.12 |
| Bengaluru | 11.0 | 7.0 | 20.0 | 0.16 | 0.060 | 0.14 |
| Hyderabad | 10.0 | 6.0 | 27.0 | 0.10 | 0.045 | 0.10 |
| Pune | 8.0 | 5.0 | 25.0 | 0.11 | 0.050 | 0.10 |
| Chennai | 10.0 | 6.0 | 26.0 | 0.10 | 0.045 | 0.09 |
| Kolkata | 8.0 | 5.0 | 23.0 | 0.12 | 0.050 | 0.10 |

Time bands use synthetic traffic/uncertainty/surge-probability multipliers: low demand (`0.85/0.80/0.50`), normal daytime (`1.00/1.00/1.00`), morning peak (`1.30/1.30/1.80`), and evening peak (`1.40/1.40/2.00`). Surge probability is capped at `0.45` and surge itself at `2.00` by default.

### Simulator diagnostics

Every exported dataset includes descriptive diagnostics in `metadata.diagnostics`:

- transaction and unique-customer counts;
- counts per city;
- average estimated and actual amounts;
- rates of actual fare above, below, equal to, and within 2% of estimate;
- average absolute estimate/actual difference;
- surge frequency.

These are dataset-quality diagnostics, not final evidence KPIs or production statistics.

## Phase 4 - Prediction engine

A single point prediction cannot say whether an amount represents typical fare, 90% empirical coverage, or 97% empirical coverage. Phase 4 therefore trains one gradient-boosted quantile regressor for each of:

```text
Q05 Q10 Q25 Q50 Q75 Q90 Q93 Q95 Q97 Q99
```

Each model learns the conditional `fare_ratio = actual_amount_paise / estimated_amount_paise`. At inference, that predicted ratio is multiplied by the decision-time estimate and rounded upward to the next integer paise. Floating point is confined to the ML boundary; public currency remains validated `Money`/integer paise.

> The model predicts the conditional distribution of final transaction amount. It does not decide how much money to reserve.

> All training data in the current project is synthetic and generated by the Phase 3 simulator. The artifact is not trained on Razorpay, Uber, Ola, merchant, or production data.

### Auditable feature schema

Training, validation, test, and inference use the same `PredictionFeatureExtractor`. Its fixed feature schema is:

- `estimated_amount_paise`, `distance_km`, `estimated_duration_minutes`, and `surge_multiplier`;
- cyclical `hour_sin`/`hour_cos`, zero-based `day_of_week`, and `is_weekend`, all derived from the transaction timestamp in IST;
- one fixed one-hot feature for each of Delhi, Mumbai, Bengaluru, Hyderabad, Pune, Chennai, and Kolkata.

The extractor cannot accept an outcome. It explicitly prohibits transaction/customer IDs, actual amount, completion timestamp, route/traffic/pricing-noise simulator latents, actual distance, and actual duration. IDs are retained only for joins and tracing. Customer personalization remains a later phase.

### Split, calibration, and baseline

Records are canonicalized by transaction ID and shuffled with the configured seed into 70% training, 15% validation, and 15% untouched test partitions. The current artifact uses seed 42 and the checked-in 10,000-record synthetic dataset: 7,000 train, 1,500 validation, and 1,500 test records.

Evaluation reports, for every quantile, empirical coverage, signed/absolute calibration error, and pinball loss. It also reports Q50 MAE, Q05–Q95 interval coverage/width, per-city Q90/Q95/Q97/Q99 coverage, and raw quantile-crossing frequency. Coverage is an empirical diagnostic, not a guarantee.

Independent quantile models can cross. Evaluation measures their raw crossings. Published predictions use a deterministic cumulative-maximum repair so `Q05 <= ... <= Q99`.

The Global Quantile Baseline learns unconditional fare-ratio quantiles from the training set and applies the same ratios to every ride. It is a prediction baseline, separate from—and does not modify—the Exact Estimate and Fixed 20% Buffer reserve strategies.

### Persistence and reproducibility

`artifacts/prediction/fare_distribution_v1/` contains ten joblib models plus `metadata.json`, `feature_schema.json`, `baseline_ratios.json`, and `evaluation_summary.json`. Metadata records the feature/quantile/model configuration, split counts, seed, target, paise rounding, SHA-256 fingerprint of canonical dataset contents/configuration, and library versions.

Joblib uses pickle semantics. Load model artifacts only from trusted project sources; never load arbitrary or user-uploaded joblib/pickle files.

Artifact loading validates the recorded scikit-learn and joblib versions before deserializing any model. A mismatch fails clearly and requires installing the recorded versions or retraining; it is never silently ignored.

## Phase 5 - Reserve optimization engine

Phase 4 answers “what conditional final-fare distribution is predicted?” Phase 5 answers “which candidate block minimizes the configured cost of under-blocking, expected unused funds, and customer-visible extra blocking?”

```text
Score(block)
= lambda_under * estimated_under_block_probability(block)
+ lambda_excess * expected_excess_block(block) / estimated_amount
+ lambda_friction * max(block - estimated_amount, 0) / estimated_amount
```

The default low-level configuration is:

```text
lambda_under          = 4.0
lambda_excess         = 1.0
lambda_friction       = 0.5
candidate_step_paise  = 100
```

These values deliberately make under-blocking substantially more costly than a modest excess block while retaining meaningful excess and friction penalties. They were selected as simple product-principle parameters, not tuned against the held-out test set.

> The objective weights are project policy parameters for experimentation. They are not Razorpay-defined production risk weights.

### CDF and modeled support

`QuantileDistribution` estimates `F(block)` using piecewise-linear interpolation between distinct published quantile amounts. Equal neighboring amounts are grouped safely at the highest corresponding probability. Values below Q05 receive conservative zero modeled coverage. Values at or above Q99 remain capped at `0.99`: Q99 is not a maximum fare and never becomes 100% certainty. No unsupported upper-tail extrapolation is performed.

### Expected excess

Expected unused funds are not approximated by `block - Q50`. The implementation analytically evaluates:

```text
E[(block - Y)+] = integral from 0 to F(block) of (block - Q(u)) du
```

over each linear quantile-function segment. For this integration only, Q0 is approximated by linearly extending the Q05–Q10 segment downward and clamping the amount to at least one paise. This is a numerical lower-tail approximation, not a learned Q0. The public expected-excess `Money` rounds upward to integer paise.

Expected excess and friction are distinct. Expected excess describes model-weighted unused funds across possible final fares. Friction describes the full visible block above the original estimate, whether or not that increment is later collected.

### Candidate search and selection

Candidates include the estimate, every published quantile amount, and 100-paise steps by default through the range anchored by `min(estimate, Q50)` and `max(estimate, Q99)`. Values are positive, sorted, and deduplicated. Every candidate is scored with exact `Decimal` arithmetic. The minimum score wins; equal scores choose the smaller block.

`OptimizationResult` contains the recommended `Money`, estimated collection/under-block probabilities, expected excess, normalized ratios, score components, candidate count, configuration, and model version. It contains no outcome. `OptimizedReserveStrategy` converts this rich result to the existing minimal `ReserveDecision`, so Exact Estimate, Fixed 20%, and Optimized Reserve use the same retrospective evaluation service and actual outcomes.

> The optimizer uses only information available at reserve-decision time. Actual final amount is used only for retrospective evaluation.

Evaluation must use held-out or fresh data without retraining. The reproducible Phase 5 demonstration uses 10,000 newly simulated records with seed `202605`; the Phase 4 artifact remains unchanged.

## Phase 6 — Merchant Risk Profiles

Different merchants can have different tolerance for failed collections versus excess customer funds being temporarily blocked. Phase 5 minimizes the objective across every candidate. Phase 6 first filters those exact same candidates by a merchant policy and then minimizes the unchanged Phase 5 objective within the feasible set:

```text
feasible(block, policy)
    = estimated_collection_probability(block) >= policy.target

selected block
    = argmin Score(block), over feasible candidates only
```

The built-in, centralized policies are:

| Profile | Target estimated collection probability |
|---|---:|
| Aggressive | 0.93 |
| Balanced | 0.97 |
| Conservative | 0.99 |

Balanced is the default policy when application code explicitly requests `ReserveRiskPolicy.default()`. The `optimize-block` CLI keeps Phase 5 backward compatibility: omitting `--risk-profile` remains unconstrained; passing a profile enables Phase 6 policy enforcement.

These names describe merchant tolerance for modeled under-block risk. “Conservative” does not guarantee collection, and “Aggressive” does not intentionally under-block. Each target is an estimated probability from the synthetic-data-trained conditional model, bounded by Q99 support. The target is not a guarantee, service-level agreement, Razorpay policy, or production recommendation.

> Risk profile targets are modeled collection-probability thresholds, not guarantees of successful collection.

> The 99% / 97% / 93% values are hackathon/product policy settings from the product design and are not Razorpay production defaults.

`PolicyConstrainedOptimizer` reuses `ReserveBlockOptimizer.score_candidates()` and its candidate generation, CDF, expected-excess calculation, lambdas, score components, and smaller-block tie-break. It does not replace the objective, alter the distribution, or use the final outcome. If a requested target exceeds modeled support or no generated candidate reaches it, a structured `PolicyTargetNotReachable` error is returned rather than silently lowering the target or claiming unsupported certainty.

`PolicyOptimizationResult` records the selected profile, target, `policy_satisfied`, feasible-candidate count, estimated probability, expected excess, and full Phase 5 objective result. Policy satisfaction means the model estimate met the configured threshold at decision time. It is deliberately distinct from retrospective realized collection success, which can be computed only after the actual fare exists.

All three policies use one `OptimizedReserveStrategy` implementation with profile-specific identifiers: `optimized_aggressive`, `optimized_balanced`, and `optimized_conservative`. They enter the same Phase 2 comparison service as Exact Estimate and Fixed Buffer 20%, so every strategy receives identical transactions and outcomes. The policy evaluation reports target versus average estimated probability, satisfaction rate, average block, expected excess, objective score, realized success, calibration difference, and per-city realized success/excess diagnostics.

> Merchant risk profiles are project-level policy abstractions for experimentation. They are not Razorpay-defined production policies.

> The optimizer and policy layer use only reserve-decision-time information. Actual final amount is used only for retrospective evaluation.

## Phase 7 — Customer-Level Personalization

The original predictor uses the current ride context. Phase 7 additionally summarizes historical completed rides belonging to that customer, but only when each historical outcome was already available before the current decision:

```text
eligible history record <=>
    same customer
    different transaction
    completed_at < current transaction timestamp
```

Records are ordered by transaction start time. A completion-time priority queue releases outcomes into per-customer history only when the strict rule above becomes true. Consequently, an overlapping ride that started earlier but has not completed cannot leak into another decision. After feature construction, records are split chronologically: first 70% train, next 15% validation, final 15% untouched test. Personalized records are never shuffled.

### Historical feature schema

For eligible prior rides, let `r_i = actual_amount_i / estimated_amount_i` and `n` be completed history count. The interpretable behavioral features are:

```text
customer_history_count = n

customer_mean_fare_ratio = sum(r_i) / n

customer_fare_ratio_stddev = sqrt(
    sum((r_i - mean_fare_ratio)^2) / n
)

customer_overrun_rate = count(r_i > 1) / n

customer_mean_positive_overrun_ratio =
    mean(r_i - 1 for r_i > 1)
```

The standard deviation uses the deterministic population definition. One historical ride has standard deviation zero. With no history, structural values are count `0`, mean ratio `1`, and other aggregates `0`; these values are never passed to the personalized model because cold start falls back to the base predictor.

`customer_id` and `transaction_id` are lookup/tracing identifiers only. They are prohibited from the ML feature matrix—there is no hashing, one-hot encoding, numeric mapping, or identity memorization. No demographic, sensitive, credit, device, address, or phone attributes exist.

### Cold start and model boundary

The minimum history threshold is three completed rides:

```text
history count 0-2 -> fare_distribution_v1 (base fallback)
history count 3+  -> fare_distribution_personalized_v1
```

Predictions expose `prediction_mode`, history count, and history-as-of time. They never expose historical actual-fare lists or hidden simulator parameters. Both predictors retain the same fare-ratio target, quantile grid, gradient-boosting family, and hyperparameters so evaluation isolates the value of customer history.

The optimizer remains unaware of customer history:

```text
current context + eligible history
              -> personalized distribution
              -> unchanged Phase-5 optimizer
              -> unchanged Phase-6 merchant policy
```

### Opt-in synthetic customer behavior

Default Phase-3 simulation is unchanged. `--personalized-customer-behavior` opts into deterministic hidden customer characteristics derived from SHA-256 of simulation seed and customer ID:

- fare overrun bias sampled from `-0.035` through `0.090`;
- outcome variance multiplier sampled from `0.65` through `1.60`.

The bias modestly shifts realized fare and the variance multiplier scales route, traffic, and pricing uncertainty. They remain stochastic per ride but persistent per synthetic customer. Neither hidden value is stored in `RideTransactionContext`, exported records, history features, or model features. The model can observe behavior only indirectly through prior completed outcomes.

> Current personalization evidence is based entirely on synthetic mobility data. Customer behavior assumptions are not Razorpay, Uber, Ola, or merchant production statistics.

### Evaluation and diagnostics

Evaluation compares the Phase-4 base predictor and Phase-7 predictor on identical chronological test records. It reports pinball loss, mean absolute calibration error, Q50 MAE, Q90/Q95/Q97/Q99 coverage, Q05–Q95 coverage/width, history-depth buckets (`0-2`, `3-5`, `6-10`, `11+`), and observed-history-only diagnostic segments:

- historically stable: at least three rides, standard deviation at most `0.025`, and mean ratio within `0.03` of one;
- historically variable: at least three rides and standard deviation at least `0.05`;
- historically overrun-prone: at least three rides and the documented mean/overrun thresholds.

These labels are evaluation diagnostics, not customer judgments or risk-policy rules. Balanced-policy downstream evaluation reuses the existing objective and retrospective metrics.

The separate trusted artifact is stored under `artifacts/prediction/fare_distribution_personalized_v1/`. It records the chronological split, history schema, minimum threshold, dataset fingerprint, simulation metadata, model configuration, evaluation summary, and exact library versions. Joblib artifacts must be loaded only from trusted project sources.

## Strategy extension boundary

Every strategy implements the same minimal contract:

```python
class ReserveStrategy(Protocol):
    @property
    def strategy_id(self) -> str: ...

    def calculate_block(
        self,
        transaction: RideTransactionContext,
    ) -> ReserveDecision: ...
```

`ReserveDecision` contains only the transaction ID, strategy/version, block amount, and deterministic parameters. Rich mathematical diagnostics remain in the separate `OptimizationResult`; neither object contains outcomes.

`OptimizedReserveStrategy` implements this protocol and enters the same comparison service without changing Phase-2 evaluation code.

## Evaluation formulas

For a completed transaction:

```text
collection_success = block_amount >= actual_amount
excess_block        = max(block_amount - actual_amount, 0)
under_block         = max(actual_amount - block_amount, 0)
is_under_blocked    = under_block > 0
excess_block_ratio  = excess_block / block_amount
```

Aggregate metrics include transaction/success/under-block counts, collection success rate, under-block rate, average excess and under-block amounts, total blocked and actual amounts, capital efficiency, and average excess-block ratio.

Rates are ratios from `0.000000` to `1.000000`, not percentages from 0 to 100. They are stored as `Decimal`, rounded half-up to six decimal places, and serialized as fixed-width JSON strings to avoid binary floating-point ambiguity. Average monetary amounts are rounded half-up to the nearest paise.

### Project-defined capital efficiency

```text
capital_efficiency =
    sum(min(block_amount, actual_amount)) / sum(block_amount)
```

This bounded 0-to-1 ratio describes how much reserved capital corresponded to collectible transaction value. It is a project-defined metric, not a universal or Razorpay-defined KPI. An under-blocked strategy can fully utilize a small block and appear capital-efficient while still collecting unsuccessfully, so this metric must always be shown with collection success and under-block rate.

### Customer-friction proxy

```text
excess_block_ratio = excess_block / block_amount
average_excess_block_ratio = mean(transaction excess_block_ratio)
```

Phase 2 uses excess-block ratio as a transparent customer-friction proxy because unused blocks temporarily lock more customer funds. It is not a behavioural or psychological friction prediction.

## Architecture

```text
src/reserve_pay_optimizer/
  config.py                         Stable domain/baseline constants
  domain/
    errors.py                       Structured validation issues
    money.py                        Exact INR/paise value object
    mobility.py                     Decision context and separate outcome
    reserve.py                      ReserveDecision
    evaluation.py                   TransactionEvaluation and StrategyMetrics
    types.py                        Currency, domain, and city vocabularies
  strategies/
    base.py                         ReserveStrategy protocol
    exact_estimate.py               Exact-estimate baseline
    fixed_buffer.py                 Configurable fixed-buffer baseline
    optimized.py                    Predictor-to-optimizer strategy adapter
  services/
    mobility_validation.py          Phase 1 validation/normalization
    evaluation.py                   Transaction and aggregate evaluation
    comparison.py                   Fair multi-strategy comparison
    evaluation_input.py             Separated JSON dataset parser
    optimizer_evaluation.py         Shared three-strategy comparison plus decision diagnostics
    policy_evaluation.py            Shared baseline/profile evaluation and city diagnostics
  simulation/
    config.py                       Validated simulator/fare configuration
    profiles.py                     Synthetic city and time-band assumptions
    generator.py                    Seeded context/outcome generation
    models.py                       Records, datasets, and diagnostics model
    diagnostics.py                  Dataset quality summary
  prediction/
    config.py                       Quantiles, split, seed, and tree settings
    features.py                     Leakage-safe decision-time features
    dataset.py                      Supervised join, split, and SHA-256 fingerprint
    distribution.py                 Typed Money quantiles and monotonic repair
    baseline.py                     Global training-ratio quantile baseline
    model.py                        Conditional gradient-boosted quantile models
    evaluation.py                   Calibration, loss, interval, city, crossing metrics
    training.py                     Deterministic training orchestration
    persistence.py                  Trusted joblib artifact save/load
  optimization/
    config.py                       Validated objective weights and candidate step
    distribution.py                 CDF interpolation and analytical excess integration
    candidates.py                   Bounded deterministic candidate generation
    objective.py                    Dimensionless weighted candidate scoring
    models.py                       Score components and OptimizationResult
    optimizer.py                    Minimum-score search and tie-breaking
  policy/
    risk.py                         Immutable profiles and centralized targets
    errors.py                       Structured infeasible-policy error
    models.py                       Policy-aware optimization result
    optimizer.py                    Feasible-candidate constrained optimization
  personalization/
    config.py                       History threshold, model version, diagnostic thresholds
    models.py                       Typed history and personalized prediction result
    history.py                      Strict completion-time history provider and formulas
    features.py                     Context plus behavioral feature extraction
    dataset.py                      Completion queue, chronological split, fingerprint
    model.py                        Personalized quantile gradient-boosting models
    predictor.py                    Automatic cold-start/personalized routing
    evaluation.py                   Base comparison, cohorts, segments, reserve outcomes
    training.py                     Chronological training orchestration
    persistence.py                  Trusted personalized artifact save/load
  cli.py                            CLI adapter
artifacts/prediction/               Reproducible Phase 4 trained artifact
examples/
  valid_hyderabad_ride.json
  invalid_ride.json
  baseline_evaluation.json          Deterministic Phase 2 fixture
tests/                              Phase 1-through-7 tests
```

Domain and service code remains independent of HTTP and Razorpay SDK objects. The only direct runtime dependency is scikit-learn.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

## CLI

The Phase 1 validation command remains available:

```powershell
python -m reserve_pay_optimizer validate-mobility --file examples/valid_hyderabad_ride.json
```

Compare both Phase 2 baselines on the same completed records:

```powershell
python -m reserve_pay_optimizer evaluate-baselines --file examples/baseline_evaluation.json
```

Generate 10,000 records to a file and print a compact diagnostic summary:

```powershell
python -m reserve_pay_optimizer simulate-mobility `
  --count 10000 `
  --seed 42 `
  --customer-pool-size 1000 `
  --output simulated_transactions.json
```

Omit `--output` to emit the complete dataset to standard output. The default count is 100, so the CLI does not print 10,000 records unless explicitly requested.

Evaluate the generated file without conversion:

```powershell
python -m reserve_pay_optimizer evaluate-baselines `
  --file simulated_transactions.json
```

Optional `--start-datetime` and `--end-datetime` values must be timezone-aware RFC 3339 timestamps. Simulator defaults cover calendar year 2026 in India Standard Time.

Train the Phase 4 predictor:

```powershell
python -m reserve_pay_optimizer train-predictor `
  --file simulated_transactions.json `
  --seed 42 `
  --output artifacts/prediction/fare_distribution_v1
```

Evaluate the untouched test partition (a different input fingerprint is treated as an external evaluation dataset):

```powershell
python -m reserve_pay_optimizer evaluate-predictor `
  --file simulated_transactions.json `
  --model artifacts/prediction/fare_distribution_v1
```

Predict one conditional distribution:

```powershell
python -m reserve_pay_optimizer predict-distribution `
  --model artifacts/prediction/fare_distribution_v1 `
  --file examples/valid_hyderabad_ride.json
```

The response contains integer-paise quantiles and no recommended block amount. `FareDistributionPrediction.amount_for_quantile(Decimal("0.97"))` provides an exact configured-quantile query; unmodeled or out-of-range probabilities raise a clear `KeyError`. No probability is extrapolated beyond Q05–Q99.

Optimize one transaction, optionally showing the five best candidates:

```powershell
python -m reserve_pay_optimizer optimize-block `
  --model artifacts/prediction/fare_distribution_v1 `
  --file examples/valid_hyderabad_ride.json `
  --verbose
```

Apply one Phase 6 merchant profile to the same workflow:

```powershell
python -m reserve_pay_optimizer optimize-block `
  --model artifacts/prediction/fare_distribution_v1 `
  --file examples/valid_hyderabad_ride.json `
  --risk-profile balanced `
  --verbose
```

Compare all three profile decisions for one transaction:

```powershell
python -m reserve_pay_optimizer compare-risk-profiles `
  --model artifacts/prediction/fare_distribution_v1 `
  --file examples/valid_hyderabad_ride.json
```

Generate an unseen evaluation dataset and compare all strategies without retraining:

```powershell
python -m reserve_pay_optimizer simulate-mobility `
  --count 10000 `
  --seed 202605 `
  --customer-pool-size 1000 `
  --output evaluation_transactions.json

python -m reserve_pay_optimizer evaluate-optimizer `
  --file evaluation_transactions.json `
  --model artifacts/prediction/fare_distribution_v1
```

Evaluate both baselines and all three policies against the same unseen records:

```powershell
python -m reserve_pay_optimizer evaluate-risk-profiles `
  --file evaluation_transactions.json `
  --model artifacts/prediction/fare_distribution_v1
```

The three low-level lambdas and candidate step accept explicit CLI overrides for Phase 5 and Phase 6 commands. Profiles change feasibility only; all profiles in one comparison use exactly the same supplied objective configuration.

Generate the opt-in personalized training dataset:

```powershell
python -m reserve_pay_optimizer simulate-mobility `
  --count 20000 `
  --seed 202607 `
  --customer-pool-size 1000 `
  --personalized-customer-behavior `
  --output personalized_transactions.json
```

Train the separate Phase 7 artifact:

```powershell
python -m reserve_pay_optimizer train-personalized-predictor `
  --file personalized_transactions.json `
  --seed 42 `
  --base-model artifacts/prediction/fare_distribution_v1 `
  --output artifacts/prediction/fare_distribution_personalized_v1
```

Evaluate the chronological held-out partition:

```powershell
python -m reserve_pay_optimizer evaluate-personalization `
  --file personalized_transactions.json `
  --model artifacts/prediction/fare_distribution_personalized_v1 `
  --base-model artifacts/prediction/fare_distribution_v1
```

Personalized inference and optimization require an evaluation-record-shaped history file:

```powershell
python -m reserve_pay_optimizer predict-personalized-distribution `
  --model artifacts/prediction/fare_distribution_personalized_v1 `
  --base-model artifacts/prediction/fare_distribution_v1 `
  --history examples/personalization_stable_history.json `
  --file examples/personalization_current_ride.json

python -m reserve_pay_optimizer optimize-personalized-block `
  --model artifacts/prediction/fare_distribution_personalized_v1 `
  --base-model artifacts/prediction/fare_distribution_v1 `
  --history examples/personalization_stable_history.json `
  --file examples/personalization_current_ride.json `
  --risk-profile balanced
```

Run the calculated same-ride demonstration:

```powershell
python -m reserve_pay_optimizer compare-customer-personalization `
  --model artifacts/prediction/fare_distribution_personalized_v1 `
  --base-model artifacts/prediction/fare_distribution_v1 `
  --scenario examples/personalization_comparison.json `
  --risk-profile balanced
```

### Small generated record

For `--count 2 --seed 7`, the first record is:

```json
{
  "transaction": {
    "transaction_id": "SIM-000001",
    "customer_id": "C0003",
    "estimated_amount_paise": 26840,
    "city": "bengaluru",
    "distance_km": 11.4,
    "estimated_duration_minutes": 29,
    "surge_multiplier": 1.0,
    "timestamp": "2026-02-28T14:00:58+05:30"
  },
  "outcome": {
    "transaction_id": "SIM-000001",
    "actual_amount_paise": 28981,
    "completed_at": "2026-02-28T14:33:58+05:30"
  }
}
```

### Evaluation input contract

```json
{
  "records": [
    {
      "transaction": {
        "transaction_id": "TXN-001",
        "customer_id": "C001",
        "estimated_amount_paise": 65000,
        "city": "hyderabad",
        "distance_km": 18.4,
        "estimated_duration_minutes": 42,
        "surge_multiplier": 1.18,
        "timestamp": "2026-08-23T18:30:00+05:30"
      },
      "outcome": {
        "transaction_id": "TXN-001",
        "actual_amount_paise": 71000,
        "completed_at": "2026-08-23T19:20:00+05:30"
      }
    }
  ]
}
```

Duplicate transaction IDs, duplicate outcome IDs, missing outcomes, unexpected outcomes, and mismatched IDs are rejected with structured errors.

### Calculated sample output

The checked-in three-transaction fixture produces these calculated metrics:

```json
{
  "comparison_status": "complete",
  "currency": "INR",
  "domain": "mobility",
  "strategies": {
    "exact_estimate": {
      "collection_success_rate": "0.333333",
      "under_block_rate": "0.666667",
      "average_excess_block_paise": 1000,
      "average_under_block_paise": 6667,
      "capital_efficiency": "0.983333",
      "average_excess_block_ratio": "0.015385"
    },
    "fixed_buffer_20": {
      "collection_success_rate": "0.666667",
      "under_block_rate": "0.333333",
      "average_excess_block_paise": 7667,
      "average_under_block_paise": 1333,
      "capital_efficiency": "0.893519",
      "average_excess_block_ratio": "0.098291"
    }
  }
}
```

The same three transaction IDs and total actual amount are used for each strategy.

## Phase 8 — Dynamic Re-Optimization

The reserve recommendation is no longer fixed for the whole ride. When a ride platform supplies legitimate revised projections, Phase 8 follows the existing decision path again:

```text
rebuild decision-time context
        ↓
base/personalized distribution prediction
        ↓
unchanged Phase-5 objective and Phase-6 policy constraint
        ↓
new recommended target block
        ↓
compare with currently authorized block
```

The dynamic service accepts only an initial `RideTransactionContext`, a frozen `CustomerHistoryFeatures` snapshot, a fixed session risk profile, and typed `RideContextUpdate` events. It never receives the ride outcome. Mutable update fields are revised estimate, projected total distance, projected total duration, and surge multiplier. Transaction ID, customer ID, city, ride-start timestamp, domain, and INR currency stay immutable. The original context timestamp remains the ride start; every event has a separate `observed_at` timestamp.

Three monetary values have deliberately different meanings:

```text
current_authorized_block
    application state already considered authorized

recommended_target_block
    total reserve currently recommended by prediction + optimization

additional_block_required
    max(recommended_target_block - current_authorized_block, 0)
```

Re-optimization emits a recommendation and does not mutate `current_authorized_block`. Only `confirm_block_authorized` can commit the exact requested total to session state. This confirmation is application/domain state only: it does not mean a bank, UPI provider, Razorpay, or any payment network approved funds. A decreasing recommendation produces zero additional reserve; Phase 8 never releases an active block.

### Ordering, versions, idempotency, and audit

- Sessions start at version 0; every accepted context update increments the version.
- Sequence numbers must be contiguous (`1, 2, 3, ...`) and event timestamps must increase strictly after ride start.
- Confirmations must reference the latest decision at the current session version and authorize exactly the requested total. Stale or mismatched confirmations are rejected.
- Replaying the same `event_id` with the identical payload returns the existing decision without another mutation. Reusing it with a different payload raises a structured conflict.
- The immutable audit trail records session start, context updates, re-optimization decisions, and simulated/application confirmations. It contains no final outcome or simulator latent state.

Customer history is calculated as of ride start and frozen for that session. Later ride completions, the active ride's partial behavior, and future outcomes cannot change its personalization features. Cold-start sessions continue to use the Phase-7 base-model fallback; eligible sessions continue to use the personalized model. The merchant risk profile is fixed for the session.

### Dynamic synthetic data

`simulate-dynamic-mobility` first calls the unchanged Phase-3/7 simulator and then deterministically creates zero to three observable projected updates per ride. Revised synthetic estimates use the documented synthetic fare formula and projected distance/duration/surge values that partially converge toward the completed synthetic trajectory. Hidden route/traffic noise and hidden customer profiles are never exported. Existing `simulate-mobility` output remains unchanged.

Generate a reproducible dynamic dataset:

```powershell
python -m reserve_pay_optimizer simulate-dynamic-mobility `
  --count 10000 `
  --seed 202608 `
  --customer-pool-size 1000 `
  --personalized `
  --output dynamic_transactions.json
```

Run the checked-in timeline. `--auto-confirm` is a demo convenience that assumes each recommended increase was successfully authorized in application state; it performs no external call:

```powershell
python -m reserve_pay_optimizer run-dynamic-ride `
  --model artifacts/prediction/fare_distribution_personalized_v1 `
  --base-model artifacts/prediction/fare_distribution_v1 `
  --scenario examples/dynamic_reoptimization.json `
  --risk-profile balanced `
  --auto-confirm `
  --verbose
```

Omit `--auto-confirm` to produce every recommendation while leaving the authorized block at its initial value.

The deterministic demo currently calculates this timeline from the checked-in models:

```text
18:30  estimate 65,000 paise; Q97 73,465; Q99 75,196
       initial target/authorized block 75,196

18:42  traffic update; estimate 71,000; Q97 81,314; Q99 82,469
       target 82,469; additional 7,273; simulated confirmation → 82,469

18:55  route update; estimate 78,000; Q97 90,854; Q99 98,669
       target 90,854; additional 8,385; simulated confirmation → 90,854

19:42  final synthetic outcome 79,500 (retrospective evaluation only)
       static initial block fails; dynamically confirmed final block succeeds
```

Compare static initial blocking with dynamic blocking on exactly the same rides and outcomes:

```powershell
python -m reserve_pay_optimizer evaluate-dynamic-reoptimization `
  --file dynamic_transactions.json `
  --model artifacts/prediction/fare_distribution_personalized_v1 `
  --base-model artifacts/prediction/fare_distribution_v1 `
  --risk-profile balanced
```

The report includes realized success/under-block metrics, average initial/final block, additional-block metrics, trigger rates, re-optimization counts, final excess, under-block amount, and capital efficiency. It always states this evaluation assumption explicitly:

> Dynamic evaluation assumes recommended additional block requests succeed. No real Razorpay authorization is performed.

## Phase 9 — Explainable AI

```text
The ML model predicts.
The optimizer decides.
The explanation layer communicates why.
```

The authoritative `DecisionExplanation` is built only after prediction, policy-constrained optimization, or dynamic re-optimization has finished. It contains the exact selected block, Q50/Q90/Q95/Q97/Q99, modeled coverage, merchant policy threshold, expected excess, friction, objective components, up to five best candidates, prediction mode, model version, and eligible aggregated customer history. Dynamic evidence additionally contains only changed fields, previous/revised quantiles, previous/new target, current authorized block, the exact additional-block formula, and application confirmation status.

> The LLM is never used to calculate or modify the recommended reserve amount.

> Explanations use only facts produced by the deterministic prediction, optimization, policy and dynamic-decision layers.

> Current models and explanation evidence are based on synthetic mobility data.

### Evidence and probability language

Upper quantiles are described as increasingly conservative modeled estimates, never guarantees. A Balanced target of 97% is explained as the minimum feasible modeled coverage. It does not necessarily select Q97: the unchanged Phase-5 objective can select a higher compliant candidate when that candidate has the lowest configured combination of under-block risk, expected unused reserve, and customer friction.

Factors are factual context, not precise causal attribution. The system can state that duration changed from 42 to 55 minutes and Q97 moved from one calculated amount to another. It never fabricates a rupee decomposition claiming traffic, surge, policy, or history each caused an exact amount.

Personalized evidence includes only completed-ride count, mean fare ratio, fare-ratio standard deviation, overrun rate, and mean positive overrun. It excludes customer IDs as model factors, raw ride lists, demographics, hidden simulator profiles, pricing noise, and outcomes. Cold-start explanations explicitly state that the base model was selected because fewer than three eligible rides were available.

### Rendering and optional generated text

`TemplateExplanationRenderer` works deterministically and offline in `concise` and `detailed` modes. The same structured evidence produces identical text and a stable SHA-256 `explanation_id`; a changed financial decision changes that identifier.

The optional `ExplanationTextGenerator` protocol is provider-neutral and has no SDK dependency. It receives only serialized `DecisionExplanation` facts plus guardrails that prohibit recalculation, guarantees, invented attribution, production-policy claims, customer labeling, and false authorization language. Generated JSON must copy transaction ID, selected block, modeled probability, and authorization status exactly. Missing fields, altered numbers, oversized output, invalid JSON, privacy violations, or provider exceptions automatically fall back to the template renderer. Explanation failure cannot alter or invalidate the existing financial result.

Both structured facts and rendered text are returned. Validation metrics report factual counts only: explanations generated, valid structured explanations, numeric consistency, fallbacks, and generated-text failures. There is no synthetic “explainability score.”

Explain one personalized reserve recommendation:

```powershell
python -m reserve_pay_optimizer explain-block `
  --model artifacts/prediction/fare_distribution_personalized_v1 `
  --base-model artifacts/prediction/fare_distribution_v1 `
  --history examples/personalization_stable_history.json `
  --file examples/personalization_current_ride.json `
  --risk-profile balanced `
  --detail detailed
```

Attach an explanation to every dynamic event:

```powershell
python -m reserve_pay_optimizer run-dynamic-ride `
  --model artifacts/prediction/fare_distribution_personalized_v1 `
  --base-model artifacts/prediction/fare_distribution_v1 `
  --scenario examples/dynamic_reoptimization.json `
  --risk-profile balanced `
  --auto-confirm `
  --explain `
  --detail detailed `
  --verbose
```

Without `--auto-confirm`, dynamic text says the additional amount is only recommended. With it, text says confirmation occurred only in simulated/application state and that no payment provider was called.

## Phase 10 — Razorpay Reserve Pay Architecture

```text
Prediction decides the expected distribution.
Optimization chooses the reserve amount.
Policy constrains acceptable risk.
Reserve Pay executes the already-made decision.
```

The `reserve_pay` package contains no prediction, optimization, policy, personalization, or explanation logic. `ReservePayService` receives an exact `Money` amount from an existing `ReserveDecision` or `DynamicReoptimizationDecision` and invokes a `ReservePayProvider`. A provider response can confirm or fail execution, but it cannot change the predicted distribution or calculate a new target.

### Provider contract

Every provider implements normalized operations equivalent to:

```text
createBlock(request)       -> initial authorization
increaseBlock(request)     -> provider-neutral additional authorization intent
debitBlock(request)        -> full or partial collection
releaseBlock(request)      -> release the full unused remainder
getBlockStatus(request)    -> normalized application state
```

The public source requirement lists create, debit, release, and status. `increaseBlock` is the explicit provider-neutral bridge required by Phase 8's additional-block recommendation. It deliberately does not assume whether a future Razorpay mapping amends one authorization or creates a linked authorization.

`ReserveBlock` stores exact integer-paise `Money` for authorized, remaining, debited, and released funds. It enforces:

```text
authorized > 0
debited >= 0
released >= 0
remaining >= 0
debited + released + remaining = authorized
```

The lifecycle is explicit:

```text
PENDING -> AUTHORIZED -> PARTIALLY_DEBITED -> DEBITED
                   |               |
                   +-------------> RELEASED
PENDING -> FAILED
```

Arbitrary transitions are rejected. Phase 10 intentionally supports only releasing the full remaining authorization. This keeps partial debit plus release accounting unambiguous across providers; partial release can be added only when a verified provider contract and a corresponding active-partially-released state are defined.

### Idempotency, retries, and failures

Create, increase, debit, and release require an idempotency key. The in-memory Phase-10 registry is scoped by operation and key. Identical payload replay returns the original result without executing twice; reuse with a changed payload raises `IdempotencyConflictError`. A production persistent registry can replace this store without changing the provider contract.

`RetryConfig` defaults to three attempts and zero delay. Only typed timeout and transient-unavailable failures are retryable. Validation, rejection, insufficient authorization, invalid state, unsupported operation, configuration, and idempotency conflicts are not retried. Every attempt reuses the exact same request and idempotency key. Tests inject a sleeper, so they never wait in real time.

Provider failures are normalized as credential-safe `ReservePayError` subclasses. Audit events record operation type, transaction/block identity, provider, a short SHA-256 fingerprint of the idempotency key, and a safe error code. They never contain provider credentials, authentication headers, raw provider payloads, or secret values.

### MockReserveProvider

`MockReserveProvider` implements the complete offline lifecycle with an in-memory block store, deterministic timestamps, and inspectable IDs such as `mock_blk_000001`. It supports initial create, increases, normalized status, partial and full debit, full-remaining release, idempotent replay, conflicts, and state validation.

Normal mock operation never fails randomly. `MockFailureConfig` can deterministically reject the next create/increase/debit/release, time out the next named operation, or produce a configured number of transient failures. This supports reliable success, failure, and retry demos.

### Dynamic authorization and reconciliation

Phase 8's explicit `confirm_block_authorized(...)` remains the only way to mutate a dynamic session's authorized amount:

```text
dynamic recommendation
        -> provider increase attempt
        -> normalized success
        -> Phase-8 version/stale checks
        -> confirmation
```

A provider failure returns the higher recommended target and failed execution evidence while preserving the prior authorized amount. Payment failure does not recalculate the target. If a provider success arrives after a newer ride update makes the decision stale, the success is retained in `DynamicBlockExecution`, the current session is not mutated, and the status becomes `reconciliation_required` for later operational handling.

Execution status is structured factual evidence. An explanation may display that status, but neither deterministic nor generated text can set or change provider state.

### Completion and settlement

`settle_completed_transaction(...)` is the only Phase-10 path that accepts `RideTransactionOutcome`. After the ride finishes it fetches the normalized block, debits the exact actual fare, and releases the full remainder. It never calls the predictor or optimizer. If the actual fare exceeds the remaining authorization, it performs no speculative extra collection and returns an explicit shortfall with `insufficient_reserved_funds` status.

### RazorpayProvider status

The official [UPI Reserve Pay product page](https://razorpay.com/docs/payments/recurring-payments/upi-reserve-pay/?preferred-country=IN) was checked on 2026-08-30. It verifies the Single Block Multi Debit product concept, customer authorization, subsequent debit flow, transport/mobility use case, and account-activation requirement. The retrievable public material did not provide a complete, unambiguous Reserve Pay endpoint, HTTP method, authentication construction specific to these operations, create/increase/debit/release request and response schemas, status mapping, idempotency contract, webhook schema, or error taxonomy.

> The Razorpay provider boundary is implemented, but concrete network mappings are intentionally not fabricated without verified Reserve Pay API documentation.

`RazorpayProvider` therefore implements the same Python contract, validates `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` from environment configuration, exposes an injectable transport boundary, advertises unsupported capabilities, and raises `UnsupportedProviderOperation` for network operations. It never silently falls back to mock. Credentials are excluded from representations, serialized models, audit events, CLI output, and exceptions. To enable real execution, approved documentation must define and version all mappings listed above, followed by offline fake-transport contract tests and a controlled sandbox verification.

### Full offline demo

```powershell
python -m reserve_pay_optimizer reserve-pay-demo `
  --provider mock `
  --model artifacts/prediction/fare_distribution_personalized_v1 `
  --base-model artifacts/prediction/fare_distribution_v1 `
  --scenario examples/dynamic_reoptimization.json `
  --risk-profile balanced `
  --explain `
  --verbose
```

The checked-in scenario calculates the initial recommendation, authorizes it with the mock provider, applies both in-ride updates, executes each additional authorization, settles the completed fare, releases unused funds, and returns the final normalized block.

Demonstrate a failed first additional authorization; the first event's authorized amount remains unchanged:

```powershell
python -m reserve_pay_optimizer reserve-pay-demo `
  --provider mock `
  --model artifacts/prediction/fare_distribution_personalized_v1 `
  --base-model artifacts/prediction/fare_distribution_v1 `
  --scenario examples/dynamic_reoptimization.json `
  --fail-first-increase `
  --verbose
```

Demonstrate one transient failure followed by a safe retry with the same idempotency key:

```powershell
python -m reserve_pay_optimizer reserve-pay-demo `
  --provider mock `
  --model artifacts/prediction/fare_distribution_personalized_v1 `
  --base-model artifacts/prediction/fare_distribution_v1 `
  --scenario examples/dynamic_reoptimization.json `
  --retry-first-increase `
  --verbose
```

Selecting `--provider razorpay` never falls back. Missing environment configuration returns `provider_configuration_error`; configured but undocumented execution returns `unsupported_provider_operation`.

## Phase 11 — Dashboard / Interactive Demo

Phase 11 is a visualization and operator-demo layer. It does not reimplement financial logic in the browser:

```text
React / TypeScript dashboard
        -> thin FastAPI JSON adapter
        -> existing Python prediction, personalization, policy,
           optimization, dynamic, explanation, and mock execution services
```

Money crosses the API as integer paise and probabilities cross as decimal strings. The FastAPI lifespan loads the trusted base and personalized model artifacts once; individual requests reuse those in-memory models. Invalid input and unavailable artifacts return structured, credential-safe errors.

The interface has exactly three primary screens:

1. **Optimizer** — edits legitimate pre-ride context, customer-history demonstration profile, and merchant risk profile; displays the recommended block, modeled collection coverage, Q05–Q99 uncertainty, expected unused reserve, and deterministic explanation. Mock authorization is an explicit separate action.
2. **What-if Simulator** — debounces distance, projected traffic/duration, surge, risk, and customer-profile changes; asks the backend to recompute both decisions; shows previous versus revised reserve and a dynamic ride timeline. The failure demo visibly preserves the previously authorized amount when an additional authorization fails.
3. **Evidence** — reads one precomputed artifact generated from a fresh deterministic 10,000-ride simulator dataset and compares Exact Estimate, Fixed 20%, and Optimized Balanced on the same outcomes. It includes provenance, per-city diagnostics, personalization proof, dynamic evidence, block distribution, and excess-versus-success trade-off charts.

Traffic is not a new model feature. The dashboard adapter deterministically maps the selected traffic band to projected duration, which is already a legal decision-time feature. Actual fare remains excluded until the post-ride settlement path.

### Reproducible evidence

The checked-in `demo/evidence/dashboard_evidence.json` was generated, not hand-authored:

```powershell
python -m reserve_pay_optimizer prepare-dashboard-evidence `
  --count 10000 `
  --seed 202611 `
  --output demo/evidence/dashboard_evidence.json
```

It records the dataset count, seed, customer pool, predictor/model versions, Balanced policy target, project version, generation time, and canonical SHA-256 dataset fingerprint. All evidence is synthetic and is not production Razorpay, merchant, Uber, Ola, or measured city data. The observed test metrics are displayed honestly and need not equal the 97% modeled policy target exactly.

### Local startup

Use two terminals from the repository root. First install/update the Python environment and start the API:

```powershell
python -m pip install -e .
python -m reserve_pay_optimizer serve-dashboard --host 127.0.0.1 --port 8000
```

Then install and start the dashboard:

```powershell
cd frontend
pnpm install
pnpm dev
```

Open `http://127.0.0.1:5173/optimizer`. Vite proxies `/api` to the local FastAPI service. No credentials or external payment network are required; execution demonstrations use `MockReserveProvider` only.

### Five-minute demo walkthrough

1. Open **Optimizer** and point out ₹650.00 estimated fare, Hyderabad context, Stable History, and Balanced / 97% policy. Calculate and show the exact recommended block, Q05–Q99 rail, personalized mode, and deterministic reason.
2. Switch customer profile to **Overrun-Prone History** and recalculate. The changed distribution and recommendation come from the existing Phase-7 model, not UI arithmetic.
3. Open **What-if Simulator**, increase traffic and surge, and show the previous/new comparison after the backend debounce. Run **Failure demo** to show that the recommendation increases while authorized funds remain unchanged after provider rejection.
4. Open **Evidence** and identify the 10,000-record seed/fingerprint. Compare Exact, Fixed 20%, and Optimized on collection success and average excess, then show city diagnostics and the dynamic/static evidence.
5. Return to **Optimizer** and authorize through the mock provider. Emphasize that recommendation precedes execution and that this phase performs no live Razorpay call.

### Dashboard API

The adapter exposes `GET /api/health`, `POST /api/optimize`, `POST /api/what-if`, `POST /api/mock/authorize`, `POST /api/dynamic-demo`, `GET /api/evidence`, and `GET /api/demo-scenarios`. These routes orchestrate existing services only; they contain no duplicate quantile, objective, risk-policy, or personalization formulas.

## Tests

```powershell
python -m unittest discover -s tests -v
```

The Python suite covers every Phase 1–10 invariant plus the Phase-11 API contract, backend delegation, real what-if recomputation, precomputed evidence provenance, mock-execution separation, and failed-increase authorization invariant.

Frontend checks run from `frontend`:

```powershell
pnpm test
pnpm build
```

The component suite covers optimizer inputs/results, policy changes, explicit mock execution, what-if recalculation, dynamic failure state, and evidence provenance/baselines. The production command runs TypeScript checks before the Vite build.

## Phase 12 — AI Agent Layer

Phase 12 introduces a structured multi-agent orchestration layer over the unchanged deterministic financial services:

```text
User / API / CLI request
        ↓
Reserve Intelligence Agent
        ↓
Approved Tool Calls (Allowlisted & Audited)
 ┌─────────────────────────────┐
 │ 1. get_customer_history     │
 │ 2. get_transaction_predict  │
 │ 3. calculate_risk           │
 │ 4. optimize_block           │
 └─────────────────────────────┘
        ↓
Existing Deterministic Python Services
        ↓
Structured ReserveAgentDecision
        ↓
Explanation Agent (Phase-9 evidence)
        ↓
AgentResponse (Decision + Trace + Explanation)
```

### Central Design Principle

> **Agents orchestrate. Existing deterministic services decide.**

The agent does not invent reserve numbers, calculate quantiles, modify lambda weights, or alter merchant risk policies. Tool outputs are authoritative and immutable.

### Two Agent Roles

1. **Reserve Intelligence Agent:** Coordinates approved tools to gather causal context, generate quantile predictions, evaluate risk policy constraints, and optimize the reserve block.
2. **Explanation Agent:** Translates the authoritative decision into clear, human-readable explanations using structured Phase-9 evidence. It cannot alter the computed reserve amount.

### Approved Tool Registry

| Tool | Purpose | Source Service |
|---|---|---|
| `get_customer_history()` | Retrieves completed ride metrics before the ride timestamp. | `CustomerHistoryProvider` |
| `get_transaction_prediction()` | Predicts Q05–Q99 quantiles via base or personalized models. | `PersonalizedFarePredictor` |
| `calculate_risk()` | Evaluates policy feasibility and target coverage. | `ReserveRiskPolicy` |
| `optimize_block()` | Optimizes minimal reserve block satisfying policy. | `PolicyConstrainedOptimizer` |
| `get_merchant_history()` | Honestly reports that merchant history is unavailable. | Explicit status `unavailable` |

### Security & Safety Boundaries

- **No Mutating Payment Authority:** No agent is given authority to autonomously create, increase, debit, or release Reserve Pay funds. Payment execution remains an explicit operator action.
- **No Arbitrary Tool Execution:** The tool registry strictly allowlists approved tools. The model cannot execute shell commands, eval Python code, inspect environment secrets, or make network calls.
- **Strict Decision Consistency:** Final decisions are validated against optimizer outputs. Any modification raises `DecisionConsistencyError`.
- **Bounded Execution:** Agent loops enforce strict step limits (`max_steps = 8`) to prevent infinite iterations.

### Direct vs. Agent-Orchestrated Equivalence

For identical inputs, direct service execution and agent orchestration produce **100% identical financial results**:
- Recommended block paise
- Estimated collection probability
- Risk profile
- Objective score

### CLI Usage

```powershell
python -m reserve_pay_optimizer agent-decide `
  --model artifacts/prediction/fare_distribution_personalized_v1 `
  --base-model artifacts/prediction/fare_distribution_v1 `
  --history examples/personalization_stable_history.json `
  --file examples/personalization_current_ride.json `
  --risk-profile balanced `
  --show-trace
```

### Agent API

- `POST /api/agent/decide`: Runs the full agent orchestration pipeline.
- `GET /api/agent/capabilities`: Reports available tools, model mode, and merchant history status.
- `GET /api/agent/runs/{run_id}`: Retrieves in-memory tool execution traces.

## Tests

```powershell
python -m unittest discover -s tests -v
```

The Python test suite covers 216 tests across all phases (domain, simulator, baselines, prediction, optimization, policy, dynamic re-optimization, explainability, Reserve Pay execution, web API, and agent orchestration).

Frontend checks run from `frontend`:

```powershell
pnpm test
pnpm build
```

## Explicitly not implemented

Phase 12 adds an AI agent orchestration layer. It does not contain:

- browser-side financial calculations;
- autonomous funds movement or automated capture;
- fake merchant risk scores or fabricated merchant transaction history;
- vendor LLM API dependencies for test execution;
- a fourth top-level dashboard screen;
- production database or distributed state storage.

## What remains for Phase 13

Phase 13 will introduce **Evaluation & Evidence** (comprehensive validation, benchmark comparisons, and publication-ready evidence artifacts). Phase 14 will produce the judging presentation.

