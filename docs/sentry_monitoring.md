# Sentry Monitoring

DreamAgent backend monitoring is optional and enabled only when `SENTRY_DSN` is configured.

## Processes Covered

| Process | Service tag |
| --- | --- |
| FastAPI backend | `backend` |
| Durable session chat worker | `session-chat-worker` |
| Durable project creation worker | `project-creation-worker` |

The backend captures unhandled FastAPI errors and HTTP 5xx responses. Workers capture loop errors and handled durable run failures with run, project, session, and channel tags where available.

## Environment Variables

```bash
SENTRY_DSN="https://..."
SENTRY_ENVIRONMENT="production"
SENTRY_RELEASE="dreamagent-backend@<git-sha>"
SENTRY_TRACES_SAMPLE_RATE="0"
SENTRY_PROFILES_SAMPLE_RATE="0"
SENTRY_SEND_DEFAULT_PII="false"
SENTRY_LOG_LEVEL="ERROR"
PAYMENT_SENTRY_SUCCESS_EVENTS="false"
```

Tracing and profiling are disabled by default to avoid noise and cost. Increase the sample rates only when investigating performance issues.

`PAYMENT_SENTRY_SUCCESS_EVENTS` controls Lemon Squeezy success telemetry. Keep it `false` by default to avoid noisy payment audit events in Sentry. Payment failures and payment-processing anomalies are still sent to Sentry when `SENTRY_DSN` is configured.

## Deployment

Install the dependency:

```bash
pip install -r requirements.txt
```

Export Sentry env vars before reloading PM2, or add them to the server `.env` file loaded by the backend:

```bash
export SENTRY_DSN="https://..."
export SENTRY_ENVIRONMENT="production"
export SENTRY_RELEASE="dreamagent-backend@$(git rev-parse --short HEAD)"
export SENTRY_TRACES_SAMPLE_RATE="0"
export SENTRY_PROFILES_SAMPLE_RATE="0"
export SENTRY_SEND_DEFAULT_PII="false"
export SENTRY_LOG_LEVEL="ERROR"
export PAYMENT_SENTRY_SUCCESS_EVENTS="false"

pm2 startOrReload ecosystem.config.json --update-env
pm2 save
```

If `SENTRY_DSN` is not set, all Sentry hooks become no-ops and processes continue normally.

## Data Scrubbing

Events are scrubbed before sending. The scrubber redacts authorization headers, cookies, tokens, API keys, bot tokens, secrets, passwords, DSNs, webhook URLs, and common bearer/token string patterns.

`SENTRY_DSN` is a backend/system integration variable. It should not be added as a generated project environment variable unless a user explicitly wants Sentry inside their generated app.

## Payment Events

Lemon Squeezy failures are captured as Sentry errors with safe context only:

- checkout provider errors
- checkout exceptions
- invalid webhook signatures
- invalid webhook JSON
- webhook processing exceptions
- missing user IDs
- missing plan or credit-pack mappings
- provider payment-failed webhook events

Successful plan assignments, cancellations, and credit purchases are captured only when:

```bash
PAYMENT_SENTRY_SUCCESS_EVENTS="true"
```

Payment Sentry events never include raw webhook payloads, Lemon Squeezy API keys, webhook signatures, customer emails, card/payment details, or checkout URLs.
