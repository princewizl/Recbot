import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta
from html import escape
from typing import Dict, List, Optional

import httpx
from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint, create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker
from twilio.request_validator import RequestValidator
from twilio.rest import Client as TwilioClient

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'bot.db')}")

if DATABASE_URL.startswith("sqlite:///"):
    RECEIPTS_DIR = os.path.join(os.path.dirname(DATABASE_URL[len("sqlite:///"):]) or ".", "receipts")
else:
    RECEIPTS_DIR = os.path.join(BASE_DIR, "receipts")
os.makedirs(RECEIPTS_DIR, exist_ok=True)

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class Business(Base):
    __tablename__ = "businesses"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    whatsapp_number = Column(String(50), nullable=False)
    owner_notify_number = Column(String(50), nullable=True)
    plan_id = Column(Integer, nullable=True)
    plan_status = Column(String(50), nullable=False, default="trial")
    plan_expiry = Column(DateTime, nullable=True)
    auto_renew = Column(Integer, nullable=False, default=0)
    bank_name = Column(String(255), nullable=True)
    bank_account_number = Column(String(50), nullable=True)
    bank_account_name = Column(String(255), nullable=True)


class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, nullable=False)
    name = Column(String(255), nullable=False)


class Branch(Base):
    __tablename__ = "branches"
    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, nullable=False)
    name = Column(String(255), nullable=False)
    address = Column(Text, nullable=True)


class MenuItem(Base):
    __tablename__ = "menu_items"
    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, nullable=False)
    category_id = Column(Integer, nullable=True)
    branch_id = Column(Integer, nullable=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Integer, nullable=False)
    is_active = Column(Integer, nullable=False, default=1)
    is_out_of_stock = Column(Integer, nullable=False, default=0)
    image_url = Column(String(255), nullable=True)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("phone_number", "business_id", name="ix_conversations_phone_business"),)
    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String(50), nullable=False)
    business_id = Column(Integer, nullable=False)
    branch_id = Column(Integer, nullable=True)
    category_id = Column(Integer, nullable=True)
    stage = Column(String(50), nullable=False, default="new")
    cart_json = Column(Text, default="[]")
    address = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, nullable=False)
    branch_id = Column(Integer, nullable=True)
    customer_phone = Column(String(50), nullable=False)
    items_json = Column(Text, nullable=False)
    total = Column(Integer, nullable=False)
    delivery_fee = Column(Integer, nullable=False, default=0)
    address = Column(Text, nullable=False)
    status = Column(String(50), nullable=False, default="new")
    payment_proof_text = Column(Text, nullable=True)
    payment_receipt_path = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="customer")
    business_id = Column(Integer, nullable=True)


class Plan(Base):
    __tablename__ = "plans"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    price_ngn = Column(Integer, nullable=False)
    branch_access = Column(Integer, nullable=False, default=0)
    description = Column(Text, nullable=True)


class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, nullable=False)
    user_email = Column(String(255), nullable=False)
    plan_id = Column(Integer, nullable=False)
    amount = Column(Integer, nullable=False)
    reference = Column(String(255), nullable=False, unique=True)
    status = Column(String(50), nullable=False, default="initialized")
    auto_renew = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=engine)


def ensure_schema() -> None:
    if not str(engine.url).startswith("sqlite"):
        return

    with engine.begin() as conn:
        def has_column(table_name: str, column_name: str) -> bool:
            rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
            return any(row[1] == column_name for row in rows)

        def has_index(table_name: str, index_name: str) -> bool:
            rows = conn.execute(text(f"PRAGMA index_list({table_name})")).fetchall()
            return any(row[1] == index_name for row in rows)

        if not has_column("orders", "branch_id"):
            conn.execute(text("ALTER TABLE orders ADD COLUMN branch_id INTEGER"))
        if not has_column("conversations", "branch_id"):
            conn.execute(text("ALTER TABLE conversations ADD COLUMN branch_id INTEGER"))
        if not has_column("conversations", "category_id"):
            conn.execute(text("ALTER TABLE conversations ADD COLUMN category_id INTEGER"))
        if not has_column("menu_items", "category_id"):
            conn.execute(text("ALTER TABLE menu_items ADD COLUMN category_id INTEGER"))
        if not has_column("menu_items", "branch_id"):
            conn.execute(text("ALTER TABLE menu_items ADD COLUMN branch_id INTEGER"))
        if not has_column("menu_items", "description"):
            conn.execute(text("ALTER TABLE menu_items ADD COLUMN description TEXT"))
        if not has_column("businesses", "plan_id"):
            conn.execute(text("ALTER TABLE businesses ADD COLUMN plan_id INTEGER"))
        if not has_column("businesses", "plan_status"):
            conn.execute(text("ALTER TABLE businesses ADD COLUMN plan_status VARCHAR(50) NOT NULL DEFAULT 'trial'"))
        if not has_column("businesses", "plan_expiry"):
            conn.execute(text("ALTER TABLE businesses ADD COLUMN plan_expiry DATETIME"))
        if not has_column("businesses", "auto_renew"):
            conn.execute(text("ALTER TABLE businesses ADD COLUMN auto_renew INTEGER NOT NULL DEFAULT 0"))
        if not has_column("menu_items", "is_active"):
            conn.execute(text("ALTER TABLE menu_items ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1"))
        if not has_column("menu_items", "is_out_of_stock"):
            conn.execute(text("ALTER TABLE menu_items ADD COLUMN is_out_of_stock INTEGER NOT NULL DEFAULT 0"))
        if not has_column("businesses", "bank_name"):
            conn.execute(text("ALTER TABLE businesses ADD COLUMN bank_name VARCHAR(255)"))
        if not has_column("businesses", "bank_account_number"):
            conn.execute(text("ALTER TABLE businesses ADD COLUMN bank_account_number VARCHAR(50)"))
        if not has_column("businesses", "bank_account_name"):
            conn.execute(text("ALTER TABLE businesses ADD COLUMN bank_account_name VARCHAR(255)"))
        if not has_column("orders", "delivery_fee"):
            conn.execute(text("ALTER TABLE orders ADD COLUMN delivery_fee INTEGER NOT NULL DEFAULT 0"))
        if not has_column("orders", "payment_proof_text"):
            conn.execute(text("ALTER TABLE orders ADD COLUMN payment_proof_text TEXT"))
        if not has_column("orders", "payment_receipt_path"):
            conn.execute(text("ALTER TABLE orders ADD COLUMN payment_receipt_path VARCHAR(255)"))

        if not has_index("conversations", "ix_conversations_phone_business"):
            conn.execute(text(
                "CREATE TABLE conversations_new ("
                "id INTEGER PRIMARY KEY, phone_number VARCHAR(50) NOT NULL, business_id INTEGER NOT NULL, "
                "branch_id INTEGER, category_id INTEGER, stage VARCHAR(50) NOT NULL DEFAULT 'new', "
                "cart_json TEXT DEFAULT '[]', address TEXT, updated_at DATETIME)"
            ))
            conn.execute(text(
                "INSERT INTO conversations_new (id, phone_number, business_id, branch_id, category_id, stage, cart_json, address, updated_at) "
                "SELECT id, phone_number, business_id, branch_id, category_id, stage, cart_json, address, updated_at FROM conversations"
            ))
            conn.execute(text("DROP TABLE conversations"))
            conn.execute(text("ALTER TABLE conversations_new RENAME TO conversations"))
            conn.execute(text("CREATE UNIQUE INDEX ix_conversations_phone_business ON conversations(phone_number, business_id)"))


ensure_schema()

app = FastAPI(title="Recbot CRM")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
SECRET_KEY = os.getenv("SECRET_KEY", "supersecret-key")


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return hash_password(password) == password_hash


def create_auth_token(email: str) -> str:
    signature = hmac.new(SECRET_KEY.encode(), email.encode(), hashlib.sha256).hexdigest()
    token = f"{email}:{signature}"
    return base64.urlsafe_b64encode(token.encode()).decode()


def verify_auth_token(token: str) -> Optional[str]:
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        email, signature = decoded.split(":")
        expected = hmac.new(SECRET_KEY.encode(), email.encode(), hashlib.sha256).hexdigest()
        if hmac.compare_digest(signature, expected):
            return email
    except Exception:
        return None
    return None


def get_user_by_email(db, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email).one_or_none()


def get_current_user(request: Request) -> Optional[User]:
    token = request.cookies.get("auth_token")
    if not token:
        return None
    email = verify_auth_token(token)
    if not email:
        return None
    db = SessionLocal()
    try:
        return get_user_by_email(db, email)
    finally:
        db.close()


def make_nav(current_user: Optional[User] = None) -> str:
    links = ["<a class='nav-link' href='/'>Home</a>"]
    if current_user:
        if current_user.role == "admin":
            links.append("<a class='nav-link' href='/admin/'>Command Center</a>")
            links.append("<a class='nav-link' href='/register'>Create Owners</a>")
            links.append("<a class='nav-link' href='/admin/businesses'>Businesses</a>")
            links.append("<a class='nav-link' href='/admin/users'>Users</a>")
        is_business_owner = current_user.role in {"business_owner", "business-owner", "owner"}
        if is_business_owner:
            links.append("<a class='nav-link' href='/owner/portal'>Owner Portal</a>")
            if current_user.business_id:
                links.append(f"<a class='nav-link' href='/business/{current_user.business_id}/dashboard'>Operations</a>")
                links.append(f"<a class='nav-link' href='/business/{current_user.business_id}/config'>Config</a>")
                links.append(f"<a class='nav-link' href='/business/{current_user.business_id}/plans'>Plans</a>")
    else:
        links.append("<a class='nav-link' href='/login'>Login</a>")
    nav_links_html = f"<div class='nav-links'>{''.join(links)}</div>"
    if current_user:
        initial = escape(current_user.email[:1].upper())
        footer = f"""
        <div class='nav-footer'>
          <div class='user-chip'>
            <span class='user-avatar'>{initial}</span>
            <span class='user-email'>{escape(current_user.email)}</span>
          </div>
          <a class='nav-link logout' href='/logout'>Logout</a>
        </div>
        """
    else:
        footer = ""
    return nav_links_html + footer


