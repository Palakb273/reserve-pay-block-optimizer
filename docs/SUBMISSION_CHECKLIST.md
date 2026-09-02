# Final submission checklist

Create the final submission from Git-tracked files, not by recursively archiving
the working directory. This prevents ignored local configuration and development
dependencies from being included accidentally.

## Before packaging

1. Run `git status` and review every tracked change.
2. Run `git ls-files .env` and confirm it produces no output.
3. Run the backend tests, frontend tests, and frontend production build.
4. Confirm the checked-in evidence and model artifacts are the intended versions.
5. Commit every intended submission change; `git archive HEAD` includes committed
   files only and deliberately omits uncommitted work.

## Do not submit

- `.env` or any other local secret/configuration file
- `.venv/`
- `frontend/node_modules/`
- `frontend/dist/`
- local logs, temporary databases, caches, or test output
- IDE configuration containing credentials or private paths
- private keys, certificates, access tokens, API keys, or database credentials

`.env.example` is safe to submit because it contains placeholders only.

## Safe archive procedure

From a clean Git checkout, create an archive containing tracked committed files:

```powershell
git archive --format=zip --output=reserve-pay-block-optimizer-submission.zip HEAD
```

If the local `.env` has ever been shared outside the intended development
environment, rotate its database and ingestion credentials before proceeding.

## Production-only security work

The local hackathon build is not a production financial deployment. A production
deployment still requires identity and tenant authorization, rate limiting, TLS
termination, CSP/security headers, persistent atomic idempotency, centralized
secret management, MongoDB retention/deletion controls, monitoring, verified
webhook handling, a verified real Razorpay contract, signed model artifacts, and
automated Python vulnerability scanning.
