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

    response = client.get("/admin/")
    assert response.status_code == 200
    assert "Admin Dashboard" in response.text

    login_response = client.post(
        "/login",
        data={"email": "admin@example.com", "password": "test-admin-password"},
        follow_redirects=False,
    )
    assert login_response.status_code == 303

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