MASCOT_WIDGET_HTML = """
<script src="https://unpkg.com/@dotlottie/player-component@2.7.12/dist/dotlottie-player.mjs" type="module"></script>
<div id="rb-mascot" class="rb-mascot">
  <div id="rb-bubble" class="rb-bubble">
    <span id="rb-tip">Hi, I'm Ada! I'll pop up with tips as you work around Recbot CRM.</span>
  </div>
  <button id="rb-toggle" class="rb-toggle" type="button" aria-label="Toggle Ada, your Recbot helper" title="Ada, your Recbot helper">
    <dotlottie-player id="rb-avatar" class="rb-avatar" src="/static/lottie/chatbot.lottie" background="transparent" speed="1" loop autoplay></dotlottie-player>
  </button>
</div>
<script>
(function () {
  var KEY = "rb_mascot_collapsed";
  var mascot = document.getElementById("rb-mascot");
  var toggle = document.getElementById("rb-toggle");
  var tipEl = document.getElementById("rb-tip");
  var tips = [
    "Hi, I'm Ada! I'll pop up with tips as you work around Recbot CRM.",
    "New business owner? Go to Create Owners and pick their business right from the dropdown — no need to remember ID numbers.",
    "Forgot to attach someone to a business? Open Users, click Edit next to their name, and pick a business anytime.",
    "Add categories and branches on a business's page before adding menu items — it keeps the menu tidy.",
    "Mark an item Out of Stock instead of deleting it — customers won't see it, but you keep the record.",
    "Check a business's Plans page to see when their subscription expires and switch plans.",
    "The Conversations page shows live WhatsApp chats in progress, including what's in each customer's cart.",
    "Business owners can jump straight to Operations, Config, and Plans from their own nav bar.",
    "Every order shows the customer's phone, total, and delivery address — find them under Orders.",
    "Click my avatar anytime to tuck me away — I'll remember and stay small until you need me again."
  ];
  var idx = 0;
  function applyState() {
    var collapsed = false;
    try { collapsed = localStorage.getItem(KEY) === "1"; } catch (e) {}
    mascot.classList.toggle("rb-collapsed", collapsed);
  }
  function rotateTip() {
    idx = (idx + 1) % tips.length;
    tipEl.textContent = tips[idx];
  }
  toggle.addEventListener("click", function () {
    var collapsed = mascot.classList.toggle("rb-collapsed");
    try { localStorage.setItem(KEY, collapsed ? "1" : "0"); } catch (e) {}
  });
  applyState();
  setInterval(rotateTip, 6500);
})();
</script>
"""


def render_page(title: str, body: str, nav_html: Optional[str] = None) -> HTMLResponse:
    nav_html = nav_html or make_nav(None)
    html = f"""
    <!DOCTYPE html>
    <html>
      <head>
        <meta charset="utf-8" />
        <title>{escape(title)}</title>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet" />
        <style>
                    :root {{
                      --bg:#09090b; --surface:#111114; --surface-2:#18181c; --surface-hover:#1f1f25;
                      --text:#f2f3f5; --muted:#8b8d97; --muted-2:#5f606b;
                      --primary:#5b7cff; --primary-strong:#7c98ff; --accent:#28d7b6; --danger:#ff5e7a;
                      --border:rgba(255,255,255,.08); --border-strong:rgba(255,255,255,.14);
                      --radius-sm:8px; --radius-md:12px; --radius-lg:18px;
                      --shadow-sm:0 1px 2px rgba(0,0,0,.5); --shadow-md:0 12px 32px rgba(0,0,0,.4);
                    }}
                    * {{ box-sizing: border-box; }}
                    html,body {{ height:100%; }}
                    body {{
                      margin:0; font-family:'Inter', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                      font-size:15px; line-height:1.6; color:var(--text);
                      background: radial-gradient(1100px circle at 12% -8%, rgba(91,124,255,.12), transparent 55%), radial-gradient(900px circle at 100% 0%, rgba(40,215,182,.07), transparent 50%), var(--bg);
                    }}
                    .shell {{ display:flex; min-height:100vh; }}
                    .sidebar {{ width:258px; flex-shrink:0; background:var(--surface); border-right:1px solid var(--border); display:flex; flex-direction:column; padding:18px 14px; position:sticky; top:0; height:100vh; overflow-y:auto; }}
                    .brand {{ display:flex; align-items:center; gap:10px; padding:4px 8px 18px; margin-bottom:10px; border-bottom:1px solid var(--border); }}
                    .brand-mark {{ width:26px; height:26px; border-radius:7px; background:linear-gradient(135deg,var(--primary),var(--accent)); flex-shrink:0; box-shadow:0 4px 14px rgba(91,124,255,.35); }}
                    .brand-name {{ font-weight:700; font-size:1.02rem; letter-spacing:-.02em; color:var(--text); }}
                    .nav-links {{ display:flex; flex-direction:column; gap:2px; }}
                    .nav-link {{ display:flex; align-items:center; gap:9px; padding:9px 11px; border-radius:var(--radius-sm); color:var(--muted); font-weight:500; font-size:.9rem; text-decoration:none; transition:background .15s ease, color .15s ease; }}
                    .nav-link:hover {{ background:var(--surface-2); color:var(--text); }}
                    .nav-footer {{ margin-top:auto; padding-top:14px; border-top:1px solid var(--border); display:flex; flex-direction:column; gap:6px; }}
                    .user-chip {{ display:flex; align-items:center; gap:9px; padding:8px 10px; border-radius:var(--radius-sm); background:var(--surface-2); }}
                    .user-avatar {{ width:26px; height:26px; border-radius:50%; background:linear-gradient(135deg,var(--primary),var(--accent)); color:#fff; display:flex; align-items:center; justify-content:center; font-size:.72rem; font-weight:700; flex-shrink:0; }}
                    .user-email {{ font-size:.82rem; color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
                    .nav-link.logout {{ color:var(--danger); }}
                    .nav-link.logout:hover {{ background:rgba(255,94,122,.1); color:var(--danger); }}
                    .chip {{ padding:5px 10px; border:1px solid var(--border); border-radius:999px; color:var(--muted); font-size:.82rem; }}
                    .main-area {{ flex:1; min-width:0; display:flex; flex-direction:column; }}
                    .page-title {{ position:sticky; top:0; z-index:5; padding:16px 32px; background:rgba(9,9,11,.75); backdrop-filter:blur(10px); border-bottom:1px solid var(--border); }}
                    .page-title h1 {{ margin:0; font-size:1.3rem; font-weight:700; letter-spacing:-.01em; color:var(--text); }}
                    .page-title p {{ margin:6px 0 0; color:var(--muted); font-size:.88rem; }}
                    .content {{ padding:28px 32px 64px; max-width:1280px; display:flex; flex-direction:column; gap:22px; width:100%; }}
                    .hero, .hero-panel, .auth-hero {{ border-radius:var(--radius-lg); border:1px solid var(--border-strong); background:linear-gradient(135deg,#1a2040 0%,#121a30 48%,#0d1220 100%); box-shadow:inset 0 1px 0 rgba(255,255,255,.05), var(--shadow-md); color:var(--text); }}
                    .hero {{ padding:30px; }}
                    .hero h1 {{ margin:0 0 10px; font-size:1.9rem; letter-spacing:-.02em; }}
                    .hero p {{ margin:0 0 16px; color:#c7cdea; max-width:720px; }}
                    .hero-panel {{ display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:18px; padding:28px; }}
                    .hero-panel h1 {{ margin:0 0 8px; font-size:clamp(1.5rem,2.6vw,2.1rem); line-height:1.1; letter-spacing:-.02em; }}
                    .hero-panel p {{ margin:0; color:#c7cdea; max-width:680px; }}
                    .hero-panel .actions {{ display:flex; flex-wrap:wrap; gap:10px; }}
                    .auth-shell {{ display:grid; grid-template-columns:1.05fr .95fr; gap:20px; align-items:stretch; }}
                    .auth-hero {{ padding:26px; display:flex; flex-direction:column; justify-content:center; min-height:320px; }}
                    .auth-hero h2 {{ margin:0 0 10px; font-size:1.6rem; letter-spacing:-.02em; }}
                    .auth-hero p {{ color:#c7cdea; }}
                    .auth-form {{ display:flex; flex-direction:column; gap:10px; }}
                    .auth-form .form-row {{ display:flex; flex-direction:column; gap:8px; }}
                    .form-hint {{ color:var(--muted); font-size:.88rem; margin-top:4px; }}
                    .grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:16px; }}
                    .card {{ background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-md); padding:22px; box-shadow:var(--shadow-sm); }}
                    .card h2, .card h3 {{ margin-top:0; }}
                    .card p {{ color:var(--muted); line-height:1.7; }}
                    .stats-grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:14px; }}
                    .stat-card {{ min-height:104px; display:flex; flex-direction:column; justify-content:center; gap:4px; }}
                    .stat-card .value {{ font-size:1.7rem; font-weight:700; letter-spacing:-.03em; }}
                    .panel-grid {{ display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:16px; }}
                    .section-head {{ display:flex; justify-content:space-between; align-items:center; gap:10px; margin-bottom:12px; }}
                    .section-head h3 {{ margin:0; font-size:1rem; }}
                    .table-wrap {{ overflow-x:auto; }}
                    .table-wrap table {{ min-width:500px; }}
                    .form-row {{ display:grid; gap:8px; }}
                    .form-actions {{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-top:8px; }}
                    .pill-list {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:8px; }}
                    .pill-list .pill {{ margin:0; }}
                    .metric {{ display:flex; flex-direction:column; gap:6px; }}
                    .metric .value {{ font-size:1.5rem; font-weight:700; letter-spacing:-.03em; }}
                    .metric .label {{ color:var(--muted); font-size:.82rem; }}
                    .btn, button {{ display:inline-flex; align-items:center; justify-content:center; padding:9px 16px; border-radius:var(--radius-sm); font-weight:600; font-size:.88rem; text-decoration:none; cursor:pointer; border:1px solid var(--border-strong); background:var(--surface-2); color:var(--text); font-family:inherit; transition:background .15s ease, border-color .15s ease, transform .1s ease; margin-right:8px; }}
                    .btn:hover, button:hover {{ background:var(--surface-hover); transform:translateY(-1px); }}
                    .btn.primary, button[type="submit"] {{ background:var(--primary); border-color:var(--primary); color:#fff; }}
                    .btn.primary:hover, button[type="submit"]:hover {{ background:var(--primary-strong); border-color:var(--primary-strong); }}
                    button.secondary {{ background:transparent; }}
                    table {{ width:100%; border-collapse:collapse; background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-md); overflow:hidden; }}
                    th {{ text-align:left; padding:10px 14px; font-size:.72rem; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); font-weight:600; background:var(--surface-2); border-bottom:1px solid var(--border-strong); }}
                    td {{ padding:12px 14px; border-bottom:1px solid var(--border); text-align:left; font-size:.88rem; }}
                    tr:last-child td {{ border-bottom:none; }}
                    tbody tr:hover td {{ background:var(--surface-2); }}
                    form {{ margin-top:10px; margin-bottom:14px; }}
                    input, select, textarea {{ display:block; margin-bottom:10px; padding:10px 13px; width:100%; max-width:480px; border:1px solid var(--border-strong); border-radius:var(--radius-sm); background:var(--surface-2); color:var(--text); font-size:.9rem; font-family:inherit; transition:border-color .15s ease, box-shadow .15s ease; }}
                    input:focus, select:focus, textarea:focus {{ outline:none; border-color:var(--primary); box-shadow:0 0 0 3px rgba(91,124,255,.18); }}
                    input::placeholder, textarea::placeholder {{ color:var(--muted-2); }}
                    ul {{ margin-left:20px; }}
                    a {{ color:var(--primary-strong); }}
                    .eyebrow {{ font-size:.72rem; text-transform:uppercase; letter-spacing:.14em; color:var(--muted); font-weight:700; margin-bottom:8px; }}
                    .stack {{ display:flex; flex-direction:column; gap:10px; }}
                    .pill {{ display:inline-block; padding:4px 10px; border-radius:999px; background:var(--surface-2); border:1px solid var(--border); color:var(--muted); font-size:.76rem; font-weight:600; margin-right:6px; }}
                    .form-group {{ margin-bottom:14px; }}
                    .status-pill {{ display:inline-flex; align-items:center; padding:6px 12px; border-radius:999px; background:rgba(40,215,182,.12); border:1px solid rgba(40,215,182,.3); color:var(--accent); font-weight:600; font-size:.82rem; }}
                    label {{ display:inline-flex; align-items:center; gap:8px; font-weight:500; font-size:.9rem; cursor:pointer; color:var(--text); }}
                    input[type="checkbox"], input[type="radio"] {{ width:auto; display:inline-block; max-width:none; margin:0; }}
                    .plan-grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(230px, 1fr)); gap:16px; margin:6px 0; }}
                    .plan-card {{ position:relative; display:flex; flex-direction:column; gap:8px; background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-md); padding:22px; transition:border-color .15s ease, transform .15s ease; }}
                    .plan-card:hover {{ transform:translateY(-2px); border-color:var(--border-strong); }}
                    .plan-card.active {{ border-color:var(--accent); box-shadow:0 0 0 1px var(--accent); }}
                    .plan-card h4 {{ margin:2px 0 0; font-size:1.15rem; }}
                    .plan-card .tag {{ align-self:flex-start; padding:3px 9px; border-radius:999px; background:var(--surface-2); color:var(--muted); font-size:.68rem; text-transform:uppercase; letter-spacing:.08em; font-weight:700; }}
                    .plan-card.active .tag {{ background:rgba(40,215,182,.15); color:var(--accent); }}
                    .plan-card .price {{ font-size:1.7rem; font-weight:800; letter-spacing:-.03em; color:var(--text); }}
                    .plan-card p {{ color:var(--muted); margin:0; font-size:.88rem; }}
                    .plan-card label {{ margin-top:6px; }}
                    .rb-mascot {{ position:fixed; right:20px; bottom:20px; z-index:9999; display:flex; flex-direction:column; align-items:flex-end; gap:10px; }}
                    .rb-bubble {{ max-width:240px; padding:12px 14px; border-radius:16px 16px 4px 16px; background:var(--surface); border:1px solid var(--border-strong); color:var(--text); font-size:.85rem; line-height:1.4; box-shadow:var(--shadow-md); }}
                    .rb-toggle {{ width:130px; height:130px; padding:0; border:none; background:transparent; cursor:pointer; display:flex; align-items:center; justify-content:center; transition:transform .2s ease; filter:drop-shadow(0 18px 30px rgba(0,0,0,.4)); }}
                    .rb-toggle:hover {{ transform:translateY(-2px) scale(1.04); }}
                    .rb-avatar {{ width:130px; height:130px; animation:rb-bob 3s ease-in-out infinite; }}
                    .rb-mascot.rb-collapsed .rb-bubble {{ display:none; }}
                    .rb-mascot.rb-collapsed .rb-toggle {{ width:72px; height:72px; opacity:.85; }}
                    .rb-mascot.rb-collapsed .rb-avatar {{ width:72px; height:72px; }}
                    @keyframes rb-bob {{ 0%, 100% {{ transform:translateY(0); }} 50% {{ transform:translateY(-6px); }} }}
                    @media (max-width: 900px) {{
                      .shell {{ flex-direction:column; }}
                      .sidebar {{ width:100%; height:auto; position:relative; flex-direction:row; align-items:center; overflow-x:auto; padding:10px 12px; gap:14px; }}
                      .brand {{ border-bottom:none; border-right:1px solid var(--border); padding:4px 14px 4px 0; margin-bottom:0; }}
                      .nav-links {{ flex-direction:row; }}
                      .nav-footer {{ margin-top:0; padding-top:0; border-top:none; flex-direction:row; margin-left:auto; }}
                      .user-email {{ display:none; }}
                      .content {{ padding:20px 16px 48px; }}
                      .page-title {{ padding:14px 16px; }}
                      .hero-panel {{ padding:22px; }}
                      .panel-grid {{ grid-template-columns:1fr; }}
                      .stats-grid {{ grid-template-columns:1fr; }}
                      .auth-shell {{ grid-template-columns:1fr; }}
                      .table-wrap table {{ min-width:420px; }}
                      .plan-grid {{ grid-template-columns:1fr; }}
                    }}
                    @media (max-width: 420px) {{
                      .hero, .hero-panel, .auth-hero {{ padding:18px; }}
                      .hero h1, .hero-panel h1 {{ font-size:1.4rem; }}
                      .stat-card .value, .metric .value {{ font-size:1.3rem; }}
                      .form-actions .btn, .form-actions button, .auth-form button, form button[type="submit"] {{ width:100%; text-align:center; margin-right:0; }}
                      .rb-bubble {{ max-width:calc(100vw - 88px); font-size:.82rem; }}
                    }}
                </style>
      </head>
      <body>
        <div class="shell">
          <aside class="sidebar">
            <div class="brand">
              <span class="brand-mark"></span>
              <span class="brand-name">Recbot</span>
            </div>
            {nav_html}
          </aside>
          <div class="main-area">
            <header class="page-title">
              <h1>{escape(title)}</h1>
            </header>
            <main class="content">
              {body}
            </main>
          </div>
        </div>
        {MASCOT_WIDGET_HTML}
      </body>
    </html>
    """
    return HTMLResponse(html)


