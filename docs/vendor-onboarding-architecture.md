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
- A conversation data model and admin views for reviewing conversation state (category selection, branch/location, cart, address, order confirmation), but see below for what's missing on the messaging side

### Update: webhook and Twilio are now implemented
As of the Docker/Twilio deployment work, `/webhook` and `/health` exist and are wired to the full conversation flow (category → item → cart → address → confirm), supporting both a simple JSON contract and Twilio's form-encoded WhatsApp webhook (with signature verification). See `docs/twilio-setup-guide.md` and `docs/deployment-guide.md`. Business routing already works multi-tenant via the `to` WhatsApp number matching `Business.whatsapp_number`, falling back to the first business when absent (see `resolve_webhook_business` in `app/main.py`).

### Update: self-service signup and Twilio cost passthrough are now implemented
`/signup` (public GET+POST) lets a business owner create their own `Business` + `User` account in one step and lands on the plan picker immediately — `/register` is still admin-only (for admins onboarding owners manually), but it's no longer the only path. Both `/signup` and admin `create_business` now reject a `whatsapp_number` that's already registered to another business, since `resolve_webhook_business`'s `.one_or_none()` lookup would throw on a collision.

Twilio's per-message cost is passed through by baking it into the subscription price rather than metering usage per business: `Plan` prices went from ₦1,500/₦3,500 to ₦7,500 (Starter) / ₦20,000 (Growth), based on Twilio's ~$0.005/message platform fee, an observed ~16-message full order round trip, and assumed monthly order volume per tier. These are rough, order-of-magnitude estimates — not verified against Twilio's Nigeria-specific rate card (not published) or real usage data. Revisit after a month of live billing data. There's no per-message metering or overage billing — a business that runs far more volume than the tier assumes just costs the platform more margin, it isn't charged extra.

The known unauthenticated-route bug mentioned in an earlier version of this doc (`POST /admin/businesses` and five sibling routes having zero auth checks) has been fixed — see the commit history.

### What is still not implemented
- A dedicated `Vendor` entity distinct from `Business` — today a business owner is just a `User` row with `role='business_owner'` and a `business_id` foreign key, not a separate vendor table
- **Shared-number multi-tenancy.** Routing still works by matching Twilio's `to` field against `Business.whatsapp_number` — meaning each self-registered business needs its *own* distinct WhatsApp-connected number for the bot to route to them correctly. There's no keyword/code-based scheme for many businesses to share one Twilio number, which would be needed for truly lightweight onboarding (getting a business its own approved WhatsApp Business sender is a real barrier, not something this app can shortcut).
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
