# Reserve Pay Block Optimizer — 3–5 minute demo runbook

## Before the demo

Start the API and dashboard in separate terminals:

```powershell
python -m reserve_pay_optimizer serve-dashboard --host 127.0.0.1 --port 8000
```

```powershell
cd frontend
pnpm dev
```

Open `http://127.0.0.1:5173/optimizer`. Use the checked-in model artifacts and
the mock provider; the demonstration needs no network credentials.

## 0:00–0:35 — The problem

“A ride platform knows an estimate before a ride, but the final fare can change.
Blocking only the estimate risks under-collection. A fixed, oversized buffer
unnecessarily locks customer funds. This system predicts uncertainty, applies a
merchant policy, and chooses the smallest supported reserve that meets that
policy.”

Point out that money is represented in integer paise and the actual fare is not
available to the decision engine.

## 0:35–1:35 — One decision under uncertainty

On **Optimizer**, use the Hyderabad example and calculate with Balanced policy.
Show, in this order:

1. Q05–Q99 conditional fare range rather than a single point prediction;
2. personalized or cold-start prediction mode and completed-history count;
3. the 97% modeled policy target and selected candidate;
4. expected unused reserve and objective components;
5. the deterministic explanation and agent tool trace.

Say: “The agent orchestrates approved tools. The Python predictor, policy, and
optimizer remain the authority for every financial number.”

## 1:35–2:20 — Personalization and policy

Switch between Stable History and Overrun-Prone History, then between Aggressive,
Balanced, and Conservative policy. Recalculate after each deliberate change.
Explain that customer ID is used only to retrieve completed prior rides; raw IDs
and actual current-ride outcome are prohibited model features.

Do not describe a modeled probability as a guarantee. The top modeled quantile
is Q99, not certainty or a maximum possible fare.

## 2:20–3:10 — A changing ride and a failed authorization

Open **What-if Simulator**. Increase projected traffic/duration or surge. Show
the previous and revised recommendation and the additional amount required.
Run the deterministic failure demonstration.

Emphasize the invariant visible on screen:

```text
new recommended target > currently authorized amount
```

after a failed provider attempt. The payment failure does not rewrite the
financial recommendation, and it does not mutate authorized state.

## 3:10–3:45 — Execution boundary

Return to **Optimizer** and explicitly authorize using the mock provider. Explain:

```text
prediction → optimization → policy → recommendation → execution
```

The provider executes an already-computed amount. It does not calculate one.
Mention idempotent create/increase/debit/release, partial debit, release of unused
funds, safe retries, stale-decision reconciliation, and shortfall reporting.

## 3:45–4:35 — Evidence, not a hand-picked result

Open **Evidence**. Identify the fresh synthetic cohort’s count, seed, and SHA-256
fingerprint. Compare Exact Estimate, Fixed 20%, and Optimized Balanced on:

- collection success and under-block rate;
- average excess block and excess-block ratio;
- capital efficiency;
- Q05–Q99 observed calibration;
- per-city diagnostics;
- static versus dynamic re-optimization;
- agent-versus-direct decision mismatches.

Use the values displayed from `demo/evidence/final_evidence.json`; do not memorize
or substitute roadmap example numbers. Call out the 95% Wilson interval for
collection success and the seeded bootstrap interval for average excess reserve.

## 4:35–5:00 — Close

“The project now covers the complete decision chain: a typed India mobility
context, synthetic reproducible data, uncertainty prediction, personalized risk
policy, mathematical optimization, dynamic updates, explainability, safe payment
execution architecture, an auditable agent layer, and statistically qualified
evidence. Current results are synthetic and suitable for an offline product demo,
not a claim of production performance.”

## Backup CLI proof

If the browser is unavailable, show these deterministic commands:

```powershell
python -m reserve_pay_optimizer agent-decide `
  --model artifacts/prediction/fare_distribution_personalized_v1 `
  --base-model artifacts/prediction/fare_distribution_v1 `
  --history examples/personalization_stable_history.json `
  --file examples/personalization_current_ride.json `
  --risk-profile balanced `
  --show-trace

python -m reserve_pay_optimizer reserve-pay-demo `
  --provider mock `
  --model artifacts/prediction/fare_distribution_personalized_v1 `
  --base-model artifacts/prediction/fare_distribution_v1 `
  --scenario examples/dynamic_reoptimization.json `
  --risk-profile balanced `
  --explain `
  --verbose
```
