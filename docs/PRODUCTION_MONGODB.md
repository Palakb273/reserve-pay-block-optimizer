# MongoDB production mode

The application now has two deliberately separate operating modes:

- `demo` is the default. It keeps the checked-in synthetic customer profiles, mock Reserve Pay flow, evidence screens, and all existing tests.
- `mongodb` uses persisted completed rides for personalization and stores optimization runs and agent traces in MongoDB. Synthetic demo/payment endpoints are disabled in this mode.

## Configure

Install the production dependency group:

```powershell
python -m pip install -e ".[mongodb]"
```

Copy `.env.example` into your deployment secret/configuration system and set:

```text
RPO_DATA_MODE=mongodb
MONGODB_URI=<MongoDB Atlas or replica-set connection string>
MONGODB_DATABASE=reserve_pay_optimizer
RPO_INGEST_API_KEY=<at least 32 random characters>
RPO_CORS_ORIGINS=https://your-dashboard.example
```

Do not commit a real URI or API key. For Atlas, require TLS, create a least-privilege database user, restrict network access, enable backups, and configure monitoring. Use a secret manager rather than a plaintext deployment file.

Start the API normally. `GET /api/health` is a liveness check and `GET /api/ready` verifies that models and storage are ready. Route traffic only when readiness returns HTTP 200.

## Production request flow

Optimization requests must include a stable, non-PII `customer_id`. The response includes `meta.run_id`; the persisted record is retrievable from `GET /api/optimization-runs/{run_id}`.

After a ride is complete, the trusted backend posts it to `POST /api/rides/completed` with the ingestion key in `X-API-Key`. The payload is:

```json
{
  "transaction_id": "ride_01J...",
  "customer_id": "customer_01J...",
  "estimated_amount_paise": 65000,
  "actual_amount_paise": 70200,
  "city": "hyderabad",
  "distance_km": "18.4",
  "estimated_duration_minutes": 42,
  "surge_multiplier": "1.18",
  "timestamp": "2027-01-15T18:30:00+05:30",
  "completed_at": "2027-01-15T19:24:00+05:30"
}
```

The write is idempotent by `transaction_id`: an identical replay succeeds with `status: replayed`; changed data for the same ID returns HTTP 409. History queries enforce `completed_at < current ride timestamp`, exclude the current transaction, and reuse the same tested aggregation formulas as demo mode.

MongoDB creates these collections and indexes on startup:

- `completed_rides`: unique `transaction_id`, plus `(customer_id, completed_at)`
- `optimization_runs`: unique `run_id`, plus `(transaction_id, created_at)`
- `agent_runs`: unique `run_id`

## Boundary of this production step

This makes application data persistent and separates production data from demo fixtures. It does not claim that the synthetic-trained model is production-calibrated, and it does not enable real Reserve Pay execution. Before live financial use, train and validate on approved production data, add your identity/authorization gateway, define retention and deletion policies, test MongoDB failover/backups, add metrics and alerting, and complete the real provider contract described in the main README.
