import os
import importlib

from fastapi.testclient import TestClient


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
    fee_response = client.post(f"/orders/{order['id']}/delivery-fee", data={"delivery_fee": "500"}, follow_redirects=False)
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

    def fake_link(business, order):
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
    for needle in ["ordering machine", "Simple, honest pricing", "Starter", "Growth", "What we need to onboard you", "Request my setup", "logo-white.svg"]:
        assert needle in page.text, f"missing: {needle}"

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
    assert paid["available_actions"] == ["dispatch"]

    dispatched = client.post(f"/api/orders/{order_id}/action", headers=auth, json={"action": "dispatch"}).json()
    assert dispatched["status"] == "out_for_delivery"
    assert dispatched["available_actions"] == ["mark_delivered"]

    delivered = client.post(f"/api/orders/{order_id}/action", headers=auth, json={"action": "mark_delivered"}).json()
    assert delivered["status"] == "delivered"
    assert delivered["available_actions"] == []

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

    for path, needle in [("/terms", "Terms of Use"), ("/privacy", "Privacy Policy")]:
        r = client.get(path)
        assert r.status_code == 200
        assert needle in r.text
        assert "not legal advice" in r.text


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
