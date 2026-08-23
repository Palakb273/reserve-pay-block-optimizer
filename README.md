# Reserve Pay Block Optimizer

This Python 3.11+ project defines, simulates, and predicts uncertain final fares for India-first mobility payments. Phase 4 adds a learned conditional-distribution engine using scikit-learn. It predicts fare uncertainty; it does not choose a reserve amount.

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

`ReserveDecision` contains only the transaction ID, strategy/version, block amount, and deterministic parameters. It has no confidence, probability, predicted final amount, risk score, explanation, or outcome.

A future optimizer can implement this protocol and enter the same comparison service without changing evaluation code.

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
  services/
    mobility_validation.py          Phase 1 validation/normalization
    evaluation.py                   Transaction and aggregate evaluation
    comparison.py                   Fair multi-strategy comparison
    evaluation_input.py             Separated JSON dataset parser
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
  cli.py                            CLI adapter
artifacts/prediction/               Reproducible Phase 4 trained artifact
examples/
  valid_hyderabad_ride.json
  invalid_ride.json
  baseline_evaluation.json          Deterministic Phase 2 fixture
tests/                              Phase 1, Phase 2, and Phase 3 tests
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

## Tests

```powershell
python -m unittest discover -s tests -v
```

The suite covers every Phase 1–3 invariant plus Phase 4 leakage protection, deterministic features/splits/training, quantile output and repair, hand-computable metrics, trusted persistence, and simulator-to-CLI integration.

## Explicitly not implemented

Phase 4 predicts uncertainty but does not optimize reserve amounts. The project does not contain:

- production data or claims that synthetic city profiles are measured statistics;
- TensorFlow, PyTorch, XGBoost, LightGBM, or an LLM SDK;
- an optimized reserve amount or block search;
- risk profiles or customer personalization;
- dynamic re-optimization;
- LLM explanations or AI agents;
- Razorpay API calls;
- a frontend or dashboard;
- production backtesting data.

## What remains for Phase 5

Phase 5 may consume a `FareDistributionPrediction` and define an explicit reserve optimization objective, constraints, and evidence-based decision policy. It must decide how much to block without leaking outcomes or changing the Phase 4 predictor into a decision engine. Risk profiles, personalization, re-optimization, explanation/agents, Razorpay calls, and UI remain later work.