def get_business(db, business_id: int) -> Optional[Business]:
    return db.query(Business).filter(Business.id == business_id).one_or_none()


def business_options_html(businesses: List[Business], selected_id: Optional[int] = None) -> str:
    return "".join(
        f"<option value='{b.id}' {'selected' if selected_id == b.id else ''}>{escape(b.name)} (#{b.id})</option>"
        for b in businesses
    )


def get_business_context(business_id: int) -> Dict[str, object]:
    db = SessionLocal()
    try:
        business = get_business(db, business_id)
        if not business:
            return {"business": None, "categories": [], "branches": [], "items": [], "orders": []}
        categories = db.query(Category).filter(Category.business_id == business.id).order_by(Category.name).all()
        branches = db.query(Branch).filter(Branch.business_id == business.id).order_by(Branch.name).all()
        items = db.query(MenuItem).filter(MenuItem.business_id == business.id).order_by(MenuItem.id).all()
        orders = db.query(Order).filter(Order.business_id == business.id).order_by(Order.created_at.desc()).all()
        return {"business": business, "categories": categories, "branches": branches, "items": items, "orders": orders}
    finally:
        db.close()


def get_plan(db, plan_id: int) -> Optional[Plan]:
    return db.query(Plan).filter(Plan.id == plan_id).one_or_none()


def get_active_plan(business: Business) -> Optional[Plan]:
    if not business or not business.plan_id:
        return None
    db = SessionLocal()
    try:
        return get_plan(db, business.plan_id)
    finally:
        db.close()


def plan_due_label(business: Business) -> str:
    if not business.plan_expiry:
        return "Trial"
    if business.plan_expiry < datetime.utcnow():
        return "Expired"
    return business.plan_expiry.strftime("%b %d, %Y")


def initialize_paystack_transaction(email: str, amount_ngn: int, callback_url: str, reference: str) -> Optional[str]:
    secret_key = os.getenv("PAYSTACK_SECRET_KEY")
    if not secret_key:
        return None
    headers = {
        "Authorization": f"Bearer {secret_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "email": email,
        "amount": amount_ngn * 100,
        "callback_url": callback_url,
        "reference": reference,
        "currency": "NGN",
    }
    try:
        response = httpx.post("https://api.paystack.co/transaction/initialize", json=payload, headers=headers, timeout=30.0)
        data = response.json()
        if data.get("status"):
            return data["data"]["authorization_url"]
    except Exception:
        return None
    return None


def verify_paystack_signature(request: Request, payload: bytes) -> bool:
    secret_key = os.getenv("PAYSTACK_SECRET_KEY")
    if not secret_key:
        return False
    signature = request.headers.get("x-paystack-signature", "")
    computed = hmac.new(secret_key.encode(), payload, hashlib.sha512).hexdigest()
    return hmac.compare_digest(computed, signature)


def create_plan_seed_data(db) -> None:
    if db.query(Plan).count() == 0:
        plans = [
            Plan(name="Starter", price_ngn=7500, branch_access=0, description="Single-location plan with menu and order management. WhatsApp messaging costs included."),
            Plan(name="Growth", price_ngn=20000, branch_access=1, description="Full branch access, advanced menus, and premium workflows. WhatsApp messaging costs included."),
        ]
        db.add_all(plans)
        db.commit()


def build_paystack_reference(business_id: int, plan_id: int) -> str:
    timestamp = int(datetime.utcnow().timestamp())
    return f"COLLXCT-{business_id}-{plan_id}-{timestamp}"


def get_paystack_redirect(business_id: int, plan_id: int, amount: int, auto_renew: bool, current_user: User) -> str:
    reference = build_paystack_reference(business_id, plan_id)
    callback = os.getenv("PAYSTACK_CALLBACK_URL", "http://localhost:8001/paystack/webhook")
    auth_url = initialize_paystack_transaction(current_user.email, amount, callback, reference)
    if auth_url:
        return auth_url
    return f"/paystack/simulate?business_id={business_id}&plan_id={plan_id}&amount={amount}&auto_renew={int(auto_renew)}&reference={reference}"


def upsert_payment(db, business_id: int, user_email: str, plan_id: int, amount: int, reference: str, auto_renew: bool) -> Payment:
    payment = Payment(business_id=business_id, user_email=user_email, plan_id=plan_id, amount=amount, reference=reference, status="initialized", auto_renew=1 if auto_renew else 0)
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


def apply_payment_success(db, reference: str, status: str = "success") -> Optional[Payment]:
    payment = db.query(Payment).filter(Payment.reference == reference).one_or_none()
    if not payment:
        return None
    payment.status = status
    payment.updated_at = datetime.utcnow()
    business = db.query(Business).filter(Business.id == payment.business_id).one_or_none()
    plan = get_plan(db, payment.plan_id)
    if business and plan:
        business.plan_id = plan.id
        business.plan_status = "active"
        business.plan_expiry = datetime.utcnow() + timedelta(days=30)
        business.auto_renew = payment.auto_renew
    db.commit()
    return payment


def format_cart_summary(cart_json: Optional[str]) -> str:
    if not cart_json:
        return ""
    try:
        payload = json.loads(cart_json)
    except Exception:
        return ""

    if not isinstance(payload, list):
        return ""

    summaries = []
    for item in payload:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("item_name") or "").strip()
            description = str(item.get("description") or "").strip()
            if name and description:
                summaries.append(f"{name}: {description}")
            elif name:
                summaries.append(name)
    return " | ".join(summaries)


