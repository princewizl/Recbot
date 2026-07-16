# WhatsApp Ordering Bot MVP

This workspace contains a working MVP implementation of the plan from the Word document.

## What is included
- FastAPI webhook endpoint at `/webhook`
- SQLite-backed order and conversation storage
- Menu-driven ordering flow with address collection and order confirmation
- Category-based browsing for large menus
- Optional branch/location selection for businesses with multiple locations
- Menu item availability controls so businesses can mark items active/inactive or out of stock
- Admin web UI at `/admin/` to create businesses, manage categories/branches/items, and review orders and conversations
- Business configuration page at `/business/{business_id}/config` for business-level setup
- Basic health check at `/health`
- Automated tests for the end-to-end flow

## Run locally
```bash
python -m uvicorn app.main:app --reload --port 8000
```

## Test
```bash
python -m pytest -q
```

## Example webhook payload
```json
{
  "from": "2348012345678",
  "message": "hi"
}
```
