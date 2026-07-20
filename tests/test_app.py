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