def seed_data() -> None:
    db = SessionLocal()
    try:
        if db.query(Business).count() == 0:
            business = Business(name="Demo Shop", whatsapp_number="+15551234567", owner_notify_number="+15559876543")
            db.add(business)
            db.commit()
            db.refresh(business)
            branch = Branch(business_id=business.id, name="Main Branch", address="Lagos")
            db.add(branch)
            db.commit()
            db.refresh(branch)
            categories = [
                Category(business_id=business.id, name="Meals"),
                Category(business_id=business.id, name="Drinks"),
            ]
            db.add_all(categories)
            db.commit()
            meal_category = db.query(Category).filter(Category.business_id == business.id, Category.name == "Meals").one_or_none()
            drink_category = db.query(Category).filter(Category.business_id == business.id, Category.name == "Drinks").one_or_none()
            menu_items = [
                MenuItem(business_id=business.id, branch_id=branch.id, category_id=meal_category.id if meal_category else None, name="Jollof Rice", description="Fragrant rice with rich tomato stew and spices", price=1500, is_active=1, is_out_of_stock=0),
                MenuItem(business_id=business.id, branch_id=branch.id, category_id=meal_category.id if meal_category else None, name="Fried Chicken", description="Golden crispy fried chicken served hot", price=2500, is_active=1, is_out_of_stock=0),
                MenuItem(business_id=business.id, branch_id=branch.id, category_id=meal_category.id if meal_category else None, name="Plantain", description="Sweet fried plantain with a soft center", price=800, is_active=1, is_out_of_stock=1),
                MenuItem(business_id=business.id, branch_id=branch.id, category_id=drink_category.id if drink_category else None, name="Coke", description="Chilled soft drink with a refreshing finish", price=500, is_active=1, is_out_of_stock=1),
            ]
            db.add_all(menu_items)
            db.commit()

        if db.query(User).filter(User.role == "admin").count() == 0:
            admin_email = os.getenv("ADMIN_EMAIL", "olufemi.mohammed11@gmail.com")
            admin_password = os.getenv("ADMIN_PASSWORD", "Pass@12345")
            db.add(User(email=admin_email, password_hash=hash_password(admin_password), role="admin", business_id=None))
            db.commit()
        if db.query(Plan).count() == 0:
            create_plan_seed_data(db)
    finally:
        db.close()


seed_data()


CONV_NEW = "new"
CONV_CATEGORY = "await_category"
CONV_ITEM = "await_item"
CONV_ADDRESS = "await_address"
CONV_AWAITING_PAYMENT = "awaiting_payment"
RESET_WORDS = {"hi", "hello", "hey", "start", "menu", "restart"}
STALE_CONVERSATION_AFTER = timedelta(hours=24)
STALE_RESET_STAGES = {CONV_CATEGORY, CONV_ITEM, CONV_ADDRESS}


def normalize_whatsapp_number(value: Optional[str]) -> str:
    if not value:
        return ""
    return value.replace("whatsapp:", "").strip()


def send_whatsapp_message(to_number: str, body: str, from_number: Optional[str] = None) -> bool:
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = from_number or os.getenv("TWILIO_WHATSAPP_NUMBER")
    if not account_sid or not auth_token or not from_number:
        return False
    to = to_number if to_number.startswith("whatsapp:") else f"whatsapp:{to_number}"
    from_ = from_number if from_number.startswith("whatsapp:") else f"whatsapp:{from_number}"
    try:
        client = TwilioClient(account_sid, auth_token)
        client.messages.create(from_=from_, to=to, body=body)
        return True
    except Exception:
        return False


RECEIPT_EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "application/pdf": "pdf"}


def save_payment_receipt(order_id: int, media_url: str) -> Optional[str]:
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    if not account_sid or not auth_token:
        return None
    try:
        response = httpx.get(media_url, auth=(account_sid, auth_token), timeout=30.0)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").split(";")[0].strip()
        extension = RECEIPT_EXTENSIONS.get(content_type, "bin")
        filename = f"order_{order_id}_{int(datetime.utcnow().timestamp())}.{extension}"
        with open(os.path.join(RECEIPTS_DIR, filename), "wb") as receipt_file:
            receipt_file.write(response.content)
        return filename
    except Exception:
        return None


def verify_twilio_signature(request: Request, form_params: Dict[str, str]) -> bool:
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    if not auth_token:
        return True
    signature = request.headers.get("x-twilio-signature", "")
    if not signature:
        return False
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.hostname or ""))
    port = request.headers.get("x-forwarded-port", "")
    default_port = "443" if scheme == "https" else "80"
    if port and port != default_port and ":" not in host:
        host = f"{host}:{port}"
    url = f"{scheme}://{host}{request.url.path}"
    validator = RequestValidator(auth_token)
    return validator.validate(url, form_params, signature)


def resolve_webhook_business(db, to_number: str) -> Optional[Business]:
    if to_number:
        business = db.query(Business).filter(Business.whatsapp_number == to_number).one_or_none()
        if business:
            return business
    return db.query(Business).order_by(Business.id).first()


def get_or_create_conversation(db, phone_number: str, business_id: int) -> Conversation:
    conversation = (
        db.query(Conversation)
        .filter(Conversation.phone_number == phone_number, Conversation.business_id == business_id)
        .one_or_none()
    )
    if conversation is None:
        conversation = Conversation(phone_number=phone_number, business_id=business_id, stage=CONV_NEW, cart_json="[]")
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
    return conversation


def active_categories_for_business(db, business_id: int) -> List[Category]:
    categories = db.query(Category).filter(Category.business_id == business_id).order_by(Category.id).all()
    return [c for c in categories if active_items_for_category(db, business_id, c.id)]


def active_items_for_category(db, business_id: int, category_id: int) -> List[MenuItem]:
    return (
        db.query(MenuItem)
        .filter(
            MenuItem.business_id == business_id,
            MenuItem.category_id == category_id,
            MenuItem.is_active == 1,
            MenuItem.is_out_of_stock == 0,
        )
        .order_by(MenuItem.id)
        .all()
    )


def parse_choice(text: str) -> Optional[int]:
    text = text.strip()
    return int(text) if text.isdigit() else None


def format_category_menu(categories: List[Category]) -> str:
    lines = [f"{i}) {category.name}" for i, category in enumerate(categories, start=1)]
    return "Please choose a category by replying with a number:\n" + "\n".join(lines)


def format_item_menu(items: List[MenuItem], category_name: str) -> str:
    lines = [f"{i}) {item.name} - N{item.price}" for i, item in enumerate(items, start=1)]
    return (
        f"{category_name} menu:\n" + "\n".join(lines) + "\n\n"
        "Reply with a number to add an item to your cart, 'cart' to view your cart, "
        "or 'checkout' when you're ready to order."
    )


def load_cart(cart_json: Optional[str]) -> List[Dict[str, object]]:
    if not cart_json:
        return []
    try:
        data = json.loads(cart_json)
    except Exception:
        return []
    return data if isinstance(data, list) else []


def cart_total(cart: List[Dict[str, object]]) -> int:
    total = 0
    for entry in cart:
        try:
            total += int(entry.get("price", 0)) * int(entry.get("qty", 1))
        except Exception:
            continue
    return total


def format_cart_lines(cart: List[Dict[str, object]]) -> str:
    lines = []
    for entry in cart:
        qty = entry.get("qty", 1)
        price = entry.get("price", 0)
        lines.append(f"{qty} x {entry.get('name', 'Item')} - N{int(price) * int(qty)}")
    return "\n".join(lines)


def build_greeting_reply(db, business: Business, conversation: Conversation) -> str:
    categories = active_categories_for_business(db, business.id)
    conversation.category_id = None
    if not categories:
        conversation.stage = CONV_NEW
        return f"Hi! Thanks for reaching out to {business.name}. We don't have any items available right now, please check back soon."
    conversation.stage = CONV_CATEGORY
    return f"Hi! Welcome to {business.name}. " + format_category_menu(categories)


def handle_webhook_message(db, business: Business, conversation: Conversation, message: str, media_url: str = "") -> str:
    normalized = message.strip().lower()

    if (
        conversation.stage in STALE_RESET_STAGES
        and conversation.updated_at
        and datetime.utcnow() - conversation.updated_at > STALE_CONVERSATION_AFTER
    ):
        conversation.stage = CONV_NEW
        conversation.cart_json = "[]"
        conversation.category_id = None

    conversation.updated_at = datetime.utcnow()
    db.commit()

    if normalized in RESET_WORDS or not conversation.stage:
        conversation.cart_json = "[]"
        conversation.address = None
        reply = build_greeting_reply(db, business, conversation)
        db.commit()
        return reply

    if conversation.stage == CONV_CATEGORY:
        categories = active_categories_for_business(db, business.id)
        index = parse_choice(normalized)
        if not categories:
            conversation.stage = CONV_NEW
            db.commit()
            return f"Sorry, {business.name} doesn't have any items available right now. Please check back soon."
        if index is None or index < 1 or index > len(categories):
            db.commit()
            return "Sorry, I didn't understand that. " + format_category_menu(categories)
        category = categories[index - 1]
        items = active_items_for_category(db, business.id, category.id)
        conversation.category_id = category.id
        conversation.stage = CONV_ITEM
        db.commit()
        return format_item_menu(items, category.name)

    if conversation.stage == CONV_ITEM:
        if normalized == "cart":
            cart = load_cart(conversation.cart_json)
            if not cart:
                return "Your cart is empty. Reply with a number to add an item."
            return f"Your cart:\n{format_cart_lines(cart)}\n\nTotal: N{cart_total(cart)}\n\nReply 'checkout' to place your order or add another item number."
        if normalized in {"checkout", "done"}:
            cart = load_cart(conversation.cart_json)
            if not cart:
                return "Your cart is empty. Please add at least one item before checking out."
            conversation.stage = CONV_ADDRESS
            db.commit()
            return "Great! Please reply with your delivery address."
        if normalized in {"back", "categories"}:
            reply = build_greeting_reply(db, business, conversation)
            db.commit()
            return reply
        items = active_items_for_category(db, business.id, conversation.category_id) if conversation.category_id else []
        index = parse_choice(normalized)
        if index is None or index < 1 or index > len(items):
            category = db.query(Category).filter(Category.id == conversation.category_id).one_or_none()
            return "Sorry, I didn't understand that. " + format_item_menu(items, category.name if category else "Menu")
        item = items[index - 1]
        cart = load_cart(conversation.cart_json)
        for entry in cart:
            if entry.get("item_id") == item.id:
                entry["qty"] = int(entry.get("qty", 1)) + 1
                break
        else:
            cart.append({"item_id": item.id, "name": item.name, "description": item.description or "", "price": item.price, "qty": 1})
        conversation.cart_json = json.dumps(cart)
        db.commit()
        return f"Added {item.name} to your cart. Reply with another number to add more, 'cart' to view your cart, or 'checkout' to place your order."

    if conversation.stage == CONV_ADDRESS:
        address = message.strip()
        if not address:
            return "Please share a delivery address so we can complete your order."
        cart = load_cart(conversation.cart_json)
        subtotal = cart_total(cart)
        order = Order(
            business_id=business.id,
            branch_id=conversation.branch_id,
            customer_phone=conversation.phone_number,
            items_json=conversation.cart_json or "[]",
            total=subtotal,
            delivery_fee=0,
            address=address,
            status="awaiting_delivery_fee",
        )
        db.add(order)
        conversation.cart_json = "[]"
        conversation.address = address
        conversation.category_id = None
        conversation.stage = CONV_AWAITING_PAYMENT
        db.commit()
        return (
            f"Thanks! Here's your order:\n{format_cart_lines(cart)}\nSubtotal: N{subtotal}\nDelivery to: {address}\n\n"
            "We're confirming your delivery fee now and will send your full total and payment details shortly."
        )

    if conversation.stage == CONV_AWAITING_PAYMENT:
        order = (
            db.query(Order)
            .filter(Order.customer_phone == conversation.phone_number, Order.business_id == business.id)
            .order_by(Order.id.desc())
            .first()
        )
        if not order:
            reply = build_greeting_reply(db, business, conversation)
            db.commit()
            return reply
        if order.status == "awaiting_delivery_fee":
            if normalized == "cancel":
                order.status = "cancelled"
                conversation.stage = CONV_NEW
                conversation.address = None
                db.commit()
                return "Your order has been cancelled. Reply 'hi' anytime to start a new order."
            return "We're still confirming your delivery fee — hang tight, we'll send your total and payment details shortly."
        if order.status == "awaiting_payment":
            if normalized == "cancel":
                order.status = "cancelled"
                conversation.stage = CONV_NEW
                conversation.address = None
                db.commit()
                return "Your order has been cancelled. Reply 'hi' anytime to start a new order."
            if not media_url and not message.strip():
                return "Please reply with confirmation that you've made the transfer — a text message or a photo of your receipt works."
            if media_url:
                receipt_filename = save_payment_receipt(order.id, media_url)
                if receipt_filename:
                    order.payment_receipt_path = receipt_filename
            if message.strip():
                order.payment_proof_text = message.strip()
            order.status = "payment_claimed"
            conversation.stage = CONV_NEW
            conversation.address = None
            db.commit()
            if business.owner_notify_number:
                send_whatsapp_message(
                    business.owner_notify_number,
                    f"New payment claim for order #{order.id}: N{order.total} from {order.customer_phone}. Check your bank alert and mark it paid on the dashboard.",
                    from_number=business.whatsapp_number,
                )
            return "Thanks! We've let the business know — they'll confirm your payment shortly."
        return "We've already received your payment info for this order. The business will confirm shortly."

    reply = build_greeting_reply(db, business, conversation)
    db.commit()
    return reply


