# Reserve Pay Block Optimizer

This dependency-free Python 3.11+ project defines and measures reserve-block baselines for India-first mobility payments. Phase 2 provides the comparison framework that a future ML/optimization strategy must beat; it does not contain an optimizer.

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
  cli.py                            CLI adapter
examples/
  valid_hyderabad_ride.json
  invalid_ride.json
  baseline_evaluation.json          Deterministic Phase 2 fixture
tests/                              Phase 1 and Phase 2 tests
```

Domain and service code remains independent of HTTP and Razorpay SDK objects. Runtime dependencies remain empty.

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

The suite covers every Phase 1 invariant plus exact-estimate decisions, fixed-buffer configuration and ceiling boundaries, small/large amounts, overflow, decision/outcome leakage protection, transaction evaluation, equality, aggregation formulas, metric precision, fair comparison, ID integrity, and separated JSON parsing.

## Explicitly not implemented

Phase 2 is only the measurement framework for a future optimizer. It does not contain:

- a transaction simulator or random fixture generation;
- city volatility or traffic-variance rules;
- XGBoost, LightGBM, quantile regression, or other ML;
- probability distributions or predicted final amounts;
- an optimized reserve amount or block search;
- risk profiles or customer personalization;
- dynamic re-optimization;
- LLM explanations or AI agents;
- Razorpay API calls;
- a frontend or dashboard;
- production backtesting data.

## What remains for Phase 3

Phase 3 may generate a realistic, reproducible transaction dataset and feed it into the existing comparison service. It must keep outcome generation separate from decision-time contexts and must not add prediction or optimization logic reserved for later phases.
