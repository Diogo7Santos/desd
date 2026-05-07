# FoodNet (DESD) — Regional Food Marketplace

FoodNet is a Django modular monolith for a regional producer-to-customer marketplace.  
It includes role-based operations (Customer / Producer / Admin), Stripe checkout and webhook processing, automated weekly producer settlements, and operational reporting.

## Table Of Contents
- [1. Architecture Summary](#1-architecture-summary)
- [2. Core Features](#2-core-features)
- [3. Technology Stack](#3-technology-stack)
- [4. Prerequisites](#4-prerequisites)
- [5. Environment Configuration](#5-environment-configuration)
- [6. Quick Start (Docker)](#6-quick-start-docker)
- [7. Initial Data And Test Accounts](#7-initial-data-and-test-accounts)
- [8. Stripe Setup And Webhook Listener](#8-stripe-setup-and-webhook-listener)
- [9. How Payments Work](#9-how-payments-work)
- [10. How Automated Weekly Settlements Work](#10-how-automated-weekly-settlements-work)
- [11. Operations Guide](#11-operations-guide)
- [12. How To Run Automated Tests](#12-how-to-run-automated-tests)
- [13. Security Considerations](#13-security-considerations)
- [14. Troubleshooting](#14-troubleshooting)
- [15. Known Limitations / Future Improvements](#15-known-limitations--future-improvements)

## 1. Architecture Summary

FoodNet uses a **modular monolith** pattern:

| Layer | Description |
|---|---|
| Django apps | `accounts`, `catalog`, `cart`, `orders`, `payments`, `community`, `admin_dashboard` |
| Data store | PostgreSQL |
| Async / scheduling | Celery Worker + Celery Beat |
| Broker / cache / sessions | Redis |
| Payments | Stripe Checkout + webhook event handling |
| Deployment runtime | Docker Compose |
| Reverse proxy | Nginx |

### Runtime Containers

| Service | Purpose |
|---|---|
| `web` | Django application server (`runserver`) |
| `db` | PostgreSQL 16 |
| `redis` | Redis broker/cache/session backend |
| `celery-worker` | Background task execution |
| `celery-beat` | Scheduled task dispatch |
| `nginx` | Reverse proxy for app/static/media |

## 2. Core Features

### Customer
- Account registration/login.
- Browse/search/filter products.
- Cart checkout flow.
- Stripe payment redirection and completion.
- Order history and order detail tracking.

### Producer
- Product create/update management.
- Incoming order management.
- Payment records and settlements views.
- Commission reporting views.
- CSV financial export workflow.

### Admin
- Admin portal dashboard (`/admin-portal/`).
- Financial reporting and network CSV export.
- Payment records and settlement oversight.
- Django admin access for model-level operations.

### Platform-level
- Role-based access control.
- Order state transitions (including `PENDING_PAYMENT` flow).
- Webhook-driven payment confirmation and order finalisation.
- Automated weekly settlements for eligible paid records.
- Extensive automated tests.

## 3. Technology Stack

| Component | Technology |
|---|---|
| Backend | Django 5.x |
| API layer | Django REST Framework |
| Database | PostgreSQL |
| Cache/session/broker | Redis |
| Task queue | Celery |
| Scheduler | Celery Beat |
| Payments | Stripe |
| Reverse proxy | Nginx |
| Container orchestration | Docker Compose |

## 4. Prerequisites

Install the following before running the project:

1. **Docker Desktop** (or Docker Engine + Compose plugin)
2. **Stripe account** (test mode keys)
3. **Stripe CLI** (for local webhook forwarding)

Optional but useful:
- `git`
- `curl`

## 5. Environment Configuration

Create a repo-root `.env` file (same directory as `docker-compose.yml`).

### Required variables

```env
DJANGO_SECRET_KEY=change-me
DJANGO_DEBUG=1
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

DB_NAME=desd_db
DB_USER=desd_user
DB_PASSWORD=desd_pass
DB_PORT=5432

STRIPE_SECRET_KEY=sk_test_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
```

### Optional variables

```env
REDIS_HOST=redis
REDIS_PORT=6379
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1

POSTCODES_IO_ENABLED=1
POSTCODES_IO_BASE_URL=https://api.postcodes.io
POSTCODES_IO_TIMEOUT=3
POSTCODES_IO_CACHE_TIMEOUT=86400
```

## 6. Quick Start (Docker)

### 6.1 Build and start containers

```bash
docker compose up --build -d
```

### 6.2 Apply migrations

```bash
docker compose exec -T web python manage.py migrate
```

### 6.3 Create an admin superuser

```bash
docker compose exec -T web python manage.py createsuperuser
```

### 6.4 Access points

- App via Nginx: `http://localhost`
- Django app direct: `http://localhost:8000`
- Django admin: `http://localhost/admin/`
- Admin portal: `http://localhost/admin-portal/`

## 7. Initial Data And Test Accounts

### Option : Load fixture data

```bash
docker compose exec -T web python manage.py loaddata seed_data.json
```

## 8. Stripe Setup And Webhook Listener

### 8.1 Start Stripe webhook forwarding

From your host machine:

```bash
stripe listen --forward-to localhost:8000/p/api/payments/stripe/webhook/
```

The CLI prints a signing secret (`whsec_...`). Put this value into:

```env
STRIPE_WEBHOOK_SECRET=whsec_xxx
```

Then restart web-related services:

```bash
docker compose restart web celery-worker celery-beat
```

### 8.2 Stripe test card

Use this card during checkout:

- Card number: `4242 4242 4242 4242`
- Expiry: any future date
- CVC: any 3 digits
- Postcode: any valid format

## 9. How Payments Work

### 9.1 Checkout
1. Customer places order.
2. System creates order + `PaymentRecord` entries (pending).
3. Stripe Checkout session is created.
4. Customer is redirected to Stripe-hosted checkout page.

### 9.2 Webhook verification
1. Stripe sends event to `/p/api/payments/stripe/webhook/`.
2. Signature is verified using `STRIPE_WEBHOOK_SECRET`.
3. Event id is stored in `ProcessedWebhookEvent` to prevent duplicate processing.

### 9.3 Order finalisation
On successful payment events:
1. Relevant `PaymentRecord` rows are marked `PAID`.
2. `paid_at` and provider identifiers are persisted.
3. Product stock is decremented.
4. Customer cart is cleared.
5. Order state moves from `PENDING_PAYMENT` to `PENDING`.
6. Status history entry is recorded.

### 9.4 Settlement automation linkage
Only paid records that satisfy settlement eligibility are picked up by settlement generation.

## 10. How Automated Weekly Settlements Work

Settlement task: `payments.tasks.generate_weekly_settlements`

### Scheduled run
- Celery Beat schedules weekly execution (Monday 00:05, project timezone).
- It targets the **previous week** (`week_start` to `week_end`).

### Eligibility criteria
A payment record is eligible when all conditions are true:
1. `PaymentRecord.status == PAID`
2. Related order is in fulfilled state (`READY` or `DELIVERED`)
3. `paid_at` is within target settlement week
4. Not already linked via `SettlementItem`

### Output
- Creates/updates `SettlementBatch` per producer/week.
- Attaches records through `SettlementItem`.
- Recomputes gross/commission/net totals.

### Manual settlement test (inside app container)

```bash
docker compose exec -T web python manage.py shell
```

```python
from payments.tasks import generate_weekly_settlements
generate_weekly_settlements.delay()   # async
# or
generate_weekly_settlements()         # sync immediate execution
```

## 11. Operations Guide

### Restart a service

```bash
docker compose restart web
```

### Stop environment

```bash
docker compose down
```

### Stop and remove volumes (destructive)

```bash
docker compose down -v
```

### Inspect logs

```bash
docker compose logs -f web
docker compose logs -f celery-worker
docker compose logs -f celery-beat
```

## 12. How To Run Automated Tests

### Targeted suites

```bash
docker compose exec -T web python manage.py test payments --keepdb
docker compose exec -T web python manage.py test accounts catalog orders --keepdb
```

### Full suite

```bash
docker compose exec -T web python manage.py test --keepdb
```

Notes:
- `--keepdb` makes repeated runs faster.
- Remove `--keepdb` for a clean test DB build.

## 13. Security Considerations

- Role-based route protection for customer/producer/admin boundaries.
- Stripe webhook signature validation.
- Idempotent webhook processing via stored event ids.
- HTTPOnly and SameSite cookie settings in Django config.
- CSRF middleware enabled by default.
- Password hashing and Django password validators enabled.
- Payment flow avoids trusting client-side payment success without webhook confirmation.

## 14. Troubleshooting

### Docker API permission errors
- Ensure Docker Desktop is running.
- Re-run command after Docker daemon is healthy.

### Port already in use
- Check `5432`, `6379`, `8000`, `80`.
- Stop conflicting local services or change mapped ports.

### Stripe webhook not updating payments
- Confirm Stripe CLI is running.
- Confirm `STRIPE_WEBHOOK_SECRET` matches current `stripe listen` session.
- Check `web` logs for signature validation errors.

### Payments not moving beyond pending
- Ensure webhook events are reaching `/p/api/payments/stripe/webhook/`.
- Verify `checkout_session_id` linkage exists on `PaymentRecord`.

### Celery tasks not running
- Check `celery-worker` and `celery-beat` container logs.
- Verify Redis container is healthy.

### Test DB prompts / conflicts
- Use `--keepdb` to avoid interactive delete prompts.
- If migration graph conflict appears, create/commit merge migration before rerunning tests.


---

## Project Structure (Reference)

```text
backend/
  accounts/
  catalog/
  cart/
  community/
  orders/
  payments/
  admin_dashboard/
  config/

frontend/
  templates/
  static/

nginx/
docker-compose.yml
README.md
```