@app.get("/health")
def health_check() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request) -> Response:
    content_type = request.headers.get("content-type", "")
    is_twilio = "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type

    media_url = ""
    if is_twilio:
        form = await request.form()
        form_params = {key: str(value) for key, value in form.multi_items()}
        if not verify_twilio_signature(request, form_params):
            return Response(content="Invalid Twilio signature", status_code=403)
        from_number = normalize_whatsapp_number(str(form.get("From", "")))
        message = str(form.get("Body", ""))
        to_number = normalize_whatsapp_number(str(form.get("To", "")))
        if int(form.get("NumMedia", "0") or 0) > 0:
            media_url = str(form.get("MediaUrl0", ""))
    else:
        payload = await request.json()
        from_number = normalize_whatsapp_number(str(payload.get("from", "")))
        message = str(payload.get("message", ""))
        to_number = normalize_whatsapp_number(payload.get("to"))

    if not from_number:
        reply = "Sorry, we couldn't identify your number. Please try again."
    else:
        db = SessionLocal()
        try:
            business = resolve_webhook_business(db, to_number)
            if not business:
                reply = "Sorry, this service isn't available right now."
            else:
                conversation = get_or_create_conversation(db, from_number, business.id)
                reply = handle_webhook_message(db, business, conversation, message, media_url)
        finally:
            db.close()

    if is_twilio:
        twiml = f"<?xml version='1.0' encoding='UTF-8'?><Response><Message>{escape(reply)}</Message></Response>"
        return Response(content=twiml, media_type="text/xml")
    return Response(content=json.dumps({"reply": reply}), media_type="application/json")


@app.get("/", response_class=HTMLResponse)
def homepage(request: Request) -> HTMLResponse:
    body = """
    <div class="hero">
      <div class="eyebrow">Recbot CRM</div>
      <h1>Run your business from a premium WhatsApp command center.</h1>
      <p>Launch orders, manage branches, oversee menus, and keep your team aligned with one elegant, high-tech dashboard.</p>
      <div class="stack">
        <div>
          <span class="pill">⚡ Live analytics</span>
          <span class="pill">📦 Menu control</span>
          <span class="pill">💬 Conversation flow</span>
        </div>
        <div>
          <a class="btn primary" href="/login">Open portal</a>
        </div>
      </div>
    </div>
    <div class="grid">
      <div class="card metric">
        <span class="label">Operations</span>
        <span class="value">Instant setup</span>
      </div>
      <div class="card metric">
        <span class="label">Automation</span>
        <span class="value">Smart workflows</span>
      </div>
      <div class="card metric">
        <span class="label">Visibility</span>
        <span class="value">Real-time overview</span>
      </div>
    </div>
    <div class="card">
      <h2>What makes this portal feel premium</h2>
      <ul>
        <li>Dark, modern dashboard styling with layered cards and glass surfaces</li>
        <li>Dedicated admin and business-owner experiences</li>
        <li>Fast onboarding for business owners through the admin console</li>
      </ul>
    </div>
    """
    return render_page("Recbot CRM", body, nav_html=make_nav(get_current_user(request)))


@app.get("/owner/portal", response_class=HTMLResponse)
def owner_portal(request: Request) -> HTMLResponse:
    current_user = get_current_user(request)
    if not current_user or current_user.role not in {"business_owner", "business-owner", "owner"}:
        return RedirectResponse(url="/login", status_code=303)
    if current_user.business_id:
        return RedirectResponse(url=f"/business/{current_user.business_id}/dashboard", status_code=303)
    body = """
    <div class="card">
      <h2>Your business is not linked yet</h2>
      <p>Ask your administrator to attach your owner account to a business so the dashboard can open here.</p>
    </div>
    """
    return render_page("Owner Portal", body, nav_html=make_nav(current_user))


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    body = """
    <div class="auth-shell">
      <div class="auth-hero">
        <div class="eyebrow">Recbot CRM</div>
        <h2>Welcome back</h2>
        <p>Sign in to manage your storefront, menus, subscriptions, and WhatsApp ordering flow.</p>
      </div>
      <div class="card auth-form">
        <h2>Secure sign in</h2>
        <p class="form-hint">Use your workspace email and password to continue.</p>
        <form method="post" action="/login">
          <div class="form-row">
            <input name="email" type="email" placeholder="Email" required />
            <input name="password" type="password" placeholder="Password" required />
          </div>
          <div class="form-actions">
            <button type="submit">Login</button>
          </div>
        </form>
      </div>
    </div>
    """
    return render_page("Login", body, nav_html=make_nav(get_current_user(request)))


@app.post("/login")
def login_submit(response: Response, email: str = Form(...), password: str = Form(...)) -> RedirectResponse:
    db = SessionLocal()
    try:
        user = get_user_by_email(db, email)
        if user and verify_password(password, user.password_hash):
            token = create_auth_token(email)
            if user.role == "admin":
                redirect_url = "/admin/"
            elif user.role in {"business_owner", "business-owner", "owner"}:
                redirect_url = f"/owner/portal" if not user.business_id else f"/business/{user.business_id}/dashboard"
            else:
                redirect_url = "/"
            redirect = RedirectResponse(url=redirect_url, status_code=303)
            redirect.set_cookie(key="auth_token", value=token, httponly=True)
            return redirect
    finally:
        db.close()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request) -> HTMLResponse:
    current_user = get_current_user(request)
    if not current_user or current_user.role != "admin":
        body = """
        <div class="auth-shell">
          <div class="auth-hero">
            <div class="eyebrow">Admin access</div>
            <h2>Owner onboarding</h2>
            <p>Only administrators can create new business-owner accounts here.</p>
          </div>
          <div class="card auth-form">
            <h2>Access required</h2>
            <p class="form-hint">Sign in as an admin to start onboarding a new business owner.</p>
            <div class="form-actions">
              <a class="btn primary" href="/login">Sign in as admin</a>
            </div>
          </div>
        </div>
        """
        return render_page("Create Business Owner", body, nav_html=make_nav(current_user))

    db = SessionLocal()
    try:
        businesses = db.query(Business).order_by(Business.name).all()
        business_options = business_options_html(businesses)
    finally:
        db.close()

    body = f"""
    <div class="auth-shell">
      <div class="auth-hero">
        <div class="eyebrow">Recbot CRM</div>
        <h2>Create business owner</h2>
        <p>Use this form to onboard a business owner and attach them to a business.</p>
      </div>
      <div class="card auth-form">
        <h2>New owner setup</h2>
        <p class="form-hint">Provide an email, password, and optionally attach an existing business.</p>
        <form method="post" action="/register">
          <div class="form-row">
            <input name="email" type="email" placeholder="Owner email" required />
            <input name="password" type="password" placeholder="Temporary password" required />
            <select name="business_id">
              <option value="">No business yet (attach later)</option>
              {business_options}
            </select>
          </div>
          <div class="form-actions">
            <button type="submit">Create owner</button>
          </div>
        </form>
      </div>
    </div>
    """
    return render_page("Create Business Owner", body, nav_html=make_nav(current_user))


@app.post("/register")
def register_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    business_id: Optional[int] = Form(default=None),
) -> RedirectResponse:
    current_user = get_current_user(request)
    if not current_user or current_user.role != "admin":
        return RedirectResponse(url="/login", status_code=303)

    db = SessionLocal()
    try:
        if get_user_by_email(db, email):
            return RedirectResponse(url="/register", status_code=303)
        password_hash = hash_password(password)
        user = User(email=email, password_hash=password_hash, role="business_owner", business_id=business_id)
        db.add(user)
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/admin/users", status_code=303)


@app.get("/logout")
def logout(response: Response) -> RedirectResponse:
    redirect = RedirectResponse(url="/", status_code=303)
    redirect.delete_cookie("auth_token")
    return redirect


@app.get("/admin/", response_class=HTMLResponse)
def admin_dashboard(request: Request) -> HTMLResponse:
    db = SessionLocal()
    try:
        businesses = db.query(Business).order_by(Business.id).all()
        orders = db.query(Order).order_by(Order.created_at.desc()).limit(10).all()
        conversations = db.query(Conversation).order_by(Conversation.updated_at.desc()).limit(10).all()
        business_list = "".join(
            f"<li><a href='/admin/businesses/{business.id}'>{escape(business.name)}</a></li>" for business in businesses
        )
        order_list = "".join(
            f"<li>{escape(db.query(Business).filter(Business.id == order.business_id).one_or_none().name or 'Unknown')} — ₦{order.total} — {escape(order.status)}</li>" for order in orders
        )
        conversation_list = "".join(
            f"<li>{escape(conversation.phone_number)} — {escape(conversation.stage)}</li>" for conversation in conversations
        )
        body = f"""
        <div class="hero">
          <div class="eyebrow">Control tower</div>
          <h1>Admin command center</h1>
          <p>Manage every business, owner, order, and conversation from one intelligent workspace.</p>
        </div>
        <div class="grid">
          <div class="card metric">
            <span class="label">Businesses</span>
            <span class="value">{len(businesses)}</span>
          </div>
          <div class="card metric">
            <span class="label">Orders</span>
            <span class="value">{len(orders)}</span>
          </div>
          <div class="card metric">
            <span class="label">Conversations</span>
            <span class="value">{len(conversations)}</span>
          </div>
        </div>
        <div class="card">
          <h3>Businesses</h3>
          <ul>{business_list}</ul>
        </div>
        <div class="card">
          <h3>Recent Orders</h3>
          <ul>{order_list}</ul>
        </div>
        <div class="card">
          <h3>Recent Conversations</h3>
          <ul>{conversation_list}</ul>
        </div>
        """
    finally:
        db.close()
    return render_page("Admin Dashboard", body, nav_html=make_nav(get_current_user(request)))


