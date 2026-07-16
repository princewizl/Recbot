# Nigeria-Friendly Vendor Onboarding Architecture

## Current state of this repository
This repository currently contains a single FastAPI-based WhatsApp ordering MVP, not a full multi-vendor platform yet.

### What is implemented now
- A single FastAPI app in [app/main.py](app/main.py)
- SQLAlchemy models for:
  - `Business`
  - `Category`
  - `Branch`
  - `MenuItem`
  - `Conversation`
  - `Order`
  - `User` (email, password hash, role, `business_id`)
  - `Plan`
  - `Payment`
- SQLite-backed storage by default via `DATABASE_URL` or the local `bot.db` file
- Signed-cookie session auth (`/login`, `/logout`) with role-based navigation, and an admin CRM covering business creation/configuration, categories, branches, menu items, orders, conversations, business-owner accounts, and subscription plans/payments via Paystack
- A conversation data model and admin views for reviewing conversation state (category selection, branch/location, cart, address, delivery fee, payment), but see below for what's missing on the messaging side

### Update: webhook and Twilio are now implemented
As of the Docker/Twilio deployment work, `/webhook` and `/health` exist and are wired to the full conversation flow (category → item → cart → address → order created, awaiting delivery fee and payment), supporting both a simple JSON contract and Twilio's form-encoded WhatsApp webhook (with signature verification). See `docs/twilio-setup-guide.md` and `docs/deployment-guide.md`. Business routing already works multi-tenant via the `to` WhatsApp number matching `Business.whatsapp_number`, falling back to the first business when absent (see `resolve_webhook_business` in `app/main.py`).

### Update: customer payment is bank-transfer, not Paystack — deliberately
Paystack is used for one thing only: subscription payments from businesses to the platform (`/business/{id}/plans`). Customer-facing order payment does **not** go through Paystack, on purpose: routing customer payments through this app's own Paystack account would mean the app becomes the custodian of that money until it's paid out to the business — settlement/split-payment engineering, and edges uncomfortably close to the kind of payment-aggregation activity a PSSP license covers (the one this app confirmed it does *not* need, back when Paystack's own merchant KYC form asked for it). Bank transfer sidesteps this entirely: money goes directly from customer to business, this app never touches it.

Flow: customer completes items + address → order created immediately (`status=awaiting_delivery_fee`) → admin or the business owner manually enters a delivery fee on the portal (`POST /orders/{id}/delivery-fee`) — deliberately manual rather than geocoded, since free-text WhatsApp addresses are too messy for reliable distance APIs and a human who knows their delivery area is faster and more accurate anyway → customer gets a WhatsApp message with the full total and the business's bank details (`Business.bank_name`/`bank_account_number`/`bank_account_name`, editable in business config) → customer replies with confirmation (text or a photo of their receipt — Twilio media is downloaded and stored under `RECEIPTS_DIR`, in the same persistent volume as `bot.db`) → `status=payment_claimed`, business notified via `owner_notify_number` (finally wiring up fields that existed in the schema but were never connected to anything) → admin/business checks their own bank alert and clicks "Mark paid" on the portal (`POST /orders/{id}/mark-paid`) → `status=paid`.

This is a trust-based system, not a verified one — there's no automatic proof of payment, just the business's own manual check plus whatever the customer sent as evidence. That's a known, accepted risk in this exact market (it's how a large share of informal Nigerian WhatsApp commerce already works), not a flaw unique to this design.

### Update: self-service signup was built, then deliberately removed
A public `/signup` route existed briefly (create `Business` + `User` in one step, log the owner in immediately, land on the plan picker). It was removed because it didn't gate anything on payment — the owner got full working access on `plan_status = "trial"` with nothing stopping them from never paying. The business model calls for charging an onboarding fee up front, which self-service as built didn't support. Business creation is admin-only again (`POST /admin/businesses`), same as before this round of work. If self-service comes back, it needs a payment step (e.g. a Paystack charge) gating account creation/activation, not just an optional plans page afterward.

Two things from that work were kept, since they're correct independent of how onboarding happens:
- **Duplicate `whatsapp_number` rejection** on `POST /admin/businesses` — `resolve_webhook_business`'s `.one_or_none()` lookup would throw if two businesses ever shared a number.
- **Twilio cost-passthrough pricing.** `Plan` prices went from ₦1,500/₦3,500 to ₦7,500 (Starter) / ₦20,000 (Growth), based on Twilio's ~$0.005/message platform fee, an observed ~16-message full order round trip, and assumed monthly order volume per tier. These are rough, order-of-magnitude estimates — not verified against Twilio's Nigeria-specific rate card (not published) or real usage data. Revisit after a month of live billing data. There's no per-message metering or overage billing — a business that runs far more volume than the tier assumes just costs the platform more margin, it isn't charged extra. This is separate from the onboarding fee decision above — it's the recurring subscription price, not a one-time signup charge.

