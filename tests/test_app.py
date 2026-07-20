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