@app.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request) -> HTMLResponse:
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.id).all()
        business_names = {b.id: b.name for b in db.query(Business).all()}
        rows = "".join(
            f"<tr><td>{escape(user.email)}</td><td>{escape(user.role)}</td>"
            f"<td>{escape(business_names.get(user.business_id, '')) if user.business_id else ''}</td>"
            f"<td><a href='/admin/users/{user.id}'>Edit</a></td></tr>"
            for user in users
        )
        body = f"""
        <div class="card">
          <h3>User roster</h3>
          <div class="table-wrap"><table><tr><th>Email</th><th>Role</th><th>Business</th><th>Actions</th></tr>{rows}</table></div>
        </div>
        """
    finally:
        db.close()
    return render_page("Users", body, nav_html=make_nav(get_current_user(request)))


@app.get("/admin/users/{user_id}", response_class=HTMLResponse)
def edit_user_page(request: Request, user_id: int) -> HTMLResponse:
    current_user = get_current_user(request)
    if not current_user or current_user.role != "admin":
        return RedirectResponse(url="/login", status_code=303)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).one_or_none()
        if not user:
            return render_page("User Not Found", "<p>User not found.</p>", nav_html=make_nav(current_user))
        businesses = db.query(Business).order_by(Business.name).all()
        role_options = "".join(
            f"<option value='{role}' {'selected' if user.role == role else ''}>{role.replace('_', ' ').title()}</option>"
            for role in ("admin", "business_owner", "customer")
        )
        body = f"""
        <div class="card">
          <h3>Edit User</h3>
          <p class="form-hint">{escape(user.email)}</p>
          <form method="post" action="/admin/users/{user_id}">
            <select name="role">{role_options}</select>
            <select name="business_id">
              <option value="">No business</option>
              {business_options_html(businesses, user.business_id)}
            </select>
            <div class="form-actions">
              <button type="submit">Save User</button>
            </div>
          </form>
        </div>
        """
    finally:
        db.close()
    return render_page("Edit User", body, nav_html=make_nav(current_user))


@app.post("/admin/users/{user_id}")
def update_user(request: Request, user_id: int, role: str = Form(...), business_id: Optional[int] = Form(default=None)) -> RedirectResponse:
    current_user = get_current_user(request)
    if not current_user or current_user.role != "admin":
        return RedirectResponse(url="/login", status_code=303)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).one_or_none()
        if user:
            user.role = role
            user.business_id = business_id or None
            db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/admin/users", status_code=303)


@app.get("/admin/businesses", response_class=HTMLResponse)
def admin_businesses(request: Request) -> HTMLResponse:
    db = SessionLocal()
    try:
        businesses = db.query(Business).order_by(Business.id).all()
        rows = "".join(
            f"<tr><td><a href='/admin/businesses/{business.id}'>{escape(business.name)}</a></td><td>{escape(business.whatsapp_number)}</td><td>{escape(business.owner_notify_number or '')}</td></tr>"
            for business in businesses
        )
        body = f"""
        <div class="card">
          <h3>Create Business</h3>
          <form method="post" action="/admin/businesses">
            <input name="name" placeholder="Business Name" required />
            <input name="whatsapp_number" placeholder="WhatsApp Number" required />
            <input name="owner_notify_number" placeholder="Owner Notify Number" />
            <button type="submit">Create Business</button>
          </form>
        </div>
        <div class="card">
          <h3>Business directory</h3>
          <div class="table-wrap"><table><tr><th>Name</th><th>WhatsApp Number</th><th>Owner Notify</th></tr>{rows}</table></div>
        </div>
        """
    finally:
        db.close()
    return render_page("Businesses", body, nav_html=make_nav(get_current_user(request)))


@app.post("/admin/businesses")
def create_business(
    request: Request,
    name: str = Form(...),
    whatsapp_number: str = Form(...),
    owner_notify_number: str = Form(default=""),
) -> RedirectResponse:
    current_user = get_current_user(request)
    if not current_user or current_user.role != "admin":
        return RedirectResponse(url="/login", status_code=303)
    db = SessionLocal()
    try:
        if db.query(Business).filter(Business.whatsapp_number == whatsapp_number).first():
            return RedirectResponse(url="/admin/businesses", status_code=303)
        business = Business(name=name, whatsapp_number=whatsapp_number, owner_notify_number=owner_notify_number or None)
        db.add(business)
        db.commit()
        db.refresh(business)
    finally:
        db.close()
    return RedirectResponse(url=f"/admin/businesses/{business.id}", status_code=303)


@app.get("/admin/businesses/{business_id}", response_class=HTMLResponse)
def business_detail(request: Request, business_id: int) -> HTMLResponse:
    current_user = get_current_user(request)
    if not current_user or (current_user.role != "admin" and current_user.business_id != business_id):
        return RedirectResponse(url="/login", status_code=303)
    db = SessionLocal()
    try:
        context = get_business_context(business_id)
        business = context["business"]
        plans = db.query(Plan).order_by(Plan.price_ngn).all()
    finally:
        db.close()
    if not business:
        return render_page("Business Not Found", "<p>Business not found.</p>", nav_html=make_nav(get_current_user(request)))
    active_plan = get_active_plan(business)
    plan_name = active_plan.name if active_plan else "Starter"
    plan_description = active_plan.description if active_plan else "Choose a plan that fits your growth."
    plan_expiry_label = plan_due_label(business)
    categories_rows = "".join(f"<tr><td>{escape(category.name)}</td></tr>" for category in context["categories"])
    branches_rows = "".join(f"<tr><td>{escape(branch.name)}</td><td>{escape(branch.address or '')}</td></tr>" for branch in context["branches"])
    items_rows = "".join(
        f"<tr><td>{escape(item.name)}</td><td>{escape(item.description or '')}</td><td>₦{item.price}</td><td>{'Yes' if item.is_active == 1 else 'No'}</td><td>{'Yes' if item.is_out_of_stock == 1 else 'No'}</td><td><a href='/admin/businesses/{business.id}/items/{item.id}'>Edit</a></td></tr>" for item in context["items"]
    )
    orders_rows = "".join(render_order_row(order) for order in context["orders"])
    plan_options = "".join(
        f"<option value='{plan.id}'>{escape(plan.name)} - ₦{plan.price_ngn}</option>" for plan in plans
    )
    category_options = "".join(f"<option value='{category.id}'>{escape(category.name)}</option>" for category in context["categories"])
    branch_options = "".join(f"<option value='{branch.id}'>{escape(branch.name)}</option>" for branch in context["branches"])
    body = f"""
    <div class="hero-panel">
      <div>
        <div class="eyebrow">Business control room</div>
        <h1>{escape(business.name)}</h1>
        <p>Configure offerings, manage inventory, and keep your operation running smoothly.</p>
      </div>
      <div class="actions">
        <a class="btn primary" href="/business/{business.id}/dashboard">Owner dashboard</a>
        <a class="btn" href="/business/{business.id}/plans">Plans</a>
      </div>
    </div>
    <div class="panel-grid">
      <div class="card">
        <div class="section-head">
          <h3>Edit business profile</h3>
          <span class="status-pill">Profile</span>
        </div>
        <form method="post" action="/admin/businesses/{business.id}">
          <div class="form-row">
            <input name="name" value="{escape(business.name)}" required />
            <input name="whatsapp_number" value="{escape(business.whatsapp_number)}" required />
            <input name="owner_notify_number" value="{escape(business.owner_notify_number or '')}" placeholder="Owner notify number (for order alerts)" />
            <input name="bank_name" value="{escape(business.bank_name or '')}" placeholder="Bank name (for customer payments)" />
            <input name="bank_account_number" value="{escape(business.bank_account_number or '')}" placeholder="Bank account number" />
            <input name="bank_account_name" value="{escape(business.bank_account_name or '')}" placeholder="Account holder name" />
          </div>
          <div class="form-actions">
            <button type="submit">Save</button>
          </div>
        </form>
      </div>
      <div class="card">
        <div class="section-head">
          <h3>Subscription</h3>
          <span class="status-pill">{escape(business.plan_status or 'trial').title()}</span>
        </div>
        <p><strong>Current plan:</strong> {escape(plan_name)}</p>
        <p><strong>Expires:</strong> {escape(plan_expiry_label)}</p>
        <p>{escape(plan_description)}</p>
        <div class="form-actions">
          <a class="btn primary" href="/admin/businesses/{business.id}/plans">Manage plan</a>
        </div>
      </div>
    </div>
    <div class="panel-grid">
      <div class="card">
        <div class="section-head">
          <h3>Categories</h3>
        </div>
        <form method="post" action="/admin/businesses/{business.id}/categories">
          <input name="name" placeholder="Category Name" required />
          <div class="form-actions">
            <button type="submit">Add Category</button>
          </div>
        </form>
        <div class="table-wrap"><table><tr><th>Name</th></tr>{categories_rows}</table></div>
      </div>
      <div class="card">
        <div class="section-head">
          <h3>Branches</h3>
        </div>
        <form method="post" action="/admin/businesses/{business.id}/branches">
          <input name="name" placeholder="Branch Name" required />
          <textarea name="address" placeholder="Address"></textarea>
          <div class="form-actions">
            <button type="submit">Add Branch</button>
          </div>
        </form>
        <div class="table-wrap"><table><tr><th>Name</th><th>Address</th></tr>{branches_rows}</table></div>
      </div>
    </div>
    <div class="panel-grid">
      <div class="card">
        <div class="section-head">
          <h3>Menu Items</h3>
        </div>
        <form method="post" action="/admin/businesses/{business.id}/items">
          <input name="name" placeholder="Item Name" required />
          <textarea name="description" placeholder="Short item description"></textarea>
          <input name="price" type="number" placeholder="Price" required />
          <select name="category_id">
            <option value="">No Category</option>
            {category_options}
          </select>
          <select name="branch_id">
            <option value="">All Branches</option>
            {branch_options}
          </select>
          <label><input type="checkbox" name="is_active" checked /> Active</label>
          <label><input type="checkbox" name="is_out_of_stock" /> Out of Stock</label>
          <div class="form-actions">
            <button type="submit">Add Item</button>
          </div>
        </form>
        <div class="table-wrap"><table><tr><th>Name</th><th>Description</th><th>Price</th><th>Active</th><th>Out of Stock</th><th>Actions</th></tr>{items_rows}</table></div>
      </div>
      <div class="card">
        <div class="section-head">
          <h3>Orders</h3>
        </div>
        <div class="table-wrap"><table><tr><th>Order</th><th>Customer</th><th>Address</th><th>Total</th><th>Age</th><th>Status</th></tr>{orders_rows}</table></div>
      </div>
    </div>
    """
    return render_page(f"{business.name} Configuration", body, nav_html=make_nav(get_current_user(request)))


@app.post("/business/{business_id}/purchase-plan")
def purchase_plan(
    request: Request,
    business_id: int,
    plan_id: int = Form(...),
    auto_renew: Optional[str] = Form(default=None),
) -> RedirectResponse:
    current_user = get_current_user(request)
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    db = SessionLocal()
    try:
        business = get_business(db, business_id)
        plan = get_plan(db, plan_id)
        if not business or not plan:
            return RedirectResponse(url=f"/admin/businesses/{business_id}", status_code=303)
        auto_renew_flag = auto_renew == "1"
        reference = build_paystack_reference(business.id, plan.id)
        upsert_payment(db, business.id, current_user.email, plan.id, plan.price_ngn, reference, auto_renew_flag)
    finally:
        db.close()

    auth_url = get_paystack_redirect(business.id, plan.id, plan.price_ngn, auto_renew_flag, current_user)
    return RedirectResponse(url=auth_url, status_code=303)