The known unauthenticated-route bug mentioned in an earlier version of this doc (`POST /admin/businesses` and five sibling routes having zero auth checks) has been fixed — see the commit history. Two more turned up the same way while building the pages below: `GET /admin/orders` and `GET /admin/conversations` had no auth check either, exposing every customer's phone number, address, and payment proof text to anyone unauthenticated. Also fixed.

### Update: dedicated order/conversation pages, session staleness handling, polished WhatsApp messages
- `GET /orders/{id}` and `GET /conversations/{id}` — full detail views (item breakdown, payment proof/receipt, related orders) instead of cramped table rows; order actions (set delivery fee, mark paid) now happen through a native `<dialog>` confirmation modal rather than a bare inline form
- `Conversation.updated_at` now actually refreshes on every message (previously set once at creation despite views sorting by it); a conversation idle 24h+ in a pre-order browsing stage resets to a fresh greeting rather than resuming with potentially stale menu item numbers — never applies to a conversation with a real pending order awaiting payment
- Conversations are scoped per `(phone_number, business_id)` instead of globally per phone — a customer can now order from multiple businesses independently without one conversation silently wiping the other. Required a real SQLite migration (table rebuild) since the constraint changed, handled automatically in `ensure_schema()`
- `send_whatsapp_message` sends from the specific business's own number now, not one hardcoded env var — needed once more than one business shares the Twilio account
- WhatsApp messages show item descriptions, use WhatsApp-native `*bold*`/`_italic_` formatting, and carry a "Powered by Collxct" footer on the four key touchpoints (greeting, order-created, payment-info push, payment-confirmed)
- One gap closed: the customer previously never got notified when the business actually marked their order paid — the conversation just went silent after payment was claimed

### What is still not implemented
- A dedicated `Vendor` entity distinct from `Business` — today a business owner is just a `User` row with `role='business_owner'` and a `business_id` foreign key, not a separate vendor table
- **A one-time onboarding fee.** There's no payment-gated account creation anywhere yet — `POST /admin/businesses` just creates the row. If the plan is "admin creates the business after the owner pays," that payment currently has to happen entirely outside the app (bank transfer, manual Paystack link, whatever) with the admin creating the account as the confirmation step.
- **Automatic payment verification.** "Mark paid" is a manual click after a human checks their own bank alert — there's no bank/webhook integration confirming the transfer actually happened. Dispute risk is real (customer claims paid, business claims not received) and currently has no resolution mechanism beyond whatever proof (text/photo) the customer sent.
- **Shared-number multi-tenancy.** Routing still works by matching Twilio's `to` field against `Business.whatsapp_number` — meaning each onboarded business needs its *own* distinct WhatsApp-connected number for the bot to route to them correctly, which they set up with their own name/logo directly through Meta's WhatsApp Business Profile. There's no keyword/code-based scheme for many businesses to share one Twilio number, which would be needed if you wanted businesses to skip getting their own WhatsApp Business API access.
- Per-message usage metering or overage billing (see the pricing note above — currently a flat-rate bet, not measured)
- A production-grade PostgreSQL deployment setup

## Proposed architecture for future expansion
If you want to support multiple vendors/businesses in Nigeria, the most practical next step is to keep one shared backend and add vendor/business separation inside the database.

### Suggested architecture
- One shared FastAPI backend
- One public HTTPS webhook endpoint
- One messaging integration layer (Twilio or Meta WhatsApp Business API)
- One database for all vendors/businesses
- Per-business menu and order records

### Recommended data model extension
The current code already includes a `Business` model. For a vendor platform, the next logical step is to add:
- a `Vendor` entity for onboarding and account management
- a `Business` entity linked to a vendor
- per-business menu items and order records

## Recommended rollout plan
1. Deploy one shared backend.
2. Create a business/vendor onboarding form.
3. Link each business to its own menu and WhatsApp number.
4. Keep the ordering flow the same but route conversations by business ID.
5. Later add vendor dashboards, order notifications, and payments.

## Nigeria-friendly recommendation
For a first rollout in Nigeria, use:
- one shared backend
- one messaging provider
- one hosting environment
- multiple businesses onboarded as separate profiles under the same platform

This is more practical than deploying a separate bot per business at the start.
