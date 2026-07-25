# Recbot — roadmap / ideas backlog

Captured product ideas with a feasibility read against the current codebase.

---

## 1. Item images (open the platform to fashion/retail, not just food)

**✅ Shipped (2026-07-24):** owners upload a photo per item (create/edit forms),
images are stored under `/data/media` and served over `/media`, shown as
thumbnails in the admin catalogue, and sent as WhatsApp photo messages when a
customer browses a category (text menu still works as fallback). Wording nudged
from "menu" toward "catalogue". Possible follow-ups: show item thumbnails in the
mobile order view; multiple images per item; image compression.

**Goal:** show a picture per item so clothes, shoes, wigs, etc. sell well over
WhatsApp — visual products need visuals.

**Feasibility: easy–moderate.** `MenuItem.image_url` already exists
(`app/main.py`) but is currently unused. Work needed:

- **Upload + storage:** an admin/owner upload endpoint that saves the image and
  serves it over HTTPS (Collxct already mounts `StaticFiles` and stores receipts,
  so the pattern exists). Public HTTPS URL is required for the next step.
- **Send over WhatsApp:** include the image as a Twilio outbound `media_url`
  when showing an item. (The bot already *receives* media for payment proofs, so
  the Twilio media plumbing is half there.)
- **Show in web + mobile app:** render the image in the admin item list, the
  order/menu views, and the app.
- **Copy/positioning:** the "menu"/"food" wording becomes "catalogue"/"items" so
  it reads for any retailer.

**Effort:** ~1–2 focused sessions. No data migration.

---

## 2. Platform fee per transaction (instead of / alongside subscriptions)

**Goal:** take a small cut of every order payment that covers WhatsApp/messaging
costs plus profit — the Chowdeck / Glovo commission model — so businesses can
join with no subscription.

**Feasibility: moderate–large; a monetization pivot, but well-supported.**

- **How, technically:** move order payments to **Paystack subaccounts + transaction
  splits** under *Collxct's* Paystack account (today each business uses its own
  key, so Collxct isn't in the flow). Create a Paystack **subaccount per business
  from the bank details we already collect** (`bank_name`, `bank_account_number`),
  then charge with a split: a flat + percentage platform fee to Collxct, the rest
  settled to the business subaccount automatically.
- **Nice side effects:** businesses no longer need their own Paystack key
  (simpler onboarding), and settlement to the business is automatic.
- **What it touches:** onboarding (collect/verify settlement bank → create
  subaccount), the order payment link creation, a platform-fee config
  (flat + %), and reporting. Pricing/marketing shifts from subscription to
  commission (note existing onboarding-fee messaging).
- **Risks/compliance:** Collxct becomes a payment facilitator/marketplace —
  Paystack marketplace/split approval, KYC on subaccounts, refund/dispute
  handling, and settlement timing all need thought. Businesses currently on
  bank-transfer (not Paystack) must move to the split model to be monetized.

**Effort:** ~3–5 sessions + a Paystack review/approval step. Can run **alongside**
subscriptions (offer both: "pay-as-you-go commission" vs "flat monthly").

**Suggested sequencing:** do item images first (quick, broadens the market), then
pilot the commission model with a few businesses before making it the default.