@app.get("/paystack/simulate", response_class=HTMLResponse)
def paystack_simulate(
    business_id: int,
    plan_id: int,
    amount: int,
    auto_renew: int = 0,
    reference: str = "",
) -> HTMLResponse:
    db = SessionLocal()
    try:
        payment = db.query(Payment).filter(Payment.reference == reference).one_or_none()
        if payment:
            apply_payment_success(db, reference)
    finally:
        db.close()
    body = f"<div class=\"card\"><h3>Payment completed</h3><p>Your plan purchase for business {business_id} has been recorded.</p><p><a href=\"/admin/businesses/{business_id}\">Return to business dashboard</a></p></div>"
    return render_page("Payment Simulated", body, nav_html=make_nav(None))


@app.post("/paystack/webhook")
async def paystack_webhook(request: Request) -> Response:
    payload = await request.body()
    if not verify_paystack_signature(request, payload):
        return Response(status_code=400)
    data = json.loads(payload.decode("utf-8") if isinstance(payload, bytes) else payload)
    event = data.get("event")
    if event == "charge.success":
        reference = data.get("data", {}).get("reference")
        if reference:
            db = SessionLocal()
            try:
                apply_payment_success(db, reference)
            finally:
                db.close()
    return Response(status_code=200)


@app.post("/admin/businesses/{business_id}")
def update_business(
    request: Request,
    business_id: int,
    name: str = Form(...),
    whatsapp_number: str = Form(...),
    owner_notify_number: str = Form(default=""),
    bank_name: str = Form(default=""),
    bank_account_number: str = Form(default=""),
    bank_account_name: str = Form(default=""),
) -> RedirectResponse:
    current_user = get_current_user(request)
    if not current_user or (current_user.role != "admin" and current_user.business_id != business_id):
        return RedirectResponse(url="/login", status_code=303)
    db = SessionLocal()
    try:
        business = get_business(db, business_id)
        if business:
            business.name = name
            business.whatsapp_number = whatsapp_number
            business.owner_notify_number = owner_notify_number or None
            business.bank_name = bank_name or None
            business.bank_account_number = bank_account_number or None
            business.bank_account_name = bank_account_name or None
            db.commit()
    finally:
        db.close()
    return RedirectResponse(url=f"/admin/businesses/{business_id}", status_code=303)


@app.post("/admin/businesses/{business_id}/categories")
def create_category(request: Request, business_id: int, name: str = Form(...)) -> RedirectResponse:
    current_user = get_current_user(request)
    if not current_user or (current_user.role != "admin" and current_user.business_id != business_id):
        return RedirectResponse(url="/login", status_code=303)
    db = SessionLocal()
    try:
        db.add(Category(business_id=business_id, name=name))
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url=f"/admin/businesses/{business_id}", status_code=303)


@app.post("/admin/businesses/{business_id}/branches")
def create_branch(request: Request, business_id: int, name: str = Form(...), address: str = Form(default="")) -> RedirectResponse:
    current_user = get_current_user(request)
    if not current_user or (current_user.role != "admin" and current_user.business_id != business_id):
        return RedirectResponse(url="/login", status_code=303)
    db = SessionLocal()
    try:
        db.add(Branch(business_id=business_id, name=name, address=address or None))
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url=f"/admin/businesses/{business_id}", status_code=303)


@app.post("/admin/businesses/{business_id}/items")
def create_menu_item(
    request: Request,
    business_id: int,
    name: str = Form(...),
    description: Optional[str] = Form(default=None),
    price: int = Form(...),
    category_id: Optional[int] = Form(default=None),
    branch_id: Optional[int] = Form(default=None),
    is_active: Optional[str] = Form(default=None),
    is_out_of_stock: Optional[str] = Form(default=None),
) -> RedirectResponse:
    current_user = get_current_user(request)
    if not current_user or (current_user.role != "admin" and current_user.business_id != business_id):
        return RedirectResponse(url="/login", status_code=303)
    db = SessionLocal()
    try:
        db.add(
            MenuItem(
                business_id=business_id,
                category_id=category_id or None,
                branch_id=branch_id or None,
                name=name,
                description=description or None,
                price=price,
                is_active=1 if is_active else 0,
                is_out_of_stock=1 if is_out_of_stock else 0,
            )
        )
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url=f"/admin/businesses/{business_id}", status_code=303)


@app.get("/admin/businesses/{business_id}/items/{item_id}", response_class=HTMLResponse)
def edit_menu_item_page(request: Request, business_id: int, item_id: int) -> HTMLResponse:
    current_user = get_current_user(request)
    if not current_user or (current_user.role != "admin" and current_user.business_id != business_id):
        return RedirectResponse(url="/login", status_code=303)
    db = SessionLocal()
    try:
        business = get_business(db, business_id)
        item = db.query(MenuItem).filter(MenuItem.id == item_id, MenuItem.business_id == business_id).one_or_none()
        if not business or not item:
            return render_page("Item Not Found", "<p>Item not found.</p>", nav_html=make_nav(get_current_user(request)))
        categories = db.query(Category).filter(Category.business_id == business_id).all()
        branches = db.query(Branch).filter(Branch.business_id == business_id).all()
        category_options = "".join(
            f"<option value='{category.id}' {'selected' if item.category_id == category.id else ''}>{escape(category.name)}</option>"
            for category in categories
        )
        branch_options = "".join(
            f"<option value='{branch.id}' {'selected' if item.branch_id == branch.id else ''}>{escape(branch.name)}</option>"
            for branch in branches
        )
        active_checked = "checked" if item.is_active == 1 else ""
        stock_checked = "checked" if item.is_out_of_stock == 1 else ""
        body = f"""
        <div class="card">
          <h3>Edit Item</h3>
          <form method="post" action="/admin/businesses/{business_id}/items/{item_id}">
            <input name="name" value="{escape(item.name)}" required />
            <textarea name="description" placeholder="Short item description">{escape(item.description or '')}</textarea>
            <input name="price" type="number" value="{item.price}" required />
            <select name="category_id">
              <option value="">No Category</option>
              {category_options}
            </select>
            <select name="branch_id">
              <option value="">All Branches</option>
              {branch_options}
            </select>
            <label><input type="checkbox" name="is_active" {active_checked} /> Active</label>
            <label><input type="checkbox" name="is_out_of_stock" {stock_checked} /> Out of Stock</label>
            <button type="submit">Save Item</button>
          </form>
        </div>
        """
    finally:
        db.close()
    return render_page("Edit Item", body, nav_html=make_nav(get_current_user(request)))


@app.post("/admin/businesses/{business_id}/items/{item_id}")
def update_menu_item(
    request: Request,
    business_id: int,
    item_id: int,
    name: str = Form(...),
    description: Optional[str] = Form(default=None),
    price: int = Form(...),
    category_id: Optional[int] = Form(default=None),
    branch_id: Optional[int] = Form(default=None),
    is_active: Optional[str] = Form(default=None),
    is_out_of_stock: Optional[str] = Form(default=None),
) -> RedirectResponse:
    current_user = get_current_user(request)
    if not current_user or (current_user.role != "admin" and current_user.business_id != business_id):
        return RedirectResponse(url="/login", status_code=303)
    db = SessionLocal()
    try:
        item = db.query(MenuItem).filter(MenuItem.id == item_id, MenuItem.business_id == business_id).one_or_none()
        if item:
            item.name = name
            item.description = description or None
            item.price = price
            item.category_id = category_id or None
            item.branch_id = branch_id or None
            item.is_active = 1 if is_active else 0
            item.is_out_of_stock = 1 if is_out_of_stock else 0
            db.commit()
    finally:
        db.close()
    return RedirectResponse(url=f"/admin/businesses/{business_id}", status_code=303)


def format_age(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    minutes = int((datetime.utcnow() - dt).total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def render_order_row(order: Order, show_business_name: bool = False, business_name: str = "") -> str:
    business_cell = f"<td>{escape(business_name)}</td>" if show_business_name else ""
    is_pending = order.status not in {"paid", "cancelled"}
    is_stale = is_pending and order.created_at and (datetime.utcnow() - order.created_at) > timedelta(hours=2)
    age_style = "color:var(--danger);font-weight:700;" if is_stale else "color:var(--muted);"
    age_cell = f"<td style='{age_style}'>{format_age(order.created_at)}</td>"
    if order.status == "awaiting_delivery_fee":
        action_cell = (
            f"<form method='post' action='/orders/{order.id}/delivery-fee' style='margin:0;display:flex;gap:6px;align-items:center;'>"
            f"<input name='delivery_fee' type='number' min='0' placeholder='Delivery fee' required style='margin:0;max-width:140px;' />"
            f"<button type='submit' style='margin:0;'>Send total</button>"
            f"</form>"
        )
    elif order.status == "awaiting_payment":
        action_cell = "<span class='pill'>Awaiting customer payment</span>"
    elif order.status == "payment_claimed":
        proof_bits = []
        if order.payment_proof_text:
            proof_bits.append(escape(order.payment_proof_text))
        if order.payment_receipt_path:
            proof_bits.append(f"<a href='/orders/{order.id}/receipt' target='_blank'>View receipt</a>")
        proof_html = " &middot; ".join(proof_bits) if proof_bits else "<span class='form-hint'>No proof attached</span>"
        action_cell = (
            f"<div class='stack' style='gap:6px;'>"
            f"<span class='pill'>Payment claimed</span>"
            f"<span class='form-hint'>{proof_html}</span>"
            f"<form method='post' action='/orders/{order.id}/mark-paid' style='margin:0;'>"
            f"<button type='submit'>Mark paid</button>"
            f"</form>"
            f"</div>"
        )
    elif order.status == "paid":
        receipt_link = f"<br/><a href='/orders/{order.id}/receipt' target='_blank'>View receipt</a>" if order.payment_receipt_path else ""
        action_cell = f"<span class='status-pill'>Paid</span>{receipt_link}"
    elif order.status == "cancelled":
        action_cell = "<span class='pill'>Cancelled</span>"
    else:
        action_cell = escape(order.status)
    return (
        f"<tr>{business_cell}<td>#{order.id}</td><td>{escape(order.customer_phone)}</td><td>{escape(order.address)}</td>"
        f"<td>₦{order.total}</td>{age_cell}<td>{action_cell}</td></tr>"
    )


@app.post("/orders/{order_id}/delivery-fee")
def set_order_delivery_fee(request: Request, order_id: int, delivery_fee: int = Form(...)) -> RedirectResponse:
    current_user = get_current_user(request)
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == order_id).one_or_none()
        if not order:
            return RedirectResponse(url="/admin/orders", status_code=303)
        if not current_user or (current_user.role != "admin" and current_user.business_id != order.business_id):
            return RedirectResponse(url="/login", status_code=303)
        business = get_business(db, order.business_id)
        items_subtotal = cart_total(load_cart(order.items_json))
        order.delivery_fee = delivery_fee
        order.total = items_subtotal + delivery_fee
        order.status = "awaiting_payment"
        db.commit()

        bank_lines = []
        if business and business.bank_name:
            bank_lines.append(f"Bank: {business.bank_name}")
        if business and business.bank_account_number:
            bank_lines.append(f"Account number: {business.bank_account_number}")
        if business and business.bank_account_name:
            bank_lines.append(f"Account name: {business.bank_account_name}")
        bank_info = "\n".join(bank_lines) if bank_lines else "Please contact us for payment details."

        send_whatsapp_message(
            order.customer_phone,
            f"Your order #{order.id} total is N{order.total} (including N{delivery_fee} delivery).\n\n"
            f"Please pay to:\n{bank_info}\n\n"
            "Once you've paid, reply here with confirmation or a photo of your receipt.",
            from_number=business.whatsapp_number if business else None,
        )
        business_id = order.business_id
    finally:
        db.close()
    if current_user.role == "admin":
        return RedirectResponse(url="/admin/orders", status_code=303)
    return RedirectResponse(url=f"/business/{business_id}/dashboard", status_code=303)


@app.post("/orders/{order_id}/mark-paid")
def mark_order_paid(request: Request, order_id: int) -> RedirectResponse:
    current_user = get_current_user(request)
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == order_id).one_or_none()
        if not order:
            return RedirectResponse(url="/admin/orders", status_code=303)
        if not current_user or (current_user.role != "admin" and current_user.business_id != order.business_id):
            return RedirectResponse(url="/login", status_code=303)
        order.status = "paid"
        db.commit()
        business_id = order.business_id
    finally:
        db.close()
    if current_user.role == "admin":
        return RedirectResponse(url="/admin/orders", status_code=303)
    return RedirectResponse(url=f"/business/{business_id}/dashboard", status_code=303)


