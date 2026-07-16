# Twilio Setup Guide for This App

## Current status
`/webhook` now handles both payload shapes on the same endpoint:
- The simple JSON contract (`{"from": ..., "message": ...}`) used by the test suite and for manual/local testing, replying with `{"reply": ...}`.
- Twilio's form-encoded WhatsApp webhook (`From`, `To`, `Body`), replying with TwiML XML so Twilio delivers the response inline — no separate outbound API call needed for replies.

The `twilio` SDK is installed and a `send_whatsapp_message(to_number, body, from_number=None)` helper (in `app/main.py`) is available for proactive/outbound sends (delivery-fee/bank-info push, payment-claim notifications) outside the reply-to-incoming-message flow. It's a no-op (returns `False`) until the env vars below are set. **`from_number` matters once you have more than one business** — pass that business's own `whatsapp_number` explicitly, or the message goes out from whatever `TWILIO_WHATSAPP_NUMBER` is set to regardless of which business the customer is talking to. See the multi-business section below.

## What the current app already does
- a webhook endpoint at `/webhook` (JSON and Twilio form-encoded, with Twilio signature verification once `TWILIO_AUTH_TOKEN` is set)
- a health endpoint at `/health`
- a conversation flow: menu browsing → cart → address → order created → admin/business sets a delivery fee → customer gets the total and the business's bank details → customer confirms payment (text or photo) → business marks it paid on the portal
- conversations scoped per (customer phone, business) — the same customer can independently order from multiple businesses without one conversation clobbering the other
- SQLite-backed storage for businesses, menu items, conversations, and orders

## Environment variables to set
- `TWILIO_ACCOUNT_SID` — from the Twilio Console dashboard
- `TWILIO_AUTH_TOKEN` — from the Twilio Console dashboard (keep secret, never commit)
- `TWILIO_WHATSAPP_NUMBER` — the sandbox (or purchased) WhatsApp sender, e.g. `whatsapp:+14155238886`

## Twilio console steps
1. Sign in to the [Twilio Console](https://console.twilio.com).
2. Go to **Messaging → Try it out → Send a WhatsApp message**. This gives you a sandbox number (usually `+1 415 523 8886`) and a join code like `join example-word`.
3. From your own phone's WhatsApp, send that join code as a message to the sandbox number. This links your personal number as an authorized tester — trial accounts can only message numbers that have joined the sandbox this way.
4. Run the app locally and expose it publicly (the sandbox needs a real HTTPS URL, not `localhost`):
   ```bash
   python -m uvicorn app.main:app --reload --port 8000
   ngrok http 8000
   ```
5. Copy the `https://...ngrok...` forwarding URL from ngrok.
6. Back in the Twilio Console sandbox settings, set **"WHEN A MESSAGE COMES IN"** to `https://<your-ngrok-url>/webhook`, method `POST`, and save.
7. Copy your Account SID and Auth Token from the Console dashboard into your local environment (e.g. a `.env` file or shell export) as `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN`, and set `TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886` (use the actual sandbox number Twilio assigned you).
8. From your phone, message the sandbox number "hi" — you should get the category menu back, and can walk the full order flow (pick category → pick item → cart → checkout → address → get a total + bank details → reply with payment confirmation).

## Adding a second (and further) business under the same Twilio account

One Twilio account/subaccount maps to exactly one WhatsApp Business Account (WABA) — you can't have separate WABAs per business under one account. But **within that one WABA you can register multiple phone numbers ("senders")**, so multiple businesses can share a single Twilio account, each with their own distinct number.

1. In the Twilio Console, register a new phone number for WhatsApp under your existing WABA (Twilio can provision a number for you, or you can bring your own). Meta requires ownership verification of that specific number via SMS/voice OTP — quick, not a real barrier.
2. Set that number's "when a message comes in" webhook to the same URL as your first number: `https://collxct.com.ng:8443/webhook` — routing between businesses happens inside the app (`resolve_webhook_business` matches Twilio's `To` field against `Business.whatsapp_number`), not via separate webhook URLs.
3. On the Collxct admin side, create the business with that exact number in `whatsapp_number` (matching the format Twilio sends, e.g. `+234...`).
4. Set the business's bank details in config so the payment flow works.

## Troubleshooting: proactive messages not arriving

Replies inside the webhook (TwiML) and proactive sends (delivery-fee push, mark-paid, dispatch, delivered — all via `send_whatsapp_message()`) are two different mechanisms. Signature verification working and replies arriving doesn't guarantee proactive sends will — those go through the Twilio REST API and need `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` (not just the auth token) plus a valid sender number.

If a customer/business doesn't get a message after setting a delivery fee, marking paid, dispatching, or marking delivered, check the log immediately after:
```bash
docker compose logs recbot --tail=20 | grep send_whatsapp_message
```
- `skipped: missing credentials (account_sid=False ...)` — one of `TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN` isn't set in `.env`. `TWILIO_AUTH_TOKEN` alone being present is enough for signature verification and TwiML replies to work, which is why this can go unnoticed until a proactive send is attempted.
- `failed (to=... from=...): <error>` — credentials are present but Twilio itself rejected the send; the error message names why (bad number format, sandbox restrictions on a number that hasn't joined, etc.)
- No line at all — the code path that calls `send_whatsapp_message()` didn't run; check the request actually reached the route (e.g. `docker compose logs nginx`).

**Meta Business Verification**: per-number ownership OTP is all you need for your first two senders. Adding a **third or later** number requires your Meta Business Portfolio (Collxct's, not each client's) to have completed full Meta Business Verification first — a one-time step for the platform, not something each client business has to individually go through. Budget time for this before onboarding your third business; it typically needs similar documentation to what Paystack's KYC already asked for (Certificate of Incorporation, etc.).

## Suggested production setup
- Use HTTPS for the webhook endpoint (a real domain, not ngrok, once deploying) — done, see `docs/deployment-guide.md`
- Use PostgreSQL instead of SQLite for production — not yet done, still SQLite
- Store secrets in environment variables, never in code — done
- Add error logging and monitoring — not yet done
- Verify the `X-Twilio-Signature` header on incoming webhook requests before trusting the payload — done, see `verify_twilio_signature` in `app/main.py`
- Move from the shared trial sandbox number to an approved WhatsApp Business sender once ready to launch for real
