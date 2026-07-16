# Twilio Setup Guide for This App

## Current status
`/webhook` now handles both payload shapes on the same endpoint:
- The simple JSON contract (`{"from": ..., "message": ...}`) used by the test suite and for manual/local testing, replying with `{"reply": ...}`.
- Twilio's form-encoded WhatsApp webhook (`From`, `To`, `Body`), replying with TwiML XML so Twilio delivers the response inline — no separate outbound API call needed for replies.

The `twilio` SDK is installed and a `send_whatsapp_message(to_number, body)` helper (in `app/main.py`) is available for proactive/outbound sends (e.g. order-status pushes) outside the reply-to-incoming-message flow. It's a no-op (returns `False`) until the env vars below are set.

## What the current app already does
- a webhook endpoint at `/webhook` (JSON and Twilio form-encoded)
- a health endpoint at `/health`
- a conversation flow for menu browsing, cart building, address collection, and order confirmation
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
8. From your phone, message the sandbox number "hi" — you should get the category menu back, and can walk the full order flow (pick category → pick item → cart → checkout → address → confirm).

## Suggested production setup
- Use HTTPS for the webhook endpoint (a real domain, not ngrok, once deploying)
- Use PostgreSQL instead of SQLite for production
- Store secrets in environment variables, never in code
- Add error logging and monitoring
- Verify the `X-Twilio-Signature` header on incoming webhook requests before trusting the payload (not yet implemented — worth adding before going live with real customer traffic)
- Move from the shared trial sandbox number to an approved WhatsApp Business sender once ready to launch for real
