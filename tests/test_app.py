import base64
import os
import importlib

from fastapi.testclient import TestClient

# 1x1 red PNG used to exercise image upload.
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_category_selection_flow(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    response = client.post(
        "/webhook",
        json={"from": "2348012345678", "message": "hi"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "category" in payload["reply"].lower()

    response = client.post(
        "/webhook",
        json={"from": "2348012345678", "message": "1"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "jollof rice" in payload["reply"].lower()


def test_admin_dashboard_and_business_creation(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    # Unauthenticated visitors must be bounced to login, not shown the dashboard.
    response = client.get("/admin/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"

    login_response = client.post(
        "/login",
        data={"email": "admin@example.com", "password": "test-admin-password"},
        follow_redirects=False,
    )
    assert login_response.status_code == 303

    response = client.get("/admin/")
    assert response.status_code == 200
    assert "Admin Dashboard" in response.text

    response = client.post(
        "/admin/businesses",
        data={"name": "Mama Food", "whatsapp_number": "+2348000000000", "owner_notify_number": "+2348000000001"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    list_response = client.get("/admin/businesses")
    assert list_response.status_code == 200
    assert "Mama Food" in list_response.text


def test_menu_item_descriptions_show_in_admin_and_conversations(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    login_response = client.post(
        "/login",
        data={"email": "admin@example.com", "password": "test-admin-password"},
        follow_redirects=False,
    )
    assert login_response.status_code == 303

    create_business = client.post(
        "/admin/businesses",
        data={"name": "Test Kitchen", "whatsapp_number": "+2348000000000", "owner_notify_number": "+2348000000001"},
        follow_redirects=False,
    )
    assert create_business.status_code == 303
    business_id = int(create_business.headers["location"].split("/")[-1])

    create_item = client.post(
        f"/admin/businesses/{business_id}/items",
        data={"name": "Burger", "price": "1200", "description": "Crispy grilled burger with cheddar", "is_active": "on"},
        follow_redirects=False,
    )
    assert create_item.status_code == 303

    admin_page = client.get(f"/admin/businesses/{business_id}")
    assert admin_page.status_code == 200
    assert "Crispy grilled burger with cheddar" in admin_page.text

    db = main.SessionLocal()
    db.add(main.Conversation(phone_number="2348123456789", business_id=business_id, stage="new", cart_json='[{"name": "Burger", "description": "Crispy grilled burger with cheddar"}]'))
    db.commit()
    db.close()

    conversation_page = client.get("/admin/conversations")
    assert conversation_page.status_code == 200
    assert "Crispy grilled burger with cheddar" in conversation_page.text


def test_action_required_alerts_for_new_order(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    # Walk the seeded demo shop's flow: greet, pick category, pick item, checkout.
    phone = "2348012345678"
    client.post("/webhook", json={"from": phone, "message": "hi"})
    client.post("/webhook", json={"from": phone, "message": "1"})
    client.post("/webhook", json={"from": phone, "message": "1"})
    client.post("/webhook", json={"from": phone, "message": "checkout"})
    client.post("/webhook", json={"from": phone, "message": "Ada"})
    response = client.post("/webhook", json={"from": phone, "message": "12 Marina Road, Lagos"})
    assert "delivery fee" in response.json()["reply"].lower()

    # The alert API requires a staff login.
    unauthenticated = client.get("/api/action-required")
    assert unauthenticated.status_code == 401

    login_response = client.post(
        "/login",
        data={"email": "admin@example.com", "password": "test-admin-password"},
        follow_redirects=False,
    )
    assert login_response.status_code == 303

    payload = client.get("/api/action-required").json()
    assert payload["count"] == 1
    order = payload["orders"][0]
    assert order["status"] == "awaiting_delivery_fee"
    assert order["action"] == "Set delivery fee"
    assert order["customer"] == "Ada"

    # Setting the delivery fee resolves the alert.
    fee_response = client.post(
        f"/orders/{order['id']}/delivery-fee",
        data={"delivery_fee": "500", "accept_terms": "1"},
        follow_redirects=False,
    )
    assert fee_response.status_code == 303
    payload = client.get("/api/action-required").json()
    assert payload["count"] == 0


def test_bot_respects_business_hours(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    # Close the seeded demo shop: local "now" is outside a window starting in 1h.
    db = main.SessionLocal()
    business = db.query(main.Business).first()
    local_now = main.business_local_now(business)
    business.open_time = (local_now + main.timedelta(hours=1)).strftime("%H:%M")
    business.close_time = (local_now + main.timedelta(hours=2)).strftime("%H:%M")
    db.commit()
    db.close()

    phone = "2348012340000"
    reply = client.post("/webhook", json={"from": phone, "message": "hi"}).json()["reply"]
    assert "closed" in reply.lower()
    assert "category" not in reply.lower()

    # Status checks still work while closed.
    reply = client.post("/webhook", json={"from": phone, "message": "status"}).json()["reply"]
    assert "closed" not in reply.lower()

    # Reopen (24/7) and ordering resumes.
    db = main.SessionLocal()
    business = db.query(main.Business).first()
    business.open_time = None
    business.close_time = None
    db.commit()
    db.close()
    reply = client.post("/webhook", json={"from": phone, "message": "hi"}).json()["reply"]
    assert "category" in reply.lower()


def test_single_branch_plan_limit_for_owners(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    client.post("/login", data={"email": "admin@example.com", "password": "test-admin-password"}, follow_redirects=False)
    create_business = client.post(
        "/admin/businesses",
        data={"name": "Solo Kitchen", "whatsapp_number": "+2348000000002"},
        follow_redirects=False,
    )
    business_id = int(create_business.headers["location"].split("/")[-1])
    client.post("/register", data={"email": "owner@example.com", "password": "owner-pass", "business_id": str(business_id)}, follow_redirects=False)
    client.get("/logout")

    client.post("/login", data={"email": "owner@example.com", "password": "owner-pass"}, follow_redirects=False)
    first = client.post(f"/admin/businesses/{business_id}/branches", data={"name": "Main"}, follow_redirects=False)
    assert first.status_code == 303
    assert "notice" not in first.headers["location"]
    second = client.post(f"/admin/businesses/{business_id}/branches", data={"name": "Annex"}, follow_redirects=False)
    assert second.status_code == 303
    assert "notice=branch_limit" in second.headers["location"]


def test_totp_two_factor_login_flow(tmp_path, monkeypatch):
    import time as time_module

    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    # Enable 2FA directly on the seeded admin.
    secret = main.generate_totp_secret()
    db = main.SessionLocal()
    admin = db.query(main.User).filter(main.User.email == "admin@example.com").one()
    admin.totp_secret = secret
    admin.totp_enabled = 1
    db.commit()
    db.close()

    # Password alone must not grant a session — it redirects to the verify step.
    response = client.post(
        "/login",
        data={"email": "admin@example.com", "password": "test-admin-password"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/login/verify"
    assert client.get("/admin/", follow_redirects=False).status_code == 303  # still logged out

    # A wrong code bounces back to the verify page.
    response = client.post("/login/verify", data={"code": "000000"}, follow_redirects=False)
    assert response.headers["location"] == "/login/verify"

    # The correct TOTP code completes the sign-in.
    code = main._totp_code(secret, int(time_module.time()) // 30)
    response = client.post("/login/verify", data={"code": code}, follow_redirects=False)
    assert response.headers["location"] == "/admin/"
    assert client.get("/admin/").status_code == 200


def test_auto_delivery_fee_and_paystack_flow(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    # Configure the demo shop: Paystack + auto delivery fee, pickup located.
    db = main.SessionLocal()
    business = db.query(main.Business).first()
    business.payment_method = "paystack"
    business.paystack_secret_key = "sk_test_x"
    business.delivery_autocalc = 1
    business.delivery_base_fee = 1000
    business.delivery_per_km = 200
    business.geo_lat = 6.45
    business.geo_lng = 3.40
    db.commit()
    db.close()

    # ~2.2 km away; no real network calls in tests.
    monkeypatch.setattr(main, "geocode_address", lambda address: (6.47, 3.40))
    monkeypatch.setattr(main, "osrm_route_km", lambda *a: None)  # force the haversine fallback path

    def fake_link(db, business, order):
        order.payment_reference = f"RBORD-{order.id}-test"
        order.payment_link = "https://checkout.paystack.com/test123"
        return order.payment_link

    monkeypatch.setattr(main, "create_paystack_order_link", fake_link)

    phone = "2348011111111"
    client.post("/webhook", json={"from": phone, "message": "hi"})
    client.post("/webhook", json={"from": phone, "message": "1"})
    client.post("/webhook", json={"from": phone, "message": "1"})
    client.post("/webhook", json={"from": phone, "message": "checkout"})
    client.post("/webhook", json={"from": phone, "message": "Ada"})
    reply = client.post("/webhook", json={"from": phone, "message": "12 Marina Road, Lagos"}).json()["reply"]

    # Fee auto-calculated (base 1000 + ceil(2.2km) * 200 = 1600, rounded to N50)
    # and the payment link sent immediately — no owner action needed.
    assert "checkout.paystack.com" in reply
    assert "Delivery (2.2 km)" in reply

    db = main.SessionLocal()
    order = db.query(main.Order).first()
    assert order.status == "awaiting_payment"
    assert order.delivery_fee == 1600
    db.close()

    # Customer says "paid": Paystack verification confirms automatically.
    monkeypatch.setattr(main, "verify_paystack_order_payment", lambda business, order: True)
    reply = client.post("/webhook", json={"from": phone, "message": "paid"}).json()["reply"]
    assert "Payment confirmed" in reply
    db = main.SessionLocal()
    assert db.query(main.Order).first().status == "paid"
    db.close()

    # Nothing ever entered the action queue.
    client.post("/login", data={"email": "admin@example.com", "password": "test-admin-password"}, follow_redirects=False)
    assert client.get("/api/action-required").json()["count"] == 0


def test_annual_prepay_extends_expiry_a_year(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.delenv("PAYSTACK_SECRET_KEY", raising=False)

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    client.post("/login", data={"email": "admin@example.com", "password": "test-admin-password"}, follow_redirects=False)
    purchase = client.post(
        "/business/1/purchase-plan",
        data={"plan_id": "2", "billing_cycle": "annual", "auto_renew": "1"},
        follow_redirects=False,
    )
    assert purchase.status_code == 303
    simulate_url = purchase.headers["location"]
    assert simulate_url.startswith("/paystack/simulate")
    client.get(simulate_url)

    db = main.SessionLocal()
    business = db.query(main.Business).filter(main.Business.id == 1).one()
    payment = db.query(main.Payment).order_by(main.Payment.id.desc()).first()
    growth = db.query(main.Plan).filter(main.Plan.id == 2).one()
    assert payment.billing_cycle == "annual"
    assert payment.amount == growth.price_ngn * 10
    days = (business.plan_expiry - main.datetime.utcnow()).days
    assert 360 <= days <= 366
    db.close()


def test_landing_page_and_contact_form(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    page = client.get("/")
    assert page.status_code == 200
    for needle in ["ordering machine", "Pay only when you sell", "per order", "processed securely by Paystack", "What we need to onboard you", "Request my setup", "logo-white.svg"]:
        assert needle in page.text, f"missing: {needle}"

    # No APK on disk in tests → the button is hidden and the route shows "coming soon".
    assert "Get the Android app" not in page.text
    soon = client.get("/download/android")
    assert soon.status_code == 200 and "coming soon" in soon.text.lower()

    # Contact form stores the lead (SMTP unconfigured -> sent=0 notice).
    response = client.post(
        "/contact",
        data={"name": "Bola", "phone": "+2348012345678", "message": "I run a suya spot in Yaba", "business_name": "Bola Suya"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "sent=0" in response.headers["location"]
    db = main.SessionLocal()
    lead = db.query(main.ContactMessage).one()
    assert lead.name == "Bola" and lead.emailed == 0
    db.close()

    # Honeypot submissions are dropped silently.
    client.post(
        "/contact",
        data={"name": "Bot", "phone": "1", "message": "spam", "website": "http://spam.example"},
        follow_redirects=False,
    )
    db = main.SessionLocal()
    assert db.query(main.ContactMessage).count() == 1
    db.close()


def test_login_rate_limiting(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    for _ in range(5):
        response = client.post("/login", data={"email": "admin@example.com", "password": "wrong"}, follow_redirects=False)
        assert response.status_code == 303
    locked = client.post("/login", data={"email": "admin@example.com", "password": "test-admin-password"}, follow_redirects=False)
    assert locked.status_code == 200
    assert "Too many login attempts" in locked.text


def _place_demo_order(client):
    """Drive the seeded demo shop to an order waiting on the business."""
    phone = "2348012345678"
    client.post("/webhook", json={"from": phone, "message": "hi"})
    client.post("/webhook", json={"from": phone, "message": "1"})
    client.post("/webhook", json={"from": phone, "message": "1"})
    client.post("/webhook", json={"from": phone, "message": "checkout"})
    client.post("/webhook", json={"from": phone, "message": "Ada"})
    client.post("/webhook", json={"from": phone, "message": "12 Marina Road, Lagos"})


def test_mobile_api_login_and_order_lifecycle(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    _place_demo_order(client)

    # Wrong password is rejected with a JSON error, not a redirect.
    bad = client.post("/api/login", json={"email": "admin@example.com", "password": "nope"})
    assert bad.status_code == 401
    assert bad.json()["error"] == "invalid_credentials"

    # Correct login hands back a bearer token.
    login = client.post("/api/login", json={"email": "admin@example.com", "password": "test-admin-password"})
    assert login.status_code == 200
    token = login.json()["token"]
    assert token
    assert login.json()["user"]["role"] == "admin"

    # No token -> unauthorized; the token authenticates just like the cookie.
    assert client.get("/api/orders").status_code == 401
    auth = {"Authorization": f"Bearer {token}"}

    action_required = client.get("/api/action-required", headers=auth).json()
    assert action_required["count"] == 1
    order_id = action_required["orders"][0]["id"]

    detail = client.get(f"/api/orders/{order_id}", headers=auth).json()
    assert detail["status"] == "awaiting_delivery_fee"
    assert detail["available_actions"] == ["set_delivery_fee"]
    assert detail["items"] and detail["items"][0]["qty"] >= 1

    # Walk the order all the way through the fulfilment actions.
    fee = client.post(
        f"/api/orders/{order_id}/action",
        headers=auth,
        json={"action": "set_delivery_fee", "delivery_fee": 500},
    ).json()
    assert fee["status"] == "awaiting_payment"
    assert fee["delivery_fee"] == 500
    assert fee["available_actions"] == ["mark_paid"]

    # Setting the fee clears the action-required queue.
    assert client.get("/api/action-required", headers=auth).json()["count"] == 0

    paid = client.post(f"/api/orders/{order_id}/action", headers=auth, json={"action": "mark_paid"}).json()
    assert paid["status"] == "paid"
    # Refund rides alongside the status action once the money has been taken.
    assert paid["available_actions"] == ["dispatch", "refund"]

    dispatched = client.post(f"/api/orders/{order_id}/action", headers=auth, json={"action": "dispatch"}).json()
    assert dispatched["status"] == "out_for_delivery"
    assert dispatched["available_actions"] == ["mark_delivered", "refund"]

    delivered = client.post(f"/api/orders/{order_id}/action", headers=auth, json={"action": "mark_delivered"}).json()
    assert delivered["status"] == "delivered"
    # Delivered is not the end of the line: a refund is still possible, which is
    # the usual case (goods wrong, missing, or unacceptable on arrival).
    assert delivered["available_actions"] == ["refund"]

    # A fee action needs a fee; unknown actions are rejected.
    assert client.post(f"/api/orders/{order_id}/action", headers=auth, json={"action": "teleport"}).status_code == 400


def test_mobile_api_device_registration(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    # Registration requires auth.
    assert client.post("/api/devices", json={"token": "abc"}).status_code == 401

    token = client.post("/api/login", json={"email": "admin@example.com", "password": "test-admin-password"}).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}

    assert client.post("/api/devices", json={"token": "fcm-token-123"}, headers=auth).json()["ok"] is True

    db = main.SessionLocal()
    assert db.query(main.DeviceToken).filter(main.DeviceToken.token == "fcm-token-123").count() == 1
    db.close()

    # Re-registering the same token is idempotent (upsert, not a duplicate row).
    client.post("/api/devices", json={"token": "fcm-token-123"}, headers=auth)
    db = main.SessionLocal()
    assert db.query(main.DeviceToken).count() == 1
    db.close()

    # Unregister removes it.
    client.request("DELETE", "/api/devices", json={"token": "fcm-token-123"}, headers=auth)
    db = main.SessionLocal()
    assert db.query(main.DeviceToken).count() == 0
    db.close()


def test_push_to_business_is_noop_without_credentials(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.delenv("FCM_CREDENTIALS_FILE", raising=False)

    import app.main as main
    importlib.reload(main)

    # With no FCM credentials configured, pushing must be a safe no-op.
    assert main.push_to_business(1, "hi", "there") == 0


def test_legal_pages_render(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    for path, needle in [("/terms", "Terms of Use"), ("/privacy", "Privacy Policy"),
                         ("/refunds", "Refund Policy")]:
        r = client.get(path)
        assert r.status_code == 200
        assert needle in r.text

    # The refund policy must say who actually sends the money, since Collxct
    # never holds it — a customer reading otherwise would chase the wrong party.
    refunds = client.get("/refunds").text
    assert "the business sends your refund" in refunds.lower()
    assert "/terms" in refunds


def test_password_reset_flow(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    db = main.SessionLocal()
    db.add(main.User(email="owner@example.com", password_hash=main.hash_password("old-pass"), role="business_owner"))
    db.commit()
    token = main.create_reset_token(main.get_user_by_email(db, "owner@example.com"))
    db.close()

    # Valid token shows the reset form.
    page = client.get(f"/reset-password?token={token}")
    assert page.status_code == 200 and "New password" in page.text

    # Setting a new password succeeds.
    done = client.post("/reset-password", data={"token": token, "password": "brand-new-pass", "confirm": "brand-new-pass"})
    assert done.status_code == 200 and "Password updated" in done.text

    # The token is single-use: changing the password invalidates it.
    assert "Link expired" in client.get(f"/reset-password?token={token}").text

    # The new password works.
    assert client.post("/api/login", json={"email": "owner@example.com", "password": "brand-new-pass"}).status_code == 200

    # forgot-password never reveals whether an email exists.
    assert client.post("/api/forgot-password", json={"email": "nobody@example.com"}).json()["ok"] is True
    assert client.post("/api/forgot-password", json={"email": "owner@example.com"}).json()["ok"] is True


def test_item_image_upload_serve_and_catalogue(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)
    client.post("/login", data={"email": "admin@example.com", "password": "test-admin-password"}, follow_redirects=False)
    biz = client.post(
        "/admin/businesses",
        data={"name": "Fashion House", "whatsapp_number": "+2348000000000"},
        follow_redirects=False,
    )
    business_id = int(biz.headers["location"].split("/")[-1])

    # Upload an item with a photo.
    created = client.post(
        f"/admin/businesses/{business_id}/items",
        data={"name": "Red Dress", "price": "15000", "is_active": "on"},
        files={"image": ("dress.png", _TINY_PNG, "image/png")},
        follow_redirects=False,
    )
    assert created.status_code == 303

    db = main.SessionLocal()
    item = db.query(main.MenuItem).filter(main.MenuItem.business_id == business_id).first()
    image_url = item.image_url
    business = main.get_business(db, business_id)
    items = db.query(main.MenuItem).filter(main.MenuItem.business_id == business_id).all()
    db.close()
    assert image_url and image_url.startswith("/media/")

    # The image is served publicly.
    served = client.get(image_url)
    assert served.status_code == 200 and served.headers["content-type"].startswith("image/")

    # Sending catalogue images is a safe no-op without Twilio configured.
    main.send_item_catalogue_images(business, "2348011112222", items)

    # A non-image upload is rejected (no image_url stored).
    client.post(
        f"/admin/businesses/{business_id}/items",
        data={"name": "No Pic", "price": "100", "is_active": "on"},
        files={"image": ("notes.txt", b"hello", "text/plain")},
        follow_redirects=False,
    )
    db = main.SessionLocal()
    nopic = db.query(main.MenuItem).filter(main.MenuItem.name == "No Pic").first()
    assert nopic.image_url is None
    db.close()


def test_message_count_and_platform_charge(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    phone = "2348012345678"
    for msg in ["hi", "1", "1", "checkout", "Ada", "12 Marina Road, Lagos"]:
        client.post("/webhook", json={"from": phone, "message": msg})

    db = main.SessionLocal()
    order = db.query(main.Order).order_by(main.Order.id.desc()).first()
    mc = order.message_count
    total = order.total
    charge = main.order_platform_charge(order)
    conv = db.query(main.Conversation).filter(main.Conversation.phone_number == phone).first()
    conv_count = conv.message_count
    db.close()

    # The browse + checkout round-trips were tallied onto the order.
    assert mc >= 10
    # Charge = flat service buffer + commission % of the order + per-message recovery.
    expected = main.PLATFORM_SERVICE_CHARGE_NGN + round(total * main.PLATFORM_COMMISSION_PERCENT / 100) + \
        main.PLATFORM_PER_MESSAGE_NGN * min(mc, main.PLATFORM_MAX_BILLED_MESSAGES)
    assert charge == expected
    # The conversation counter reset when the order was placed (fresh for next).
    assert conv_count < mc

    # A very long chat is billed only up to the message cap.
    db = main.SessionLocal()
    o = db.query(main.Order).order_by(main.Order.id.desc()).first()
    o.message_count = 999
    db.commit()
    capped = main.order_platform_charge(o)
    db.close()
    assert capped == main.PLATFORM_SERVICE_CHARGE_NGN + round(total * main.PLATFORM_COMMISSION_PERCENT / 100) + \
        main.PLATFORM_PER_MESSAGE_NGN * main.PLATFORM_MAX_BILLED_MESSAGES


def test_cancel_order(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    _place_demo_order(client)
    token = client.post("/api/login", json={"email": "admin@example.com", "password": "test-admin-password"}).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}

    order = client.get("/api/orders?scope=active", headers=auth).json()["orders"][0]
    assert order["can_cancel"] is True

    cancelled = client.post(f"/api/orders/{order['id']}/action", headers=auth, json={"action": "cancel"})
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["can_cancel"] is False

    # It drops out of the active list.
    active = client.get("/api/orders?scope=active", headers=auth).json()["orders"]
    assert not any(o["id"] == order["id"] for o in active)


def test_see_and_remove_cart_commands(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    phone = "2348012345678"
    client.post("/webhook", json={"from": phone, "message": "hi"})
    client.post("/webhook", json={"from": phone, "message": "1"})  # open a category

    # "see 1" previews the item without adding it to the cart.
    seen = client.post("/webhook", json={"from": phone, "message": "see 1"}).json()["reply"].lower()
    assert "add it to your cart" in seen
    empty = client.post("/webhook", json={"from": phone, "message": "cart"}).json()["reply"].lower()
    assert "empty" in empty

    # Add an item, then the cart shows numbered lines with a remove hint.
    client.post("/webhook", json={"from": phone, "message": "1"})
    cart = client.post("/webhook", json={"from": phone, "message": "cart"}).json()["reply"].lower()
    assert "remove 1" in cart

    # "remove 1" empties the cart.
    removed = client.post("/webhook", json={"from": phone, "message": "remove 1"}).json()["reply"].lower()
    assert "removed" in removed and "empty" in removed


def test_catalogue_and_business_config_api(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import app.main as main
    importlib.reload(main)

    db = main.SessionLocal()
    business_id = db.query(main.Business).first().id
    db.add(main.User(email="owner@example.com", password_hash=main.hash_password("pw"),
                     role="business_owner", business_id=business_id))
    db.commit()
    db.close()

    client = TestClient(main.app)
    token = client.post("/api/login", json={"email": "owner@example.com", "password": "pw"}).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}

    # Create a category and an item with a photo (multipart).
    cat = client.post("/api/categories", json={"name": "Dresses"}, headers=auth).json()
    created = client.post(
        "/api/items",
        data={"name": "Red Dress", "price": "15000", "category_id": str(cat["id"]), "is_active": "1", "is_out_of_stock": "0"},
        files={"image": ("d.png", _TINY_PNG, "image/png")},
        headers=auth,
    )
    assert created.status_code == 200
    item = created.json()
    assert item["name"] == "Red Dress" and item["price"] == 15000 and item["image_url"]
    item_id = item["id"]

    # Catalogue lists the category and item.
    catalogue = client.get("/api/catalogue", headers=auth).json()
    assert any(c["name"] == "Dresses" for c in catalogue["categories"])
    assert any(i["id"] == item_id for i in catalogue["items"])

    # Quick out-of-stock toggle.
    assert client.post(f"/api/items/{item_id}/stock", json={"is_out_of_stock": True}, headers=auth).json()["is_out_of_stock"] is True

    # Update without a new image keeps the old photo.
    upd = client.post(f"/api/items/{item_id}", data={"name": "Blue Dress", "price": "16000", "is_active": "1", "is_out_of_stock": "0"}, headers=auth)
    assert upd.status_code == 200 and upd.json()["name"] == "Blue Dress" and upd.json()["image_url"]

    # Delete removes it.
    assert client.request("DELETE", f"/api/items/{item_id}", headers=auth).json()["ok"] is True
    assert not any(i["id"] == item_id for i in client.get("/api/catalogue", headers=auth).json()["items"])

    # Dashboard stats.
    stats = client.get("/api/stats", headers=auth).json()
    for key in ("business_name", "accepting_orders", "needs_action", "active_orders", "orders_today", "revenue_today", "item_count"):
        assert key in stats

    # Business config round-trips.
    assert "whatsapp_number" in client.get("/api/business/config", headers=auth).json()
    saved = client.post("/api/business/config", json={"name": "My Shop", "bank_code": "058", "open_time": "09:00", "close_time": "18:00"}, headers=auth)
    assert saved.status_code == 200
    got = client.get("/api/business/config", headers=auth).json()
    assert got["name"] == "My Shop" and got["bank_code"] == "058" and got["open_time"] == "09:00"


def test_commission_model_no_gating_and_bank_code(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    db = main.SessionLocal()
    business = db.query(main.Business).first()
    bid = business.id
    business.plan_expiry = main.datetime.utcnow() - main.timedelta(days=400)
    db.commit()
    # Commission-only: an expired plan never blocks ordering.
    assert main.plan_is_blocked(business) is False
    # Subaccount creation is a safe no-op when central Paystack isn't configured.
    assert main.ensure_paystack_subaccount(business) is None
    db.close()

    assert "category" in client.post("/webhook", json={"from": "2348012345678", "message": "hi"}).json()["reply"].lower()

    # Admin saves the payout bank code used for the Paystack subaccount split.
    client.post("/login", data={"email": "admin@example.com", "password": "test-admin-password"}, follow_redirects=False)
    r = client.post(
        f"/admin/businesses/{bid}",
        data={"name": "Demo Shop", "whatsapp_number": "+2348000000000", "bank_code": "058", "bank_account_number": "0123456789"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    db = main.SessionLocal()
    assert main.get_business(db, bid).bank_code == "058"
    db.close()


def test_paused_business_blocks_new_orders(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    # Open by default: greeting shows the menu.
    assert "category" in client.post("/webhook", json={"from": "2348012345678", "message": "hi"}).json()["reply"].lower()

    # Pause the business.
    db = main.SessionLocal()
    for b in db.query(main.Business).all():
        b.accepting_orders = 0
    db.commit()
    db.close()

    # A new customer is turned away with the paused message.
    reply = client.post("/webhook", json={"from": "2348019998888", "message": "hi"}).json()["reply"].lower()
    assert "paused" in reply

    # Resume: ordering works again.
    db = main.SessionLocal()
    for b in db.query(main.Business).all():
        b.accepting_orders = 1
    db.commit()
    db.close()
    assert "category" in client.post("/webhook", json={"from": "2348017776666", "message": "hi"}).json()["reply"].lower()


def test_open_close_toggle_web_and_mobile(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")

    import app.main as main
    importlib.reload(main)

    # Attach a business-owner account to the seeded business.
    db = main.SessionLocal()
    business_id = db.query(main.Business).first().id
    db.add(main.User(email="owner@example.com", password_hash=main.hash_password("owner-pass"),
                     role="business_owner", business_id=business_id))
    db.commit()
    db.close()

    # Mobile API client authenticates by bearer token only (no cookies).
    api = TestClient(main.app)
    login = api.post("/api/login", json={"email": "owner@example.com", "password": "owner-pass"})
    assert login.status_code == 200
    assert login.json()["user"]["accepting_orders"] is True
    auth = {"Authorization": f"Bearer {login.json()['token']}"}

    assert api.get("/api/business", headers=auth).json()["accepting_orders"] is True

    # Pause from the app.
    paused = api.post("/api/business/accepting-orders", headers=auth, json={"accepting_orders": False})
    assert paused.status_code == 200 and paused.json()["accepting_orders"] is False
    assert "paused" in api.post("/webhook", json={"from": "2348012345678", "message": "hi"}).json()["reply"].lower()

    # Resume from the web dashboard (separate client so cookies don't clash).
    web = TestClient(main.app)
    web.post("/login", data={"email": "admin@example.com", "password": "test-admin-password"}, follow_redirects=False)
    assert web.post(f"/business/{business_id}/toggle-orders", follow_redirects=False).status_code == 303
    assert api.get("/api/business", headers=auth).json()["accepting_orders"] is True


def test_delivery_fee_requires_accepting_refund_liability(tmp_path, monkeypatch):
    """Pricing an order is the moment the business takes it on, so the server
    refuses to price (and to bill the customer) without an explicit acceptance —
    a form post that skips the browser must not slip past the checkbox."""
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    _place_demo_order(client)
    client.post("/login", data={"email": "admin@example.com", "password": "test-admin-password"},
                follow_redirects=False)
    order_id = client.get("/api/action-required").json()["orders"][0]["id"]

    # No acceptance: bounced back to the order, still unpriced and unbilled.
    refused = client.post(f"/orders/{order_id}/delivery-fee", data={"delivery_fee": "500"},
                          follow_redirects=False)
    assert refused.status_code == 303
    assert "accept_required" in refused.headers["location"]

    db = main.SessionLocal()
    order = db.query(main.Order).filter(main.Order.id == order_id).one()
    assert order.status == "awaiting_delivery_fee"
    assert order.fee_terms_accepted_at is None
    db.close()

    # While the order still awaits pricing, the dialog carries the acceptance
    # checkbox and links the policy it refers to.
    detail = client.get(f"/orders/{order_id}").text
    assert "accept_terms" in detail
    assert "/refunds" in detail

    # With acceptance: priced, and the acceptance is stamped against the order.
    ok = client.post(f"/orders/{order_id}/delivery-fee",
                     data={"delivery_fee": "500", "accept_terms": "1"}, follow_redirects=False)
    assert ok.status_code == 303

    db = main.SessionLocal()
    order = db.query(main.Order).filter(main.Order.id == order_id).one()
    assert order.status == "awaiting_payment"
    assert order.fee_terms_accepted_at is not None
    assert order.fee_terms_version == main.LEGAL_LAST_UPDATED
    db.close()


def test_refund_requires_payment_and_is_recorded(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    _place_demo_order(client)
    token = client.post("/api/login", json={"email": "admin@example.com",
                                            "password": "test-admin-password"}).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}
    order_id = client.get("/api/action-required", headers=auth).json()["orders"][0]["id"]
    action_url = f"/api/orders/{order_id}/action"

    # Nothing has been paid yet, so there is nothing to refund — that is a cancel.
    too_early = client.post(action_url, headers=auth, json={"action": "refund"})
    assert too_early.status_code == 400
    assert too_early.json()["error"] == "not_refundable"

    fee = client.post(action_url, headers=auth,
                      json={"action": "set_delivery_fee", "delivery_fee": 500,
                            "accept_terms": True}).json()
    assert fee["terms_accepted_at"] is not None
    paid = client.post(action_url, headers=auth, json={"action": "mark_paid"}).json()
    assert "refund" in paid["available_actions"]

    refunded = client.post(action_url, headers=auth,
                           json={"action": "refund", "refund_reason": "Kitchen ran out"}).json()
    assert refunded["status"] == "refunded"
    assert refunded["refund_amount"] == refunded["total"]
    assert refunded["refund_reason"] == "Kitchen ran out"
    assert refunded["refunded_at"] is not None
    # A refunded order must stop counting as money earned.
    assert refunded["status"] not in main.PAID_STATUSES
    # And it cannot be refunded a second time.
    assert client.post(action_url, headers=auth, json={"action": "refund"}).status_code == 400


def test_refund_breakdown_keeps_messaging_fee_and_reverses_commission(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import app.main as main
    importlib.reload(main)

    db = main.SessionLocal()
    business = db.query(main.Business).first()
    business.payment_method = "paystack"          # customer service fee only applies here
    order = main.Order(business_id=business.id, customer_phone="2348012345678", items_json="[]",
                       total=5000, delivery_fee=500, address="12 Marina Road", status="paid",
                       message_count=4)
    db.close()

    breakdown = main.order_refund_breakdown(business, order)
    expected_fee = main.PLATFORM_SERVICE_CHARGE_NGN + 4 * main.PLATFORM_PER_MESSAGE_NGN
    # Goods and delivery go back; the messaging we were already billed for does not.
    assert breakdown["refundable"] == 5000
    assert breakdown["retained_service_fee"] == expected_fee
    assert breakdown["customer_paid"] == 5000 + expected_fee
    assert breakdown["commission_reversed"] == round(5000 * main.PLATFORM_COMMISSION_PERCENT / 100)


def test_affiliate_share_math(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import app.main as main
    importlib.reload(main)

    order = main.Order(business_id=1, customer_phone="2348012345678", items_json="[]",
                       total=5000, delivery_fee=0, address="x", status="paid")
    commission = main.order_commission(order)
    assert commission == round(5000 * main.PLATFORM_COMMISSION_PERCENT / 100)
    assert main.affiliate_share(order) == round(commission * main.AFFILIATE_SHARE_PERCENT / 100)
    # order_platform_charge must still agree with order_commission (single source of truth).
    assert main.order_platform_charge(order) == main.PLATFORM_SERVICE_CHARGE_NGN + commission


def test_affiliate_accrual_respects_window_and_refunds(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import app.main as main
    importlib.reload(main)

    db = main.SessionLocal()
    business = db.query(main.Business).first()
    affiliate = main.User(email="ref@example.com", password_hash="x", role="affiliate")
    db.add(affiliate)
    db.commit()
    db.refresh(affiliate)
    referred_at = main.datetime.utcnow() - main.timedelta(days=100)
    business.referred_by_user_id = affiliate.id
    business.referred_at = referred_at
    db.commit()

    # In-window, paid: counts.
    in_window = main.Order(business_id=business.id, customer_phone="1", items_json="[]",
                           total=10000, address="x", status="paid",
                           created_at=referred_at + main.timedelta(days=10))
    # Past the one-year window: does not count even though paid.
    expired = main.Order(business_id=business.id, customer_phone="1", items_json="[]",
                         total=10000, address="x", status="paid",
                         created_at=referred_at + main.timedelta(days=400))
    # Refunded: does not count even though within the window.
    refunded = main.Order(business_id=business.id, customer_phone="1", items_json="[]",
                          total=10000, address="x", status="refunded",
                          created_at=referred_at + main.timedelta(days=20))
    db.add_all([in_window, expired, refunded])
    db.commit()

    balance = main.affiliate_accrued_balance(db, affiliate.id)
    assert balance == main.affiliate_share(in_window)
    assert balance > 0
    db.close()


def test_affiliate_admin_flow_and_mobile_login(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    login = client.post("/login", data={"email": "admin@example.com", "password": "test-admin-password"},
                       follow_redirects=False)
    assert login.status_code == 303

    reg = client.post("/register", data={
        "email": "ref@example.com", "password": "affpass123", "role": "affiliate",
    }, follow_redirects=False)
    assert reg.status_code == 303

    db = main.SessionLocal()
    business = db.query(main.Business).first()
    affiliate = db.query(main.User).filter(main.User.email == "ref@example.com").one()
    assert affiliate.role == "affiliate"
    db.close()

    link = client.post(f"/admin/businesses/{business.id}", data={
        "name": business.name, "whatsapp_number": business.whatsapp_number,
        "referred_by_user_id": str(affiliate.id),
    }, follow_redirects=False)
    assert link.status_code == 303

    db = main.SessionLocal()
    business = db.query(main.Business).filter(main.Business.id == business.id).one()
    assert business.referred_by_user_id == affiliate.id
    assert business.referred_at is not None
    business_name = business.name  # captured before commit() expires the instance
    order = main.Order(business_id=business.id, customer_phone="1", items_json="[]",
                       total=8000, address="x", status="paid")
    db.add(order)
    db.commit()
    expected_share = main.affiliate_share(order)
    db.close()

    # Separate client for the affiliate's mobile-app session — a real phone never
    # carries the admin's browser cookie, and get_current_user() prefers a cookie
    # over the bearer header when both are present, so reusing `client` here would
    # silently authenticate as the admin instead of the affiliate.
    mobile = TestClient(main.app)
    aff_login = mobile.post("/api/login", json={"email": "ref@example.com", "password": "affpass123"})
    assert aff_login.status_code == 200
    token = aff_login.json()["token"]
    assert aff_login.json()["user"]["role"] == "affiliate"

    summary = mobile.get("/api/affiliate/summary", headers={"Authorization": f"Bearer {token}"}).json()
    assert summary["accrued_total"] == expected_share
    assert summary["outstanding"] == expected_share
    assert summary["referred_businesses"][0]["business_name"] == business_name

    payout = client.post(f"/admin/affiliates/{affiliate.id}/payouts",
                         data={"amount": str(expected_share), "note": "bank transfer"},
                         follow_redirects=False)
    assert payout.status_code == 303

    summary_after = mobile.get("/api/affiliate/summary", headers={"Authorization": f"Bearer {token}"}).json()
    assert summary_after["paid_total"] == expected_share
    assert summary_after["outstanding"] == 0


def test_rider_split_shares_preserve_platform_charge(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import app.main as main
    importlib.reload(main)

    order = main.Order(business_id=1, customer_phone="1", items_json="[]",
                       total=8500, delivery_fee=1500, address="x", status="awaiting_payment",
                       message_count=6)
    business_share, rider_share = main.rider_split_shares(order)
    assert rider_share == 1500  # the full delivery fee, untouched
    # Whatever's left after both flat shares must equal exactly what Collxct
    # would have taken anyway — the rider only intercepts the delivery portion.
    remainder = order.total - business_share - rider_share
    assert remainder == main.order_commission(order)
    assert business_share == order.total - order.delivery_fee - main.order_commission(order)


def test_apply_order_action_assigns_rider_and_rejects_foreign_rider(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import app.main as main
    importlib.reload(main)

    db = main.SessionLocal()
    business = db.query(main.Business).first()
    other_business = main.Business(name="Other Shop", whatsapp_number="+2348099999999")
    rider = main.Rider(business_id=business.id, name="Chidi", phone="080...")
    db.add_all([other_business, rider])
    db.commit()
    db.refresh(other_business)
    db.refresh(rider)
    foreign_rider = main.Rider(business_id=other_business.id, name="Not Yours")
    db.add(foreign_rider)
    db.commit()
    db.refresh(foreign_rider)

    order = main.Order(business_id=business.id, customer_phone="1", items_json="[]",
                       total=0, delivery_fee=0, address="x", status="awaiting_delivery_fee")
    db.add(order)
    db.commit()

    # A rider that actually belongs to this business gets assigned.
    main.apply_order_action(db, order, business, "set_delivery_fee",
                            delivery_fee=1000, rider_id=rider.id)
    assert order.rider_id == rider.id

    # A rider belonging to a DIFFERENT business is silently ignored, not assigned.
    order2 = main.Order(business_id=business.id, customer_phone="2", items_json="[]",
                        total=0, delivery_fee=0, address="x", status="awaiting_delivery_fee")
    db.add(order2)
    db.commit()
    main.apply_order_action(db, order2, business, "set_delivery_fee",
                            delivery_fee=1000, rider_id=foreign_rider.id)
    assert order2.rider_id is None
    db.close()


def test_admin_creates_rider(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    client.post("/login", data={"email": "admin@example.com", "password": "test-admin-password"},
               follow_redirects=False)
    db = main.SessionLocal()
    business = db.query(main.Business).first()
    business_id = business.id
    db.close()

    created = client.post(f"/admin/businesses/{business_id}/riders", data={
        "name": "Chidi", "phone": "08011112222", "bank_name": "GTBank",
        "bank_account_number": "0123456789", "bank_code": "058",
    }, follow_redirects=False)
    assert created.status_code == 303

    db = main.SessionLocal()
    rider = db.query(main.Rider).filter(main.Rider.business_id == business_id).one()
    assert rider.name == "Chidi"
    assert rider.bank_account_number == "0123456789"
    db.close()


def test_affiliate_cannot_login_via_web(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    db = main.SessionLocal()
    db.add(main.User(email="ref2@example.com", password_hash=main.hash_password("affpass123"), role="affiliate"))
    db.commit()
    db.close()

    resp = client.post("/login", data={"email": "ref2@example.com", "password": "affpass123"}, follow_redirects=False)
    # No redirect to a dashboard and no session cookie — just an informational page.
    assert resp.status_code == 200
    assert "mobile app" in resp.text.lower()
    assert "auth_token" not in resp.cookies


def test_robots_and_sitemap(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    robots = client.get("/robots.txt")
    assert robots.status_code == 200
    assert "Sitemap:" in robots.text
    assert "Disallow: /admin/" in robots.text

    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200
    assert "<urlset" in sitemap.text
    assert "<loc>" in sitemap.text


def test_resolve_account_requires_staff_auth(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    resp = client.get("/api/resolve-account?account_number=0123456789&bank_code=058")
    assert resp.status_code == 401


def test_delivery_fee_prefers_osrm_road_distance_over_haversine(tmp_path, monkeypatch):
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import app.main as main
    importlib.reload(main)

    db = main.SessionLocal()
    business = main.Business(
        name="Osrm Test Shop", whatsapp_number="+2348055555555",
        delivery_autocalc=1, delivery_base_fee=1000, delivery_per_km=200,
        geo_lat=6.45, geo_lng=3.40,
    )
    db.add(business)
    db.commit()
    db.refresh(business)

    monkeypatch.setattr(main, "geocode_address", lambda address: (6.47, 3.40))

    # OSRM's road distance (5.0 km) is meaningfully longer than the straight-line
    # haversine distance between these two points (~2.2 km) — if the auto-fee
    # reflects 5.0 km, we know OSRM's result won the fallback, not haversine's.
    monkeypatch.setattr(main, "osrm_route_km", lambda *a: 5.0)
    result = main.compute_auto_delivery_fee(business, "12 Marina Road, Lagos")
    assert result["km"] == 5.0
    assert result["fee"] == 1000 + 5 * 200  # 2000

    # When OSRM is unavailable (demo server down, timeout, rate-limited, etc.),
    # it must fall back to haversine rather than fail the whole auto-fee.
    monkeypatch.setattr(main, "osrm_route_km", lambda *a: None)
    result_fallback = main.compute_auto_delivery_fee(business, "12 Marina Road, Lagos")
    assert result_fallback is not None
    assert result_fallback["km"] < 3.0  # haversine's straight-line ~2.2 km
    db.close()
