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

### What is still not implemented
- A dedicated `Vendor` entity distinct from `Business` — today a business owner is just a `User` row with `role='business_owner'` and a `business_id` foreign key, not a separate vendor table
- **Self-service business registration.** Every path that creates a `Business` or a `business_owner` `User` is admin-only today: `/register` (creates the owner login) explicitly checks `current_user.role != "admin"`, and business creation only happens through the admin CRM. There is no public "sign up your business" form.
- **Known bug found while auditing this:** `POST /admin/businesses` (the route that actually creates a `Business` row) has **no authentication check at all** — unlike every other admin route in the file. Right now, anyone who can reach that endpoint can create a business, unauthenticated. Worth fixing before relying on admin-gating as a security boundary.
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
