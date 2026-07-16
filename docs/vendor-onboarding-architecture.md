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

### What is not implemented yet
- The actual inbound WhatsApp webhook: there is currently **no `/webhook` and no `/health` route** in `app/main.py`. The conversation-flow logic and models exist, but nothing wires an incoming message to them — this needs to be rebuilt or reconnected.
- Twilio or Meta WhatsApp API integration for real outbound messaging
- A dedicated `Vendor` entity distinct from `Business` — today a business owner is just a `User` row with `role='business_owner'` and a `business_id` foreign key, not a separate vendor table
- A full multi-tenant onboarding workflow beyond the current admin-driven business/owner creation
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
