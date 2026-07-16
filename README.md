# TSEC Alumni Connect

Local hackathon portal for Thadomal Shahani Engineering College.

## Run locally

1. Copy `.env.example` to `.env` and set a strong `SESSION_SECRET`.
2. Run `docker compose up --build`.
3. Visit `http://localhost:5173`, choose **Explore demo**, then sign in as a seeded user.

The Docker stack seeds fictional content automatically. Google and Microsoft buttons activate when their client ID and secret are present. Configure each provider's callback as `http://localhost:8000/auth/<provider>/callback`.

Set `API_PUBLIC_URL=http://localhost:8000` for local OAuth. In deployment, change it to the HTTPS origin that actually serves FastAPI, then register its exact `/auth/google/callback` and `/auth/microsoft/callback` URLs with the providers.

Razorpay uses test-mode keys. Set both `RAZORPAY_KEY_ID` (beginning `rzp_test_`) and `RAZORPAY_KEY_SECRET` from the same Razorpay test account. The donation page opens Razorpay Checkout and verifies its returned signature on the server. Without keys, the donation workflow remains usable as a clearly labelled local demo payment. A provider outage is returned as a clear `502` response; an invalid or mismatched key pair is returned as `400`.

The backend uses `uv` and SQLAlchemy; Docker runs PostgreSQL 16, while a SQLite URL is supported only for quick local tests.

For API-only development, run `cd backend && uv sync && uv run uvicorn app.main:app --reload`. Use Python 3.12 or 3.13 locally, matching the Docker image.

## Roles

- Visitors can browse the directory, jobs, and events.
- Pending alumni can finish their profile but must be verified by an admin before they can contact people or submit content.
- Verified alumni can see alumni email addresses, send connection requests, publish jobs, and submit events.
- Admins verify alumni and moderate events.