@app.get("/orders/{order_id}/receipt")
def get_order_receipt(request: Request, order_id: int):
    current_user = get_current_user(request)
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == order_id).one_or_none()
        if not order or not order.payment_receipt_path:
            return RedirectResponse(url="/login", status_code=303)
        if not current_user or (current_user.role != "admin" and current_user.business_id != order.business_id):
            return RedirectResponse(url="/login", status_code=303)
        file_path = os.path.join(RECEIPTS_DIR, order.payment_receipt_path)
    finally:
        db.close()
    if not os.path.exists(file_path):
        return RedirectResponse(url="/login", status_code=303)
    return FileResponse(file_path)


@app.get("/admin/orders", response_class=HTMLResponse)
def admin_orders(request: Request) -> HTMLResponse:
    db = SessionLocal()
    try:
        orders = db.query(Order).order_by(Order.created_at.desc()).all()
        business_names = {b.id: b.name for b in db.query(Business).all()}
        rows = "".join(render_order_row(order, show_business_name=True, business_name=business_names.get(order.business_id, "")) for order in orders)
    finally:
        db.close()
    body = f"<div class=\"card\"><div class=\"table-wrap\"><table><tr><th>Business</th><th>Order</th><th>Customer</th><th>Address</th><th>Total</th><th>Age</th><th>Status</th></tr>{rows}</table></div></div>"
    return render_page("Orders", body, nav_html=make_nav(get_current_user(request)))


@app.get("/admin/conversations", response_class=HTMLResponse)
def admin_conversations(request: Request) -> HTMLResponse:
    db = SessionLocal()
    try:
        conversations = db.query(Conversation).order_by(Conversation.updated_at.desc()).all()
        rows = "".join(
            f"<tr><td>{escape(conversation.phone_number)}</td><td>{escape(conversation.stage)}</td><td>{escape(format_cart_summary(conversation.cart_json) or (conversation.address or ''))}</td></tr>"
            for conversation in conversations
        )
    finally:
        db.close()
    body = f"<div class=\"card\"><div class=\"table-wrap\"><table><tr><th>Phone</th><th>Stage</th><th>Address</th></tr>{rows}</table></div></div>"
    return render_page("Conversations", body, nav_html=make_nav(get_current_user(request)))


@app.get("/business/{business_id}", response_class=HTMLResponse)
@app.get("/business/{business_id}/dashboard", response_class=HTMLResponse)
def business_dashboard(request: Request, business_id: int) -> HTMLResponse:
    context = get_business_context(business_id)
    business = context["business"]
    if not business:
        return render_page("Business Not Found", "<p>Business not found.</p>", nav_html=make_nav(get_current_user(request)))
    body = f"""
    <div class="hero-panel">
      <div>
        <div class="eyebrow">Owner workspace</div>
        <h1>{escape(business.name)} operations</h1>
        <p>Monitor your outlets, menu portfolio, and customer activity from a streamlined control center.</p>
      </div>
      <div class="actions">
        <a class="btn primary" href="/business/{business.id}/config">Manage setup</a>
        <a class="btn" href="/admin/businesses/{business.id}">Admin view</a>
      </div>
    </div>
    <div class="stats-grid">
      <div class="card stat-card metric">
        <span class="label">Branches</span>
        <span class="value">{len(context['branches'])}</span>
      </div>
      <div class="card stat-card metric">
        <span class="label">Categories</span>
        <span class="value">{len(context['categories'])}</span>
      </div>
      <div class="card stat-card metric">
        <span class="label">Menu items</span>
        <span class="value">{len(context['items'])}</span>
      </div>
      <div class="card stat-card metric">
        <span class="label">Orders tracked</span>
        <span class="value">{len(context['orders'])}</span>
      </div>
    </div>
    <div class="panel-grid">
      <div class="card">
        <div class="section-head">
          <h3>Quick actions</h3>
          <span class="status-pill">Fast access</span>
        </div>
        <p>Jump into setup, menus, and subscriptions in a single tap.</p>
        <div class="pill-list">
          <a class="btn primary" href="/business/{business.id}/config">Configure</a>
          <a class="btn" href="/business/{business.id}/plans">Plans</a>
        </div>
      </div>
      <div class="card">
        <div class="section-head">
          <h3>Recent activity</h3>
          <span class="status-pill">Live</span>
        </div>
        <ul>
          <li>{len(context['items'])} menu items loaded</li>
          <li>{len(context['orders'])} orders tracked</li>
          <li>{len(context['branches'])} active branches ready</li>
        </ul>
      </div>
    </div>
    """
    return render_page(f"{business.name} Dashboard", body, nav_html=make_nav(get_current_user(request)))


@app.get("/business/{business_id}/plans", response_class=HTMLResponse)
def business_plans(request: Request, business_id: int) -> HTMLResponse:
    current_user = get_current_user(request)
    if not current_user or (current_user.role != "admin" and current_user.business_id != business_id):
        return RedirectResponse(url="/login", status_code=303)

    db = SessionLocal()
    try:
        business = get_business(db, business_id)
        plans = db.query(Plan).order_by(Plan.price_ngn).all()
    finally:
        db.close()

    if not business:
        return render_page("Business Not Found", "<p>Business not found.</p>", nav_html=make_nav(current_user))

    active_plan = get_active_plan(business)
    current_plan_name = active_plan.name if active_plan else "Starter"
    current_plan_expiry = plan_due_label(business)
    cards = "".join(
        f"<div class=\"plan-card{' active' if active_plan and active_plan.id == plan.id else ''}\"><span class=\"tag\">{'Current' if active_plan and active_plan.id == plan.id else 'Recommended'}</span><h4>{escape(plan.name)}</h4><div class=\"price\">₦{plan.price_ngn}</div><p>{escape(plan.description or 'Premium tools for daily order and branch management.')}</p><p>{'Single branch access' if plan.branch_access == 0 else 'Unlimited branches'}</p><label><input type=\"radio\" name=\"plan_id\" value=\"{plan.id}\" {'checked' if idx == 0 else ''} /> Select this plan</label></div>"
        for idx, plan in enumerate(plans)
    )
    body = f"""
    <div class="hero">
      <div class="eyebrow">Plan management</div>
      <h1>{escape(business.name)} subscription</h1>
      <p>Choose the best Recbot CRM plan for your business and keep your WhatsApp ordering flow live.</p>
    </div>
    <div class="grid">
      <div class="card">
        <h3>Current subscription</h3>
        <p><strong>{escape(current_plan_name)}</strong></p>
        <p>Expires: <strong>{escape(current_plan_expiry)}</strong></p>
      </div>
      <div class="card">
        <h3>Billing</h3>
        <p>Auto-renewal keeps your plan active every 30 days. Cancel anytime from the admin dashboard.</p>
      </div>
    </div>
    <form method="post" action="/business/{business.id}/purchase-plan">
      <div class="plan-grid">{cards}</div>
      <div class="card">
        <label><input type="checkbox" name="auto_renew" value="1" checked /> Auto renew monthly</label>
        <button type="submit" class="btn primary">Checkout with Paystack</button>
      </div>
    </form>
    """
    return render_page(f"{business.name} Plans", body, nav_html=make_nav(current_user))


@app.get("/admin/businesses/{business_id}/plans", response_class=HTMLResponse)
def admin_business_plans(request: Request, business_id: int) -> HTMLResponse:
    current_user = get_current_user(request)
    if not current_user or current_user.role != "admin":
        return RedirectResponse(url="/login", status_code=303)

    db = SessionLocal()
    try:
        business = get_business(db, business_id)
        plans = db.query(Plan).order_by(Plan.price_ngn).all()
    finally:
        db.close()

    if not business:
        return render_page("Business Not Found", "<p>Business not found.</p>", nav_html=make_nav(current_user))

    active_plan = get_active_plan(business)
    current_plan_name = active_plan.name if active_plan else "Starter"
    current_plan_expiry = plan_due_label(business)
    cards = "".join(
        f"<div class=\"plan-card{' active' if active_plan and active_plan.id == plan.id else ''}\"><span class=\"tag\">{'Current' if active_plan and active_plan.id == plan.id else 'Recommended'}</span><h4>{escape(plan.name)}</h4><div class=\"price\">₦{plan.price_ngn}</div><p>{escape(plan.description or 'Premium tools for daily order and branch management.')}</p><p>{'Single branch access' if plan.branch_access == 0 else 'Unlimited branches'}</p><label><input type=\"radio\" name=\"plan_id\" value=\"{plan.id}\" {'checked' if idx == 0 else ''} /> Select this plan</label></div>"
        for idx, plan in enumerate(plans)
    )
    body = f"""
    <div class="hero">
      <div class="eyebrow">Admin subscription control</div>
      <h1>{escape(business.name)} plan settings</h1>
      <p>Update the business subscription, enable auto-renew, and preview active plan details.</p>
    </div>
    <div class="grid">
      <div class="card">
        <h3>Current plan</h3>
        <p><strong>{escape(current_plan_name)}</strong></p>
        <p>Expires: <strong>{escape(current_plan_expiry)}</strong></p>
      </div>
      <div class="card">
        <h3>Admin actions</h3>
        <p>Use this page to manage subscription tiers for the business and complete checkout through Paystack.</p>
      </div>
    </div>
    <form method="post" action="/business/{business.id}/purchase-plan">
      <div class="plan-grid">{cards}</div>
      <div class="card">
        <label><input type="checkbox" name="auto_renew" value="1" checked /> Auto renew monthly</label>
        <button type="submit" class="btn primary">Checkout with Paystack</button>
      </div>
    </form>
    """
    return render_page(f"{business.name} Plan Settings", body, nav_html=make_nav(current_user))


@app.get("/business/{business_id}/config", response_class=HTMLResponse)
def business_config(request: Request, business_id: int) -> HTMLResponse:
    return business_detail(request, business_id)
