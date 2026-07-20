import asyncio
import base64
import hashlib
import hmac
import json
import logging
import math
import os
import re
import secrets
import smtplib
import time
from email.message import EmailMessage
from datetime import datetime, timedelta
from html import escape
from typing import Dict, List, Optional

import httpx
from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Column, DateTime, Float, Integer, String, Text, UniqueConstraint, create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker
from twilio.request_validator import RequestValidator
from twilio.rest import Client as TwilioClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("recbot")

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
    open_time = Column(String(5), nullable=True)
    close_time = Column(String(5), nullable=True)
    utc_offset_minutes = Column(Integer, nullable=True)
    plan_reminder_sent_at = Column(DateTime, nullable=True)
    payment_method = Column(String(20), nullable=False, default="bank_transfer")
    paystack_secret_key = Column(String(255), nullable=True)
    location_address = Column(Text, nullable=True)
    geo_lat = Column(Float, nullable=True)
    geo_lng = Column(Float, nullable=True)
    delivery_autocalc = Column(Integer, nullable=False, default=0)
    delivery_base_fee = Column(Integer, nullable=False, default=0)
    delivery_per_km = Column(Integer, nullable=False, default=0)


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
    customer_name = Column(String(255), nullable=True)
    address = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, nullable=False)
    branch_id = Column(Integer, nullable=True)
    customer_phone = Column(String(50), nullable=False)
    customer_name = Column(String(255), nullable=True)
    items_json = Column(Text, nullable=False)
    total = Column(Integer, nullable=False)
    delivery_fee = Column(Integer, nullable=False, default=0)
    address = Column(Text, nullable=False)
    status = Column(String(50), nullable=False, default="new")
    status_changed_at = Column(DateTime, nullable=True)
    action_reminder_count = Column(Integer, nullable=False, default=0)
    action_reminded_at = Column(DateTime, nullable=True)
    payment_proof_text = Column(Text, nullable=True)
    payment_receipt_path = Column(String(255), nullable=True)
    payment_reference = Column(String(100), nullable=True)
    payment_link = Column(Text, nullable=True)
    address_unverified = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="customer")
    business_id = Column(Integer, nullable=True)
    totp_secret = Column(String(64), nullable=True)
    totp_enabled = Column(Integer, nullable=False, default=0)


class Plan(Base):
    __tablename__ = "plans"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    price_ngn = Column(Integer, nullable=False)
    branch_access = Column(Integer, nullable=False, default=0)
    monthly_order_cap = Column(Integer, nullable=False, default=0)
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
    billing_cycle = Column(String(10), nullable=False, default="monthly")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class ContactMessage(Base):
    __tablename__ = "contact_messages"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    business_name = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    email = Column(String(255), nullable=True)
    message = Column(Text, nullable=False)
    emailed = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


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
        if not has_column("businesses", "open_time"):
            conn.execute(text("ALTER TABLE businesses ADD COLUMN open_time VARCHAR(5)"))
        if not has_column("businesses", "close_time"):
            conn.execute(text("ALTER TABLE businesses ADD COLUMN close_time VARCHAR(5)"))
        if not has_column("businesses", "utc_offset_minutes"):
            conn.execute(text("ALTER TABLE businesses ADD COLUMN utc_offset_minutes INTEGER"))
        if not has_column("businesses", "plan_reminder_sent_at"):
            conn.execute(text("ALTER TABLE businesses ADD COLUMN plan_reminder_sent_at DATETIME"))
        if not has_column("businesses", "payment_method"):
            conn.execute(text("ALTER TABLE businesses ADD COLUMN payment_method VARCHAR(20) NOT NULL DEFAULT 'bank_transfer'"))
        if not has_column("businesses", "paystack_secret_key"):
            conn.execute(text("ALTER TABLE businesses ADD COLUMN paystack_secret_key VARCHAR(255)"))
        if not has_column("businesses", "location_address"):
            conn.execute(text("ALTER TABLE businesses ADD COLUMN location_address TEXT"))
        if not has_column("businesses", "geo_lat"):
            conn.execute(text("ALTER TABLE businesses ADD COLUMN geo_lat FLOAT"))
        if not has_column("businesses", "geo_lng"):
            conn.execute(text("ALTER TABLE businesses ADD COLUMN geo_lng FLOAT"))
        if not has_column("businesses", "delivery_autocalc"):
            conn.execute(text("ALTER TABLE businesses ADD COLUMN delivery_autocalc INTEGER NOT NULL DEFAULT 0"))
        if not has_column("businesses", "delivery_base_fee"):
            conn.execute(text("ALTER TABLE businesses ADD COLUMN delivery_base_fee INTEGER NOT NULL DEFAULT 0"))
        if not has_column("businesses", "delivery_per_km"):
            conn.execute(text("ALTER TABLE businesses ADD COLUMN delivery_per_km INTEGER NOT NULL DEFAULT 0"))
        if not has_column("users", "totp_secret"):
            conn.execute(text("ALTER TABLE users ADD COLUMN totp_secret VARCHAR(64)"))
        if not has_column("users", "totp_enabled"):
            conn.execute(text("ALTER TABLE users ADD COLUMN totp_enabled INTEGER NOT NULL DEFAULT 0"))
        if not has_column("orders", "payment_reference"):
            conn.execute(text("ALTER TABLE orders ADD COLUMN payment_reference VARCHAR(100)"))
        if not has_column("orders", "payment_link"):
            conn.execute(text("ALTER TABLE orders ADD COLUMN payment_link TEXT"))
        if not has_column("orders", "address_unverified"):
            conn.execute(text("ALTER TABLE orders ADD COLUMN address_unverified INTEGER NOT NULL DEFAULT 0"))
        if not has_column("payments", "billing_cycle"):
            conn.execute(text("ALTER TABLE payments ADD COLUMN billing_cycle VARCHAR(10) NOT NULL DEFAULT 'monthly'"))
        if not has_column("plans", "monthly_order_cap"):
            conn.execute(text("ALTER TABLE plans ADD COLUMN monthly_order_cap INTEGER NOT NULL DEFAULT 0"))
            conn.execute(text("UPDATE plans SET monthly_order_cap = 300 WHERE name = 'Starter' AND monthly_order_cap = 0"))
            conn.execute(text("UPDATE plans SET monthly_order_cap = 1000 WHERE name = 'Growth' AND monthly_order_cap = 0"))
        if not has_column("orders", "status_changed_at"):
            conn.execute(text("ALTER TABLE orders ADD COLUMN status_changed_at DATETIME"))
        if not has_column("orders", "action_reminder_count"):
            conn.execute(text("ALTER TABLE orders ADD COLUMN action_reminder_count INTEGER NOT NULL DEFAULT 0"))
        if not has_column("orders", "action_reminded_at"):
            conn.execute(text("ALTER TABLE orders ADD COLUMN action_reminded_at DATETIME"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_orders_business_id ON orders(business_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_orders_status ON orders(status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_orders_customer_phone ON orders(customer_phone)"))

        if not has_index("conversations", "ix_conversations_phone_business"):
            conn.execute(text(
                "CREATE TABLE conversations_new ("
                "id INTEGER PRIMARY KEY, phone_number VARCHAR(50) NOT NULL, business_id INTEGER NOT NULL, "
                "branch_id INTEGER, category_id INTEGER, stage VARCHAR(50) NOT NULL DEFAULT 'new', "
                "cart_json TEXT DEFAULT '[]', customer_name VARCHAR(255), address TEXT, updated_at DATETIME)"
            ))
            conn.execute(text(
                "INSERT INTO conversations_new (id, phone_number, business_id, branch_id, category_id, stage, cart_json, address, updated_at) "
                "SELECT id, phone_number, business_id, branch_id, category_id, stage, cart_json, address, updated_at FROM conversations"
            ))
            conn.execute(text("DROP TABLE conversations"))
            conn.execute(text("ALTER TABLE conversations_new RENAME TO conversations"))
            conn.execute(text("CREATE UNIQUE INDEX ix_conversations_phone_business ON conversations(phone_number, business_id)"))

        if not has_column("conversations", "customer_name"):
            conn.execute(text("ALTER TABLE conversations ADD COLUMN customer_name VARCHAR(255)"))
        if not has_column("orders", "customer_name"):
            conn.execute(text("ALTER TABLE orders ADD COLUMN customer_name VARCHAR(255)"))


ensure_schema()

app = FastAPI(title="Collxct")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
SECRET_KEY = os.getenv("SECRET_KEY", "supersecret-key")
if SECRET_KEY == "supersecret-key":
    logger.warning("SECRET_KEY is the built-in default — set a random SECRET_KEY in .env before going live.")

PBKDF2_ITERATIONS = 260000
AUTH_TOKEN_TTL_SECONDS = 30 * 24 * 3600


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS).hex()
    return f"pbkdf2:{PBKDF2_ITERATIONS}:{salt}:{digest}"


def verify_password(password: str, password_hash: str) -> bool:
    if password_hash.startswith("pbkdf2:"):
        try:
            _, iterations, salt, digest = password_hash.split(":")
            computed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations)).hex()
            return hmac.compare_digest(computed, digest)
        except Exception:
            return False
    # Legacy unsalted SHA-256 hashes; upgraded transparently on next login.
    legacy = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return hmac.compare_digest(legacy, password_hash)


def create_auth_token(email: str) -> str:
    expires = int(time.time()) + AUTH_TOKEN_TTL_SECONDS
    payload = f"{email}|{expires}"
    signature = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}|{signature}".encode()).decode()


def verify_auth_token(token: str) -> Optional[str]:
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        payload, signature = decoded.rsplit("|", 1)
        expected = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        email, expires = payload.rsplit("|", 1)
        if int(expires) < time.time():
            return None
        return email
    except Exception:
        return None


# --- TOTP two-factor auth (RFC 6238, stdlib only) ---

PENDING_2FA_TTL_SECONDS = 300


def generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _totp_code(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (int.from_bytes(digest[offset:offset + 4], "big") & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    if not secret or not code:
        return False
    code = code.strip().replace(" ", "")
    if not code.isdigit():
        return False
    counter = int(time.time()) // 30
    return any(hmac.compare_digest(_totp_code(secret, counter + i), code) for i in range(-window, window + 1))


def totp_provisioning_uri(email: str, secret: str) -> str:
    return f"otpauth://totp/Collxct:{email}?secret={secret}&issuer=Collxct"


def create_pending_2fa_token(email: str) -> str:
    expires = int(time.time()) + PENDING_2FA_TTL_SECONDS
    payload = f"2fa|{email}|{expires}"
    signature = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}|{signature}".encode()).decode()


def verify_pending_2fa_token(token: str) -> Optional[str]:
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        payload, signature = decoded.rsplit("|", 1)
        expected = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        prefix, email, expires = payload.split("|")
        if prefix != "2fa" or int(expires) < time.time():
            return None
        return email
    except Exception:
        return None


# Login brute-force throttle: max attempts per (ip, email) inside the window.
# In-memory is fine for a single-process deployment.
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 900
_login_attempts: Dict[str, List[float]] = {}


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def login_rate_limited(key: str) -> bool:
    now = time.time()
    attempts = [t for t in _login_attempts.get(key, []) if now - t < LOGIN_WINDOW_SECONDS]
    _login_attempts[key] = attempts
    return len(attempts) >= LOGIN_MAX_ATTEMPTS


def record_login_failure(key: str) -> None:
    _login_attempts.setdefault(key, []).append(time.time())


@app.middleware("http")
async def enforce_same_origin_posts(request: Request, call_next):
    """CSRF backstop on top of SameSite=Lax cookies: browser form posts carry an
    Origin/Referer header — reject ones from another site. Webhooks are exempt
    (they authenticate with signatures), and requests without either header
    (curl, tests, Twilio) pass through."""
    if request.method == "POST" and request.url.path not in {"/webhook", "/paystack/webhook"}:
        source = request.headers.get("origin") or request.headers.get("referer") or ""
        if source:
            source_host = source.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower()
            request_host = (
                request.headers.get("x-forwarded-host") or request.headers.get("host", "")
            ).split(":", 1)[0].lower()
            if source_host and request_host and source_host != request_host:
                return Response(content="Cross-origin request blocked", status_code=403)
    return await call_next(request)


CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "support@collxct.com.ng")
ONBOARDING_FEE_NGN = int(os.getenv("ONBOARDING_FEE_NGN", "100000"))


def send_email(subject: str, body: str, to_address: str) -> bool:
    """Send via SMTP configured in env. Returns False (and just logs) when SMTP
    isn't configured — callers should have their own fallback (we store contact
    messages in the DB regardless)."""
    host = os.getenv("SMTP_HOST")
    if not host:
        logger.warning("send_email skipped: SMTP_HOST not configured")
        return False
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME", "")
    password = os.getenv("SMTP_PASSWORD", "")
    from_address = os.getenv("SMTP_FROM", username or f"no-reply@{host}")
    use_ssl = os.getenv("SMTP_USE_SSL") == "1"
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_address
    message["To"] = to_address
    message.set_content(body)
    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=15) as server:
                if username:
                    server.login(username, password)
                server.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=15) as server:
                server.starttls()
                if username:
                    server.login(username, password)
                server.send_message(message)
        return True
    except Exception as exc:
        logger.error("send_email failed (to=%s): %s", to_address, exc)
        return False


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
            links.append("<a class='nav-link' href='/admin/orders'>Orders</a>")
            links.append("<a class='nav-link' href='/admin/conversations'>Conversations</a>")
            links.append("<a class='nav-link' href='/admin/businesses'>Businesses</a>")
            links.append("<a class='nav-link' href='/admin/plans'>Plans & Pricing</a>")
            links.append("<a class='nav-link' href='/admin/messages'>Leads</a>")
            links.append("<a class='nav-link' href='/admin/users'>Users</a>")
            links.append("<a class='nav-link' href='/register'>Create Owners</a>")
        is_business_owner = current_user.role in {"business_owner", "business-owner", "owner"}
        if is_business_owner:
            links.append("<a class='nav-link' href='/owner/portal'>Owner Portal</a>")
            if current_user.business_id:
                links.append(f"<a class='nav-link' href='/business/{current_user.business_id}/dashboard'>Operations</a>")
                links.append(f"<a class='nav-link' href='/business/{current_user.business_id}/config'>Config</a>")
                links.append(f"<a class='nav-link' href='/business/{current_user.business_id}/plans'>Plans</a>")
        if current_user.role == "admin" or is_business_owner:
            links.append("<a class='nav-link' href='/account/security'>Security</a>")
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
    <span id="rb-tip">Hi, I'm Ada! I'll pop up with tips as you work around Collxct.</span>
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
    "Hi, I'm Ada! I'll pop up with tips as you work around Collxct.",
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


ALERT_WIDGET_HTML = """
<div id="rb-alert" class="rb-alert" hidden>
  <div class="rb-alert-head">
    <span class="rb-alert-icon">🚨</span>
    <span id="rb-alert-title">Action needed</span>
    <span class="rb-alert-spacer"></span>
    <button id="rb-alert-sound" class="rb-alert-btn" type="button" hidden>🔊 Enable sound</button>
    <button id="rb-alert-mute" class="rb-alert-btn" type="button" title="Silence the chime for 5 minutes — a new order will ring again">Mute 5 min</button>
  </div>
  <div id="rb-alert-items" class="rb-alert-items"></div>
</div>
<script>
(function () {
  var POLL_MS = 12000;
  var MUTE_MS = 5 * 60 * 1000;
  var box = document.getElementById("rb-alert");
  if (!box) return;
  var itemsEl = document.getElementById("rb-alert-items");
  var titleEl = document.getElementById("rb-alert-title");
  var muteBtn = document.getElementById("rb-alert-mute");
  var soundBtn = document.getElementById("rb-alert-sound");
  var baseTitle = document.title;
  var ctx = null, chimeTimer = null, stopped = false, knownIds = null;

  function getMuteUntil() { try { return parseInt(localStorage.getItem("rb_alert_mute_until") || "0", 10) || 0; } catch (e) { return 0; } }
  function setMuteUntil(ts) { try { localStorage.setItem("rb_alert_mute_until", String(ts)); } catch (e) {} }
  function audioCtx() {
    if (!ctx) { try { ctx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { return null; } }
    return ctx;
  }
  function tone(freq, start, dur, peak) {
    var c = audioCtx(); if (!c) return;
    var osc = c.createOscillator(), gain = c.createGain();
    osc.type = "sine"; osc.frequency.value = freq;
    var t = c.currentTime + start;
    gain.gain.setValueAtTime(0.0001, t);
    gain.gain.exponentialRampToValueAtTime(peak, t + 0.04);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    osc.connect(gain); gain.connect(c.destination);
    osc.start(t); osc.stop(t + dur + 0.05);
  }
  function playChime() {
    var c = audioCtx(); if (!c) return;
    if (c.state === "suspended") { soundBtn.hidden = false; return; }
    soundBtn.hidden = true;
    // Long, insistent three-round chime (~3s) that repeats while unacknowledged.
    [0, 1.0, 2.0].forEach(function (offset) {
      tone(880, offset, 0.5, 0.22);
      tone(1174.66, offset + 0.18, 0.55, 0.18);
      tone(659.25, offset + 0.36, 0.7, 0.15);
    });
  }
  function startAlarm() {
    if (Date.now() < getMuteUntil()) return;
    playChime();
    if (chimeTimer) return;
    chimeTimer = setInterval(function () {
      if (Date.now() < getMuteUntil()) return;
      playChime();
    }, 6000);
  }
  function stopAlarm() { if (chimeTimer) { clearInterval(chimeTimer); chimeTimer = null; } }

  muteBtn.addEventListener("click", function () { setMuteUntil(Date.now() + MUTE_MS); });
  soundBtn.addEventListener("click", function () {
    var c = audioCtx();
    if (c && c.state === "suspended") { c.resume().then(playChime); } else { playChime(); }
  });
  document.addEventListener("click", function () {
    if (ctx && ctx.state === "suspended") ctx.resume();
  });

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (m) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m];
    });
  }
  function render(data) {
    if (!data.count) {
      box.hidden = true;
      document.title = baseTitle;
      stopAlarm();
      knownIds = [];
      return;
    }
    var html = "";
    data.orders.slice(0, 6).forEach(function (o) {
      html += "<a class='rb-alert-item' href='" + esc(o.url) + "'>"
        + "<span class='rb-alert-item-main'><strong>#" + esc(o.id) + "</strong> · " + esc(o.customer)
        + (o.business ? " · " + esc(o.business) : "") + " · ₦" + esc(o.total) + "</span>"
        + "<span class='rb-alert-item-sub'>" + esc(o.label) + " — waiting " + esc(o.age) + "</span>"
        + "<span class='rb-alert-item-cta'>" + esc(o.action) + " →</span></a>";
    });
    if (data.count > 6) html += "<div class='rb-alert-more'>+" + (data.count - 6) + " more on the Orders page…</div>";
    itemsEl.innerHTML = html;
    titleEl.textContent = data.count === 1 ? "1 order needs your action" : data.count + " orders need your action";
    box.hidden = false;
    document.title = "(" + data.count + ") 🔔 " + baseTitle;
    var ids = data.orders.map(function (o) { return String(o.id); });
    var hasNew = knownIds !== null && ids.some(function (id) { return knownIds.indexOf(id) === -1; });
    if (hasNew) setMuteUntil(0); // a brand-new alert always rings, even if muted
    knownIds = ids;
    if (Date.now() >= getMuteUntil()) { startAlarm(); } else { stopAlarm(); }
  }
  function poll() {
    if (stopped) return;
    fetch("/api/action-required", { credentials: "same-origin" }).then(function (r) {
      if (r.status === 401) { stopped = true; box.hidden = true; document.title = baseTitle; stopAlarm(); return null; }
      return r.ok ? r.json() : null;
    }).then(function (data) { if (data) render(data); }).catch(function () {});
  }
  poll();
  setInterval(poll, POLL_MS);
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
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>{escape(title)} · Collxct</title>
        <link rel="icon" type="image/svg+xml" href="/static/img/logo-icon.svg" />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet" />
        <style>
                    :root {{
                      --bg:#090c0b; --surface:#101413; --surface-2:#161c1a; --surface-hover:#1c2422;
                      --text:#f1f5f3; --muted:#8b9792; --muted-2:#5e6a65;
                      --primary:#10b981; --primary-strong:#34d399; --accent:#f59e0b; --success:#34d399; --danger:#ff5e7a;
                      --border:rgba(255,255,255,.08); --border-strong:rgba(255,255,255,.14);
                      --radius-sm:8px; --radius-md:12px; --radius-lg:18px;
                      --shadow-sm:0 1px 2px rgba(0,0,0,.5); --shadow-md:0 12px 32px rgba(0,0,0,.4);
                    }}
                    * {{ box-sizing: border-box; }}
                    html,body {{ height:100%; }}
                    body {{
                      margin:0; font-family:'Inter', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                      font-size:15px; line-height:1.6; color:var(--text);
                      background: radial-gradient(1100px circle at 12% -8%, rgba(16,185,129,.12), transparent 55%), radial-gradient(900px circle at 100% 0%, rgba(245,158,11,.05), transparent 50%), var(--bg);
                    }}
                    .shell {{ display:flex; min-height:100vh; }}
                    .sidebar {{ width:258px; flex-shrink:0; background:var(--surface); border-right:1px solid var(--border); display:flex; flex-direction:column; padding:18px 14px; position:sticky; top:0; height:100vh; overflow-y:auto; }}
                    .brand {{ display:flex; align-items:center; gap:10px; padding:4px 8px 18px; margin-bottom:10px; border-bottom:1px solid var(--border); text-decoration:none; }}
                    .brand-logo {{ height:32px; width:auto; display:block; }}
                    .nav-links {{ display:flex; flex-direction:column; gap:2px; }}
                    .nav-link {{ display:flex; align-items:center; gap:9px; padding:9px 11px; border-radius:var(--radius-sm); color:var(--muted); font-weight:500; font-size:.9rem; text-decoration:none; transition:background .15s ease, color .15s ease; }}
                    .nav-link:hover {{ background:var(--surface-2); color:var(--text); }}
                    .nav-footer {{ margin-top:auto; padding-top:14px; border-top:1px solid var(--border); display:flex; flex-direction:column; gap:6px; }}
                    .user-chip {{ display:flex; align-items:center; gap:9px; padding:8px 10px; border-radius:var(--radius-sm); background:var(--surface-2); }}
                    .user-avatar {{ width:26px; height:26px; border-radius:50%; background:linear-gradient(135deg,#34d399,#059669); color:#fff; display:flex; align-items:center; justify-content:center; font-size:.72rem; font-weight:700; flex-shrink:0; }}
                    .user-email {{ font-size:.82rem; color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
                    .nav-link.logout {{ color:var(--danger); }}
                    .nav-link.logout:hover {{ background:rgba(255,94,122,.1); color:var(--danger); }}
                    .chip {{ padding:5px 10px; border:1px solid var(--border); border-radius:999px; color:var(--muted); font-size:.82rem; }}
                    .main-area {{ flex:1; min-width:0; display:flex; flex-direction:column; }}
                    .page-title {{ position:sticky; top:0; z-index:5; padding:16px 32px; background:rgba(9,9,11,.75); backdrop-filter:blur(10px); border-bottom:1px solid var(--border); }}
                    .page-title h1 {{ margin:0; font-size:1.3rem; font-weight:700; letter-spacing:-.01em; color:var(--text); }}
                    .page-title p {{ margin:6px 0 0; color:var(--muted); font-size:.88rem; }}
                    .content {{ padding:28px 32px 64px; max-width:1280px; display:flex; flex-direction:column; gap:22px; width:100%; }}
                    .hero, .hero-panel, .auth-hero {{ border-radius:var(--radius-lg); border:1px solid var(--border-strong); background:linear-gradient(135deg,#0d2f24 0%,#0a231c 48%,#071710 100%); box-shadow:inset 0 1px 0 rgba(255,255,255,.05), var(--shadow-md); color:var(--text); }}
                    .hero {{ padding:30px; }}
                    .hero h1 {{ margin:0 0 10px; font-size:1.9rem; letter-spacing:-.02em; }}
                    .hero p {{ margin:0 0 16px; color:#bcd8cc; max-width:720px; }}
                    .hero-panel {{ display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:18px; padding:28px; }}
                    .hero-panel h1 {{ margin:0 0 8px; font-size:clamp(1.5rem,2.6vw,2.1rem); line-height:1.1; letter-spacing:-.02em; }}
                    .hero-panel p {{ margin:0; color:#bcd8cc; max-width:680px; }}
                    .hero-panel .actions {{ display:flex; flex-wrap:wrap; gap:10px; }}
                    .auth-shell {{ display:grid; grid-template-columns:1.05fr .95fr; gap:20px; align-items:stretch; }}
                    .auth-hero {{ padding:26px; display:flex; flex-direction:column; justify-content:center; min-height:320px; }}
                    .auth-hero h2 {{ margin:0 0 10px; font-size:1.6rem; letter-spacing:-.02em; }}
                    .auth-hero p {{ color:#bcd8cc; }}
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
                    input:focus, select:focus, textarea:focus {{ outline:none; border-color:var(--primary); box-shadow:0 0 0 3px rgba(16,185,129,.18); }}
                    input::placeholder, textarea::placeholder {{ color:var(--muted-2); }}
                    ul {{ margin-left:20px; }}
                    a {{ color:var(--primary-strong); }}
                    .eyebrow {{ font-size:.72rem; text-transform:uppercase; letter-spacing:.14em; color:var(--muted); font-weight:700; margin-bottom:8px; }}
                    .stack {{ display:flex; flex-direction:column; gap:10px; }}
                    .pill {{ display:inline-block; padding:4px 10px; border-radius:999px; background:var(--surface-2); border:1px solid var(--border); color:var(--muted); font-size:.76rem; font-weight:600; margin-right:6px; }}
                    .form-group {{ margin-bottom:14px; }}
                    .status-pill {{ display:inline-flex; align-items:center; padding:6px 12px; border-radius:999px; background:rgba(52,211,153,.12); border:1px solid rgba(52,211,153,.3); color:var(--success); font-weight:600; font-size:.82rem; }}
                    label {{ display:inline-flex; align-items:center; gap:8px; font-weight:500; font-size:.9rem; cursor:pointer; color:var(--text); }}
                    input[type="checkbox"], input[type="radio"] {{ width:auto; display:inline-block; max-width:none; margin:0; }}
                    .plan-grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(230px, 1fr)); gap:16px; margin:6px 0; }}
                    .plan-card {{ position:relative; display:flex; flex-direction:column; gap:8px; background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-md); padding:22px; transition:border-color .15s ease, transform .15s ease; }}
                    .plan-card:hover {{ transform:translateY(-2px); border-color:var(--border-strong); }}
                    .plan-card.active {{ border-color:var(--success); box-shadow:0 0 0 1px var(--success); }}
                    .plan-card h4 {{ margin:2px 0 0; font-size:1.15rem; }}
                    .plan-card .tag {{ align-self:flex-start; padding:3px 9px; border-radius:999px; background:var(--surface-2); color:var(--muted); font-size:.68rem; text-transform:uppercase; letter-spacing:.08em; font-weight:700; }}
                    .plan-card.active .tag {{ background:rgba(52,211,153,.15); color:var(--success); }}
                    .plan-card .price {{ font-size:1.7rem; font-weight:800; letter-spacing:-.03em; color:var(--text); }}
                    .plan-card p {{ color:var(--muted); margin:0; font-size:.88rem; }}
                    .plan-card label {{ margin-top:6px; }}
                    dialog.modal {{ border:1px solid var(--border-strong); border-radius:var(--radius-lg); padding:0; background:var(--surface); color:var(--text); box-shadow:var(--shadow-md); width:min(420px, 90vw); }}
                    dialog.modal::backdrop {{ background:rgba(2,4,10,.68); backdrop-filter:blur(2px); }}
                    dialog.modal .modal-body {{ padding:24px; }}
                    dialog.modal h3 {{ margin-top:0; }}
                    dialog.modal .modal-actions {{ display:flex; gap:10px; margin-top:18px; }}
                    dialog.modal .modal-actions button {{ margin-right:0; }}
                    .detail-grid {{ display:grid; grid-template-columns:1.4fr 1fr; gap:16px; align-items:start; }}
                    .kv-list {{ display:flex; flex-direction:column; gap:10px; }}
                    .kv-list .kv-row {{ display:flex; justify-content:space-between; gap:12px; padding:10px 0; border-bottom:1px solid var(--border); }}
                    .kv-list .kv-row:last-child {{ border-bottom:none; }}
                    .kv-list .kv-label {{ color:var(--muted); font-size:.85rem; }}
                    .kv-list .kv-value {{ font-weight:600; text-align:right; }}
                    .receipt-preview {{ max-width:100%; border-radius:var(--radius-md); border:1px solid var(--border); margin-top:10px; }}
                    @media (max-width:780px) {{ .detail-grid {{ grid-template-columns:1fr; }} }}
                    .rb-alert {{ position:fixed; top:14px; left:50%; transform:translateX(-50%); z-index:10001; width:min(560px, calc(100vw - 24px)); background:linear-gradient(160deg,#2a1218,#1a0d11); border:1px solid rgba(255,94,122,.55); border-radius:var(--radius-md); overflow:hidden; animation:rb-alert-pulse 1.6s ease-in-out infinite; }}
                    .rb-alert-head {{ display:flex; align-items:center; gap:10px; padding:12px 16px; border-bottom:1px solid rgba(255,94,122,.25); font-weight:700; color:#ffb3c1; }}
                    .rb-alert-icon {{ font-size:1.1rem; animation:rb-alert-ring 1.2s ease-in-out infinite; }}
                    .rb-alert-spacer {{ flex:1; }}
                    .rb-alert-btn {{ padding:5px 10px; border-radius:8px; border:1px solid rgba(255,94,122,.4); background:rgba(255,94,122,.12); color:#ffb3c1; font-size:.76rem; font-weight:700; cursor:pointer; margin-right:0; }}
                    .rb-alert-btn:hover {{ background:rgba(255,94,122,.22); transform:none; }}
                    .rb-alert-item {{ display:flex; flex-direction:column; gap:2px; padding:10px 16px; text-decoration:none; border-bottom:1px solid rgba(255,255,255,.06); transition:background .15s ease; }}
                    .rb-alert-item:last-child {{ border-bottom:none; }}
                    .rb-alert-item:hover {{ background:rgba(255,94,122,.08); }}
                    .rb-alert-item-main {{ color:var(--text); font-size:.9rem; }}
                    .rb-alert-item-sub {{ color:#ff8fa3; font-size:.78rem; font-weight:600; }}
                    .rb-alert-item-cta {{ color:var(--primary-strong); font-size:.8rem; font-weight:700; }}
                    .rb-alert-more {{ padding:8px 16px; color:var(--muted); font-size:.8rem; }}
                    @keyframes rb-alert-pulse {{ 0%,100% {{ box-shadow:0 18px 50px rgba(0,0,0,.6), 0 0 0 1px rgba(255,94,122,.25); }} 50% {{ box-shadow:0 18px 50px rgba(0,0,0,.6), 0 0 0 6px rgba(255,94,122,.30); }} }}
                    @keyframes rb-alert-ring {{ 0%,100% {{ transform:rotate(0); }} 20% {{ transform:rotate(14deg); }} 40% {{ transform:rotate(-12deg); }} 60% {{ transform:rotate(8deg); }} 80% {{ transform:rotate(-6deg); }} }}
                    .queue-list {{ display:flex; flex-direction:column; gap:10px; }}
                    .queue-item {{ display:flex; align-items:center; gap:14px; padding:14px 16px; border:1px solid rgba(255,94,122,.35); border-radius:var(--radius-md); background:rgba(255,94,122,.06); text-decoration:none; transition:background .15s ease, transform .1s ease; }}
                    .queue-item:hover {{ background:rgba(255,94,122,.12); transform:translateY(-1px); }}
                    .queue-main {{ display:flex; flex-direction:column; gap:2px; min-width:0; }}
                    .queue-id {{ font-weight:800; color:var(--text); }}
                    .queue-customer {{ color:var(--text); font-size:.9rem; }}
                    .queue-biz {{ color:var(--muted); font-size:.78rem; }}
                    .queue-meta {{ margin-left:auto; display:flex; flex-direction:column; align-items:flex-end; gap:2px; flex-shrink:0; }}
                    .queue-total {{ font-weight:700; color:var(--text); }}
                    .queue-status {{ color:#ff8fa3; font-size:.78rem; font-weight:600; }}
                    .queue-age {{ color:var(--muted); font-size:.75rem; }}
                    .queue-cta {{ flex-shrink:0; }}
                    .empty-state {{ padding:18px; border:1px dashed var(--border-strong); border-radius:var(--radius-md); color:var(--muted); text-align:center; }}
                    .notice-banner {{ padding:14px 18px; border:1px solid rgba(255,196,0,.4); border-radius:var(--radius-md); background:rgba(255,196,0,.08); color:#ffd866; font-weight:600; }}
                    .notice-banner.danger {{ border-color:rgba(255,94,122,.45); background:rgba(255,94,122,.08); color:#ff8fa3; }}
                    .notice-banner a {{ color:inherit; text-decoration:underline; }}
                    .stat-card.alert {{ border-color:rgba(255,94,122,.5); background:rgba(255,94,122,.07); }}
                    .stat-card.alert .value {{ color:var(--danger); }}
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
            <a class="brand" href="/">
              <img class="brand-logo" src="/static/img/logo-white.svg" alt="Collxct" />
            </a>
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
        {ALERT_WIDGET_HTML}
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
        orders = db.query(Order).filter(Order.business_id == business.id).order_by(Order.created_at.desc()).limit(100).all()
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


DEFAULT_UTC_OFFSET_MINUTES = int(os.getenv("DEFAULT_UTC_OFFSET_MINUTES", "60"))  # WAT (Lagos)
PLAN_GRACE_DAYS = int(os.getenv("PLAN_GRACE_DAYS", "3"))
# Annual prepay: pay this many months up front, get 12 (default = 2 months free).
ANNUAL_MONTHS_CHARGED = int(os.getenv("ANNUAL_MONTHS_CHARGED", "10"))


def business_local_now(business: Business) -> datetime:
    offset = business.utc_offset_minutes if business.utc_offset_minutes is not None else DEFAULT_UTC_OFFSET_MINUTES
    return datetime.utcnow() + timedelta(minutes=offset)


def parse_hhmm(value: Optional[str]):
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%H:%M").time()
    except ValueError:
        return None


def business_is_open(business: Business) -> bool:
    """True unless both opening hours are set and local time falls outside them.

    Supports overnight windows (e.g. 18:00–02:00).
    """
    open_t = parse_hhmm(business.open_time)
    close_t = parse_hhmm(business.close_time)
    if not open_t or not close_t or open_t == close_t:
        return True
    now_t = business_local_now(business).time()
    if open_t < close_t:
        return open_t <= now_t < close_t
    return now_t >= open_t or now_t < close_t


def format_closed_reply(business: Business) -> str:
    return (
        f"⏰ *{business.name}* is closed right now.\n\n"
        f"Opening hours: *{business.open_time}–{business.close_time}* daily. "
        f"Please message us again then — we'd love to serve you!\n\n"
        f"(You can still reply 'status' to check an existing order.)" + COLLXCT_FOOTER
    )


def plan_is_blocked(business: Business) -> bool:
    """A lapsed paid plan blocks new ordering after a grace period. Businesses
    without an expiry date (trial / admin-managed) are never blocked."""
    if not business.plan_expiry:
        return False
    return datetime.utcnow() > business.plan_expiry + timedelta(days=PLAN_GRACE_DAYS)


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


PAYMENT_METHOD_LABELS = {"bank_transfer": "Bank transfer", "paystack": "Paystack payment link"}


def paystack_key_mode(key: Optional[str]) -> str:
    key = (key or "").strip()
    if key.startswith("sk_live_"):
        return "live"
    if key.startswith("sk_test_"):
        return "test"
    return "unknown" if key else "missing"


def create_paystack_order_link(business: Business, order: Order) -> Optional[str]:
    """Create a hosted Paystack checkout link for an order, using the business's
    own secret key — the same key later verifies it, so test keys stay test and
    live keys stay live end to end."""
    key = (business.paystack_secret_key or "").strip()
    if not key:
        return None
    reference = f"RBORD-{order.id}-{int(datetime.utcnow().timestamp())}"
    digits = re.sub(r"[^0-9]", "", order.customer_phone) or "customer"
    payload = {
        "email": f"{digits}@collxct.com.ng",
        "amount": order.total * 100,  # kobo
        "reference": reference,
        "currency": "NGN",
        "metadata": {"order_id": order.id, "business_id": business.id, "customer_phone": order.customer_phone},
    }
    base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    if base:
        payload["callback_url"] = f"{base}/pay/thanks"
    try:
        response = httpx.post(
            "https://api.paystack.co/transaction/initialize",
            json=payload, headers={"Authorization": f"Bearer {key}"}, timeout=15.0,
        )
        data = response.json()
        if data.get("status"):
            order.payment_reference = reference
            order.payment_link = data["data"]["authorization_url"]
            return order.payment_link
        logger.error("paystack init rejected (order=%s, mode=%s): %s", order.id, paystack_key_mode(key), data.get("message"))
    except Exception as exc:
        logger.error("paystack init failed (order=%s): %s", order.id, exc)
    return None


def verify_paystack_order_payment(business: Business, order: Order) -> Optional[bool]:
    """True = confirmed paid, False = definitely not paid yet, None = couldn't check."""
    key = (business.paystack_secret_key or "").strip()
    if not key or not order.payment_reference:
        return None
    try:
        response = httpx.get(
            f"https://api.paystack.co/transaction/verify/{order.payment_reference}",
            headers={"Authorization": f"Bearer {key}"}, timeout=15.0,
        )
        data = response.json()
        if not data.get("status"):
            return None
        tx = data.get("data") or {}
        if tx.get("status") != "success":
            return False
        # Guard against a lesser amount slipping through.
        return int(tx.get("amount") or 0) >= order.total * 100
    except Exception as exc:
        logger.error("paystack verify failed (order=%s): %s", order.id, exc)
        return None


@app.get("/pay/thanks", response_class=HTMLResponse)
def payment_thanks() -> HTMLResponse:
    body = """
    <div class="card" style="text-align:center;">
      <h2>🎉 Thanks — payment received!</h2>
      <p>You can close this page and head back to WhatsApp. Reply <strong>paid</strong> there and we'll confirm your order instantly.</p>
    </div>
    """
    return render_page("Payment Complete", body, nav_html=make_nav(None))


# --- Delivery fee auto-calculation (OpenStreetMap geocoding + haversine) ---

MAX_AUTO_DELIVERY_KM = float(os.getenv("MAX_AUTO_DELIVERY_KM", "30"))
GEOCODER_USER_AGENT = os.getenv("GEOCODER_USER_AGENT", "RecbotCRM/1.0 (recbot@collxct.com.ng)")


def geocode_address(address: str):
    """Best-effort geocode via Nominatim (free, no key). Returns (lat, lng) or None."""
    if not address or not address.strip():
        return None
    try:
        response = httpx.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address.strip(), "format": "json", "limit": 1, "countrycodes": "ng"},
            headers={"User-Agent": GEOCODER_USER_AGENT}, timeout=6.0,
        )
        results = response.json()
        if isinstance(results, list) and results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as exc:
        logger.warning("geocode failed for %r: %s", address, exc)
    return None


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def compute_auto_delivery_fee(business: Business, address: str) -> Optional[Dict[str, object]]:
    """Base fee + per-km rate, like Nigerian dispatch pricing. Returns
    {'fee': int, 'km': float} or None when auto-pricing isn't possible —
    callers fall back to the manual owner-sets-fee flow."""
    if not business.delivery_autocalc or business.geo_lat is None or business.geo_lng is None:
        return None
    if not (business.delivery_base_fee or business.delivery_per_km):
        return None
    coords = geocode_address(address)
    if not coords:
        return None
    km = haversine_km(business.geo_lat, business.geo_lng, coords[0], coords[1])
    if km > MAX_AUTO_DELIVERY_KM:
        # Probably a bad geocoder match (or genuinely out of range) — let a human price it.
        return None
    fee = (business.delivery_base_fee or 0) + int(math.ceil(km)) * (business.delivery_per_km or 0)
    fee = int(round(fee / 50.0) * 50)  # round to the nearest N50 like ride apps
    return {"fee": fee, "km": round(km, 1)}


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
            Plan(name="Starter", price_ngn=7500, branch_access=0, monthly_order_cap=300, description="Single-location plan with menu and order management. Includes 300 orders/month."),
            Plan(name="Growth", price_ngn=20000, branch_access=1, monthly_order_cap=1000, description="Full branch access, advanced menus, and premium workflows. Includes 1,000 orders/month."),
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


def upsert_payment(db, business_id: int, user_email: str, plan_id: int, amount: int, reference: str, auto_renew: bool, billing_cycle: str = "monthly") -> Payment:
    payment = Payment(business_id=business_id, user_email=user_email, plan_id=plan_id, amount=amount, reference=reference, status="initialized", auto_renew=1 if auto_renew else 0, billing_cycle=billing_cycle)
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
        duration_days = 365 if payment.billing_cycle == "annual" else 30
        business.plan_expiry = datetime.utcnow() + timedelta(days=duration_days)
        business.auto_renew = payment.auto_renew
        business.plan_reminder_sent_at = None
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
            admin_password = os.getenv("ADMIN_PASSWORD")
            if not admin_password:
                admin_password = "Pass@12345"
                logger.warning("Seeded admin user with the built-in default password — set ADMIN_PASSWORD in .env and change it before going live.")
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
CONV_NAME = "await_name"
CONV_ADDRESS = "await_address"
CONV_AWAITING_PAYMENT = "awaiting_payment"
# Greetings are "soft": mid-order they get a resume reminder instead of silently
# wiping the cart. Hard reset words always start fresh.
GREETING_WORDS = {"hi", "hello", "hey", "good morning", "good afternoon", "good evening", "hy", "helo"}
HARD_RESET_WORDS = {"start", "menu", "restart", "start over", "new order"}
STATUS_WORDS = {"status", "order status", "my order", "track", "track order", "where is my order"}
HELP_WORDS = {"help", "info", "commands", "options"}
CANCEL_WORDS = {"cancel", "stop", "cancel order", "quit"}
CHECKOUT_WORDS = {"checkout", "done", "order", "place order", "pay"}
CART_WORDS = {"cart", "my cart", "view cart", "basket"}
BACK_WORDS = {"back", "categories", "go back"}
CLEAR_CART_WORDS = {"clear", "clear cart", "empty cart"}
PAYMENT_CLAIM_TOKENS = ("paid", "transfer", "sent", "receipt", "confirm", "done")
PAYMENT_INFO_TOKENS = ("how much", "account", "bank", "details", "total", "amount")
ACTIVE_ORDER_STATUSES = {"awaiting_delivery_fee", "awaiting_payment", "payment_claimed", "paid", "out_for_delivery"}
STALE_CONVERSATION_AFTER = timedelta(hours=24)
STALE_RESET_STAGES = {CONV_CATEGORY, CONV_ITEM, CONV_NAME, CONV_ADDRESS}


def normalize_whatsapp_number(value: Optional[str]) -> str:
    if not value:
        return ""
    return value.replace("whatsapp:", "").strip()


def send_whatsapp_message(to_number: str, body: str, from_number: Optional[str] = None) -> bool:
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = from_number or os.getenv("TWILIO_WHATSAPP_NUMBER")
    if not account_sid or not auth_token or not from_number:
        logger.warning(
            "send_whatsapp_message skipped: missing credentials (account_sid=%s auth_token=%s from_number=%s)",
            bool(account_sid), bool(auth_token), bool(from_number),
        )
        return False
    to = to_number if to_number.startswith("whatsapp:") else f"whatsapp:{to_number}"
    from_ = from_number if from_number.startswith("whatsapp:") else f"whatsapp:{from_number}"
    try:
        client = TwilioClient(account_sid, auth_token)
        message = client.messages.create(from_=from_, to=to, body=body)
        logger.info("send_whatsapp_message sent (sid=%s to=%s from=%s)", message.sid, to, from_)
        return True
    except Exception as exc:
        logger.error("send_whatsapp_message failed (to=%s from=%s): %s", to, from_, exc)
        return False


# Orders in these statuses are blocked on the business/admin, not the customer.
ACTION_NEEDED_STATUSES = ("awaiting_delivery_fee", "payment_claimed")
ACTION_LABELS = {
    "awaiting_delivery_fee": "Set delivery fee",
    "payment_claimed": "Confirm payment",
}
STAFF_ROLES = {"admin", "business_owner", "business-owner", "owner"}
ACTION_REMINDER_AFTER = timedelta(minutes=int(os.getenv("ACTION_REMINDER_AFTER_MINUTES", "10")))
ACTION_REMINDER_MAX = int(os.getenv("ACTION_REMINDER_MAX", "3"))
ACTION_REMINDER_INTERVAL_SECONDS = int(os.getenv("ACTION_REMINDER_INTERVAL_SECONDS", "120"))


def set_order_status(order: Order, status: str) -> None:
    order.status = status
    order.status_changed_at = datetime.utcnow()
    order.action_reminder_count = 0
    order.action_reminded_at = None


def order_link(order_id: int) -> str:
    base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    return f"{base}/orders/{order_id}" if base else ""


def notify_owner_action(business: Business, order_id: int, headline: str) -> None:
    if not business or not business.owner_notify_number:
        return
    link = order_link(order_id)
    link_line = f"\n\nOpen: {link}" if link else "\n\nOpen your Recbot dashboard to respond."
    send_whatsapp_message(business.owner_notify_number, headline + link_line, from_number=business.whatsapp_number)


def month_start_utc() -> datetime:
    return datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def monthly_order_usage(db, business: Business):
    """Returns (used, cap, plan) for the current calendar month; cap 0 = uncapped."""
    plan = get_plan(db, business.plan_id) if business.plan_id else None
    cap = plan.monthly_order_cap if plan else 0
    if not cap:
        return 0, 0, plan
    used = db.query(Order).filter(Order.business_id == business.id, Order.created_at >= month_start_utc()).count()
    return used, cap, plan


def notify_order_cap_usage(db, business: Business) -> None:
    """Soft cap: never blocks orders, just nudges the owner exactly once at 80%
    and once when crossing the cap."""
    if not business.owner_notify_number:
        return
    used, cap, plan = monthly_order_usage(db, business)
    if not cap:
        return
    threshold_80 = max(1, int(cap * 0.8))
    if used == threshold_80 and used < cap:
        send_whatsapp_message(
            business.owner_notify_number,
            f"📈 Heads up: you've used *{used}* of the *{cap}* orders included in your {plan.name} plan this month. "
            f"Orders won't be blocked — but consider upgrading if you're trending past it.",
            from_number=business.whatsapp_number,
        )
    elif used == cap + 1:
        send_whatsapp_message(
            business.owner_notify_number,
            f"🔔 You've passed the *{cap}* orders/month included in your {plan.name} plan. Orders keep flowing as normal — "
            f"please upgrade your plan to match your volume.",
            from_number=business.whatsapp_number,
        )


def action_needed_orders(db, business_id: Optional[int] = None) -> List[Order]:
    query = db.query(Order).filter(Order.status.in_(ACTION_NEEDED_STATUSES))
    if business_id is not None:
        query = query.filter(Order.business_id == business_id)
    return query.order_by(Order.created_at.asc()).all()


def run_action_reminders() -> None:
    """Re-ping the business owner on WhatsApp while an order sits waiting on them."""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        orders = (
            db.query(Order)
            .filter(Order.status.in_(ACTION_NEEDED_STATUSES), Order.action_reminder_count < ACTION_REMINDER_MAX)
            .all()
        )
        if not orders:
            return
        businesses = {b.id: b for b in db.query(Business).filter(Business.id.in_({o.business_id for o in orders})).all()}
        for order in orders:
            business = businesses.get(order.business_id)
            if not business or not business.owner_notify_number:
                continue
            waiting_since = order.status_changed_at or order.created_at or now
            last_ping = order.action_reminded_at or waiting_since
            if now - waiting_since < ACTION_REMINDER_AFTER or now - last_ping < ACTION_REMINDER_AFTER:
                continue
            action = ACTION_LABELS.get(order.status, "review")
            minutes = int((now - waiting_since).total_seconds() // 60)
            link = order_link(order.id)
            link_line = f"\n\nOpen: {link}" if link else "\n\nOpen your Recbot dashboard to respond."
            sent = send_whatsapp_message(
                business.owner_notify_number,
                f"⏰ *REMINDER {order.action_reminder_count + 1}/{ACTION_REMINDER_MAX}* — order *#{order.id}* "
                f"(N{order.total}, {order.customer_name or order.customer_phone}) has been waiting *{minutes} min* "
                f"for you to {action.lower()}. The customer is on hold until you do.{link_line}",
                from_number=business.whatsapp_number,
            )
            if sent:
                order.action_reminder_count += 1
                order.action_reminded_at = now
        db.commit()
    finally:
        db.close()


def run_plan_reminders() -> None:
    """Daily WhatsApp nudges when a paid plan is about to expire or has lapsed.
    Stops 7 days past expiry."""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        soon = now + timedelta(days=PLAN_GRACE_DAYS)
        businesses = db.query(Business).filter(Business.plan_expiry.isnot(None)).all()
        base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
        for business in businesses:
            expiry = business.plan_expiry
            if not business.owner_notify_number or expiry > soon or now - expiry > timedelta(days=7):
                continue
            if business.plan_reminder_sent_at and now - business.plan_reminder_sent_at < timedelta(hours=23):
                continue
            renew_line = (
                f"\n\nRenew: {base}/business/{business.id}/plans" if base
                else "\n\nRenew from the Plans page on your Recbot dashboard."
            )
            if expiry > now:
                days_left = max(1, (expiry - now).days)
                message = (
                    f"⚠️ Your *{business.name}* Recbot plan expires on {expiry.strftime('%b %d')} "
                    f"(about {days_left} day(s) left). Renew now to keep WhatsApp ordering live.{renew_line}"
                )
            elif not plan_is_blocked(business):
                resume = (expiry + timedelta(days=PLAN_GRACE_DAYS)).strftime("%b %d")
                message = (
                    f"🚨 Your *{business.name}* Recbot plan expired on {expiry.strftime('%b %d')}. "
                    f"WhatsApp ordering pauses on {resume} unless you renew.{renew_line}"
                )
            else:
                message = (
                    f"🚫 WhatsApp ordering for *{business.name}* is paused — your plan expired on "
                    f"{expiry.strftime('%b %d')}. Renew to switch it back on.{renew_line}"
                )
            if send_whatsapp_message(business.owner_notify_number, message, from_number=business.whatsapp_number):
                business.plan_reminder_sent_at = now
        db.commit()
    finally:
        db.close()


async def action_reminder_loop() -> None:
    while True:
        await asyncio.sleep(ACTION_REMINDER_INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(run_action_reminders)
            await asyncio.to_thread(run_plan_reminders)
        except Exception:
            logger.exception("action reminder sweep failed")


@app.on_event("startup")
async def start_action_reminder_loop() -> None:
    # Only worth running when WhatsApp sending is configured (keeps tests quiet).
    if os.getenv("TWILIO_ACCOUNT_SID") and os.getenv("TWILIO_AUTH_TOKEN"):
        asyncio.create_task(action_reminder_loop())


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


def resolve_choice(text: str, names: List[str]) -> Optional[int]:
    index = parse_choice(text)
    if index is not None:
        return index
    cleaned = text.strip().lower()
    if cleaned:
        for i, name in enumerate(names):
            if name.strip().lower() == cleaned:
                return i + 1
        if len(cleaned) >= 3:
            matches = [i for i, name in enumerate(names) if cleaned in name.strip().lower()]
            if len(matches) == 1:
                return matches[0] + 1
    # Tolerate "1.", "(2)", "item 3", "I'll take 2 please" — only when exactly one
    # number appears, so ambiguous messages still fall through to the re-prompt.
    numbers = re.findall(r"\d+", text)
    if len(numbers) == 1:
        return int(numbers[0])
    return None


COLLXCT_FOOTER = "\n\n_Powered by Collxct_"


def format_category_menu(categories: List[Category]) -> str:
    lines = [f"*{i}.* {category.name}" for i, category in enumerate(categories, start=1)]
    return "Please choose a category by replying with a number:\n\n" + "\n".join(lines)


def format_item_menu(items: List[MenuItem], category_name: str) -> str:
    lines = []
    for i, item in enumerate(items, start=1):
        lines.append(f"*{i}.* {item.name} — N{item.price}")
        if item.description:
            lines.append(f"_{item.description}_")
    return (
        f"*{category_name}* menu:\n\n" + "\n".join(lines) + "\n\n"
        "Reply with a number to add an item to your cart, 'cart' to view your cart, "
        "'back' to see other categories, or 'checkout' when you're ready to order."
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
        lines.append(f"{qty} x {entry.get('name', 'Item')} — N{int(price) * int(qty)}")
    return "\n".join(lines)


def build_greeting_reply(db, business: Business, conversation: Conversation) -> str:
    categories = active_categories_for_business(db, business.id)
    conversation.category_id = None
    if not categories:
        conversation.stage = CONV_NEW
        return f"Hi! Thanks for reaching out to *{business.name}*. We don't have any items available right now, please check back soon.{COLLXCT_FOOTER}"
    conversation.stage = CONV_CATEGORY
    return f"Hi! 👋 Welcome to *{business.name}*.\n\n" + format_category_menu(categories) + COLLXCT_FOOTER


def latest_order_for(db, business_id: int, phone_number: str) -> Optional[Order]:
    return (
        db.query(Order)
        .filter(Order.customer_phone == phone_number, Order.business_id == business_id)
        .order_by(Order.id.desc())
        .first()
    )


def format_bank_info(business: Optional[Business]) -> str:
    lines = []
    if business and business.bank_name:
        lines.append(f"Bank: {business.bank_name}")
    if business and business.bank_account_number:
        lines.append(f"Account number: {business.bank_account_number}")
    if business and business.bank_account_name:
        lines.append(f"Account name: {business.bank_account_name}")
    return "\n".join(lines) if lines else "Please contact us for payment details."


def format_payment_request(order: Order, business: Optional[Business]) -> str:
    if business and business.payment_method == "paystack" and order.payment_link:
        return (
            f"Your order *#{order.id}* total is *N{order.total}* (including N{order.delivery_fee} delivery).\n\n"
            f"*Pay securely here:* {order.payment_link}\n\n"
            f"Cards, bank transfer, and USSD all work. Reply *paid* once you're done and we'll confirm instantly. ⚡"
        )
    return (
        f"Your order *#{order.id}* total is *N{order.total}* (including N{order.delivery_fee} delivery).\n\n"
        f"*Please pay to:*\n{format_bank_info(business)}\n\n"
        f"Once you've paid, reply here with confirmation or a photo of your receipt."
    )


def format_order_status_reply(order: Optional[Order], business: Business) -> str:
    if not order or order.status == "cancelled":
        return f"You don't have an active order with *{business.name}*. Reply 'menu' to see what's available. 🛍️"
    if order.status == "awaiting_delivery_fee":
        return (
            f"Order *#{order.id}* is confirmed — we're working out your delivery fee "
            f"and will send your total and payment details shortly."
        )
    if order.status == "awaiting_payment":
        return f"Order *#{order.id}* is awaiting your payment.\n\n{format_payment_request(order, business)}"
    if order.status == "payment_claimed":
        return f"We've received your payment info for order *#{order.id}* — *{business.name}* will confirm it shortly. ✅"
    if order.status == "paid":
        return f"Payment confirmed! Order *#{order.id}* is being prepared. 🧑‍🍳"
    if order.status == "out_for_delivery":
        return f"Order *#{order.id}* is on its way to you! 🚴"
    if order.status == "delivered":
        return f"Order *#{order.id}* was delivered. Reply 'menu' to order again!"
    return f"Order *#{order.id}* status: {order.status}."


def build_help_reply(conversation: Conversation) -> str:
    step_lines = {
        CONV_CATEGORY: "Right now: reply with a category number to browse items.",
        CONV_ITEM: "Right now: reply with an item number to add it to your cart.",
        CONV_NAME: "Right now: reply with the name to put on your order.",
        CONV_ADDRESS: "Right now: reply with your delivery address.",
        CONV_AWAITING_PAYMENT: "Right now: reply with payment confirmation or a photo of your receipt.",
    }
    step = step_lines.get(conversation.stage, "Reply 'menu' to see what's available.")
    return (
        "🤖 *Quick guide*\n"
        "• 'menu' — browse / start a fresh order\n"
        "• 'cart' — view your cart\n"
        "• 'checkout' — place your order\n"
        "• 'status' — check your latest order\n"
        "• 'cancel' — cancel what you're doing\n\n"
        f"{step}"
    )


def record_payment_claim(db, business: Business, conversation: Conversation, order: Order, message: str, media_url: str) -> str:
    # Gateway orders: verify with Paystack right now — no owner action needed
    # when the money has actually landed.
    if business.payment_method == "paystack" and order.payment_reference:
        verified = verify_paystack_order_payment(business, order)
        if verified:
            set_order_status(order, "paid")
            conversation.stage = CONV_NEW
            conversation.address = None
            db.commit()
            if business.owner_notify_number:
                link = order_link(order.id)
                link_line = f"\nOpen: {link}" if link else ""
                send_whatsapp_message(
                    business.owner_notify_number,
                    f"✅ Paystack confirmed payment for order *#{order.id}* (N{order.total}, "
                    f"{order.customer_name or order.customer_phone}) automatically — it's ready to prepare.{link_line}",
                    from_number=business.whatsapp_number,
                )
            return f"🎉 Payment confirmed for order *#{order.id}*! *{business.name}* is preparing your order now."
        if verified is False:
            db.commit()
            return (
                f"Hmm — Paystack hasn't seen your payment for order *#{order.id}* yet. "
                f"If you just paid, give it a minute and reply *paid* again.\n\n"
                f"Pay here if you haven't: {order.payment_link or 'link unavailable — please contact us'}"
            )
        # verified is None: Paystack unreachable — fall through to the manual claim flow.
    if media_url:
        receipt_filename = save_payment_receipt(order.id, media_url)
        if receipt_filename:
            order.payment_receipt_path = receipt_filename
    if message.strip():
        order.payment_proof_text = message.strip()
    set_order_status(order, "payment_claimed")
    conversation.stage = CONV_NEW
    conversation.address = None
    db.commit()
    notify_owner_action(
        business,
        order.id,
        f"🚨 *ACTION NEEDED — confirm payment*\n\nOrder *#{order.id}*: {order.customer_name or order.customer_phone} says they've paid *N{order.total}*. "
        f"Check your bank alert for this exact amount, then mark the order paid so it can move forward.",
    )
    return f"Thanks! We've let *{business.name}* know — they'll confirm your payment shortly. ✅"


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

    latest_order = latest_order_for(db, business.id, conversation.phone_number)
    active_order = latest_order if latest_order and latest_order.status in ACTIVE_ORDER_STATUSES else None
    cart = load_cart(conversation.cart_json)

    # A receipt photo or clear payment message always reaches the pending order,
    # even if the conversation drifted to another stage (e.g. after a greeting reset).
    if (
        latest_order
        and latest_order.status == "awaiting_payment"
        and conversation.stage != CONV_AWAITING_PAYMENT
        and not normalized.endswith("?")
        and (
            media_url
            or (
                not cart
                and conversation.stage in {CONV_NEW, CONV_CATEGORY}
                and any(token in normalized for token in PAYMENT_CLAIM_TOKENS)
            )
        )
    ):
        return record_payment_claim(db, business, conversation, latest_order, message, media_url)

    if normalized in STATUS_WORDS:
        db.commit()
        return format_order_status_reply(latest_order, business) + COLLXCT_FOOTER

    if normalized in HELP_WORDS:
        db.commit()
        return build_help_reply(conversation)

    if normalized in CANCEL_WORDS and conversation.stage in {CONV_CATEGORY, CONV_ITEM, CONV_NAME, CONV_ADDRESS}:
        conversation.cart_json = "[]"
        conversation.customer_name = None
        conversation.address = None
        conversation.category_id = None
        conversation.stage = CONV_NEW
        db.commit()
        return "No problem — cancelled. Reply 'hi' whenever you'd like to start a new order. 👋"

    # Business-hours / subscription gate: status, help, cancel, and payment for
    # an existing order still work above — but shopping is paused while the
    # business is closed or its plan has lapsed past the grace period.
    if conversation.stage in {CONV_NEW, CONV_CATEGORY, CONV_ITEM, CONV_NAME, CONV_ADDRESS}:
        if plan_is_blocked(business):
            db.commit()
            return (
                f"Sorry, *{business.name}* isn't taking WhatsApp orders right now. "
                f"Please check back later.{COLLXCT_FOOTER}"
            )
        if not business_is_open(business):
            db.commit()
            return format_closed_reply(business)

    if normalized in GREETING_WORDS and conversation.stage == CONV_AWAITING_PAYMENT and active_order:
        db.commit()
        return (
            "👋 Welcome back!\n\n" + format_order_status_reply(active_order, business)
            + "\n\nReply 'menu' to start a new order."
        )

    if normalized in GREETING_WORDS and cart and conversation.stage in {CONV_CATEGORY, CONV_ITEM, CONV_NAME, CONV_ADDRESS}:
        resume_prompts = {
            CONV_CATEGORY: "Reply with a category number to keep shopping, or 'checkout' to place your order.",
            CONV_ITEM: "Reply with an item number to add more, or 'checkout' to place your order.",
            CONV_NAME: "What name should we put on this order?",
            CONV_ADDRESS: "Please reply with your delivery address. 📍",
        }
        db.commit()
        return (
            f"👋 Welcome back! You have an order in progress:\n{format_cart_lines(cart)}\n\n"
            f"{resume_prompts[conversation.stage]}\n\n(Reply 'restart' to start over, or 'cancel' to cancel.)"
        )

    if normalized in GREETING_WORDS or normalized in HARD_RESET_WORDS or not conversation.stage:
        conversation.cart_json = "[]"
        conversation.customer_name = None
        conversation.address = None
        reply = build_greeting_reply(db, business, conversation)
        db.commit()
        if active_order:
            reply = (
                f"ℹ️ Your order *#{active_order.id}* is still in progress — reply 'status' anytime to check on it.\n\n"
                + reply
            )
        return reply

    if conversation.stage == CONV_CATEGORY:
        categories = active_categories_for_business(db, business.id)
        if not categories:
            conversation.stage = CONV_NEW
            db.commit()
            return f"Sorry, {business.name} doesn't have any items available right now. Please check back soon."
        if normalized in CART_WORDS:
            if not cart:
                return "Your cart is empty. " + format_category_menu(categories)
            return (
                f"*Your cart:*\n{format_cart_lines(cart)}\n\n*Total:* N{cart_total(cart)}\n\n"
                "Reply 'checkout' to place your order, or pick a category to keep shopping:\n\n"
                + format_category_menu(categories)
            )
        if normalized in CHECKOUT_WORDS:
            if not cart:
                return "Your cart is empty. " + format_category_menu(categories)
            conversation.stage = CONV_NAME
            db.commit()
            return "Great! What name should we put on this order?"
        index = resolve_choice(message, [category.name for category in categories])
        if index is None or index < 1 or index > len(categories):
            if not message.strip() and media_url:
                return "I can only read text here 🙂 — please reply with a number.\n\n" + format_category_menu(categories)
            db.commit()
            return "Sorry, I didn't understand that. " + format_category_menu(categories)
        category = categories[index - 1]
        items = active_items_for_category(db, business.id, category.id)
        conversation.category_id = category.id
        conversation.stage = CONV_ITEM
        db.commit()
        return format_item_menu(items, category.name)

    if conversation.stage == CONV_ITEM:
        items = active_items_for_category(db, business.id, conversation.category_id) if conversation.category_id else []
        if not items:
            # Category was deleted or everything in it went out of stock mid-browse.
            conversation.category_id = None
            categories = active_categories_for_business(db, business.id)
            if not categories:
                conversation.stage = CONV_NEW
                db.commit()
                return f"Sorry, {business.name} doesn't have any items available right now. Please check back soon."
            conversation.stage = CONV_CATEGORY
            db.commit()
            return "Sorry, those items are no longer available. " + format_category_menu(categories)
        if normalized in CART_WORDS:
            if not cart:
                return "Your cart is empty. Reply with a number to add an item."
            return f"*Your cart:*\n{format_cart_lines(cart)}\n\n*Total:* N{cart_total(cart)}\n\nReply 'checkout' to place your order or add another item number."
        if normalized in CLEAR_CART_WORDS:
            conversation.cart_json = "[]"
            db.commit()
            return "🗑️ Cart cleared. Reply with a number to add an item, or 'back' to see other categories."
        if normalized in CHECKOUT_WORDS:
            if not cart:
                return "Your cart is empty. Please add at least one item before checking out."
            conversation.stage = CONV_NAME
            db.commit()
            return "Great! What name should we put on this order?"
        if normalized in BACK_WORDS:
            reply = build_greeting_reply(db, business, conversation)
            db.commit()
            return reply
        index = resolve_choice(message, [item.name for item in items])
        if index is None or index < 1 or index > len(items):
            category = db.query(Category).filter(Category.id == conversation.category_id).one_or_none()
            if not message.strip() and media_url:
                return "I can only read text here 🙂 — please reply with a number.\n\n" + format_item_menu(items, category.name if category else "Menu")
            return "Sorry, I didn't understand that. " + format_item_menu(items, category.name if category else "Menu")
        item = items[index - 1]
        for entry in cart:
            if entry.get("item_id") == item.id:
                entry["qty"] = int(entry.get("qty", 1)) + 1
                break
        else:
            cart.append({"item_id": item.id, "name": item.name, "description": item.description or "", "price": item.price, "qty": 1})
        conversation.cart_json = json.dumps(cart)
        db.commit()
        return f"✅ Added *{item.name}* to your cart. Reply with another number to add more, 'cart' to view your cart, or 'checkout' to place your order."

    if conversation.stage == CONV_NAME:
        name = message.strip()
        if normalized in BACK_WORDS:
            items = active_items_for_category(db, business.id, conversation.category_id) if conversation.category_id else []
            if items:
                conversation.stage = CONV_ITEM
                db.commit()
                category = db.query(Category).filter(Category.id == conversation.category_id).one_or_none()
                return format_item_menu(items, category.name if category else "Menu")
            reply = build_greeting_reply(db, business, conversation)
            db.commit()
            return reply
        if normalized in CART_WORDS:
            return f"*Your cart:*\n{format_cart_lines(cart)}\n\n*Total:* N{cart_total(cart)}\n\nWhat name should we put on this order?"
        if normalized in CHECKOUT_WORDS:
            return "Almost there! What name should we put on this order?"
        if not name:
            if media_url:
                return "I can't read a name from an image 🙂 — please type it. What name should we put on this order?"
            return "Please share your name so the business knows who's ordering."
        if name.isdigit():
            return "That looks like a number 🙂 — please reply with the name to put on this order."
        conversation.customer_name = name[:255]
        conversation.stage = CONV_ADDRESS
        db.commit()
        return f"Thanks, {conversation.customer_name}! Please reply with your delivery address. 📍"

    if conversation.stage == CONV_ADDRESS:
        address = message.strip()
        if normalized in BACK_WORDS:
            conversation.stage = CONV_NAME
            db.commit()
            return "Sure — what name should we put on this order?"
        if normalized in CART_WORDS:
            return f"*Your cart:*\n{format_cart_lines(cart)}\n\n*Total:* N{cart_total(cart)}\n\nPlease reply with your delivery address. 📍"
        if normalized in CHECKOUT_WORDS:
            return "Almost done! Please reply with your delivery address. 📍"
        if not address:
            if media_url:
                return "I can't read an address from an image 🙂 — please type it. Where should we deliver to?"
            return "Please share a delivery address so we can complete your order."
        if len(address) < 5 or not any(ch.isalpha() for ch in address):
            return "That doesn't look like a full address 🙂 — please include your street and area so the rider can find you. 📍"
        subtotal = cart_total(cart)
        auto = compute_auto_delivery_fee(business, address)
        order = Order(
            business_id=business.id,
            branch_id=conversation.branch_id,
            customer_phone=conversation.phone_number,
            customer_name=conversation.customer_name,
            items_json=conversation.cart_json or "[]",
            total=subtotal + (auto["fee"] if auto else 0),
            delivery_fee=auto["fee"] if auto else 0,
            address=address,
            status="awaiting_payment" if auto else "awaiting_delivery_fee",
            status_changed_at=datetime.utcnow(),
            address_unverified=1 if (business.delivery_autocalc and not auto) else 0,
        )
        db.add(order)
        conversation.cart_json = "[]"
        conversation.address = address
        conversation.category_id = None
        conversation.stage = CONV_AWAITING_PAYMENT
        db.commit()
        name_prefix = f"Thanks, {conversation.customer_name}! " if conversation.customer_name else "Thanks! "
        notify_order_cap_usage(db, business)
        if auto:
            if business.payment_method == "paystack":
                create_paystack_order_link(business, order)
                db.commit()
            if business.owner_notify_number:
                link = order_link(order.id)
                link_line = f"\nOpen: {link}" if link else ""
                send_whatsapp_message(
                    business.owner_notify_number,
                    f"🆕 New order *#{order.id}* from {conversation.customer_name or conversation.phone_number} — "
                    f"delivery auto-priced at N{auto['fee']} ({auto['km']} km). Payment details sent to the customer; "
                    f"nothing to do until payment lands.{link_line}",
                    from_number=business.whatsapp_number,
                )
            return (
                f"{name_prefix}Here's your order:\n{format_cart_lines(cart)}\n\n"
                f"*Subtotal:* N{subtotal}\n*Delivery ({auto['km']} km):* N{auto['fee']}\n*Total:* N{order.total}\n"
                f"*Deliver to:* {address}\n\n" + format_payment_request(order, business) + COLLXCT_FOOTER
            )
        unlocated_note = (
            "\n\n⚠️ This address couldn't be located on the map, so the fee wasn't auto-calculated."
            if business.delivery_autocalc else ""
        )
        notify_owner_action(
            business,
            order.id,
            f"🚨 *ACTION NEEDED — new order #{order.id}*\n\n"
            f"From: {conversation.customer_name or conversation.phone_number} ({conversation.phone_number})\n"
            f"{format_cart_lines(cart)}\n*Subtotal:* N{subtotal}\n*Deliver to:* {address}\n\n"
            f"Set the delivery fee now — the customer can't pay until you do.{unlocated_note}",
        )
        return (
            f"{name_prefix}Here's your order:\n{format_cart_lines(cart)}\n\n*Subtotal:* N{subtotal}\n*Delivery to:* {address}\n\n"
            f"We're confirming your delivery fee now and will send your full total and payment details shortly.{COLLXCT_FOOTER}"
        )

    if conversation.stage == CONV_AWAITING_PAYMENT:
        order = latest_order
        if not order or order.status == "cancelled":
            reply = build_greeting_reply(db, business, conversation)
            db.commit()
            return reply
        if order.status == "awaiting_delivery_fee":
            if normalized in CANCEL_WORDS:
                set_order_status(order, "cancelled")
                conversation.stage = CONV_NEW
                conversation.address = None
                db.commit()
                return "Your order has been cancelled. Reply 'hi' anytime to start a new order."
            return "We're still confirming your delivery fee — hang tight, we'll send your total and payment details shortly. Reply 'status' anytime, or 'cancel' to cancel this order."
        if order.status == "awaiting_payment":
            if normalized in CANCEL_WORDS:
                set_order_status(order, "cancelled")
                conversation.stage = CONV_NEW
                conversation.address = None
                db.commit()
                return "Your order has been cancelled. Reply 'hi' anytime to start a new order."
            if not media_url and not message.strip():
                return "Please reply with confirmation that you've made the transfer — a text message or a photo of your receipt works."
            # Questions ("how much?", "which account?") re-send the payment details
            # instead of being swallowed as payment proof.
            is_claim = bool(media_url) or any(token in normalized for token in PAYMENT_CLAIM_TOKENS)
            if not is_claim and (normalized.endswith("?") or any(token in normalized for token in PAYMENT_INFO_TOKENS)):
                return format_payment_request(order, business)
            return record_payment_claim(db, business, conversation, order, message, media_url)
        return "We've already received your payment info for this order. The business will confirm shortly. Reply 'status' anytime for updates."

    reply = build_greeting_reply(db, business, conversation)
    db.commit()
    if active_order:
        reply = (
            f"ℹ️ Your order *#{active_order.id}* is still in progress — reply 'status' anytime to check on it.\n\n"
            + reply
        )
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
        # The JSON body is an unauthenticated test convenience. Once Twilio is
        # configured, only signed Twilio form posts are accepted — otherwise
        # anyone could impersonate a customer's phone number.
        if os.getenv("TWILIO_AUTH_TOKEN") and os.getenv("ALLOW_JSON_WEBHOOK") != "1":
            return Response(content="JSON webhook disabled in production", status_code=403)
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
def homepage(request: Request, sent: Optional[str] = None) -> HTMLResponse:
    db = SessionLocal()
    try:
        plans = db.query(Plan).order_by(Plan.price_ngn).all()
    finally:
        db.close()

    plan_cards = ""
    for i, plan in enumerate(plans):
        featured = " featured" if i == len(plans) - 1 else ""
        badge = "<span class='lp-plan-badge'>Most popular</span>" if featured else ""
        cap_line = f"{plan.monthly_order_cap:,} orders/month included" if plan.monthly_order_cap else "Unlimited orders"
        branch_line = "Multiple branches &amp; locations" if plan.branch_access == 1 else "Single location"
        plan_cards += f"""
        <div class="lp-plan{featured}">
          {badge}
          <h3>{escape(plan.name)}</h3>
          <div class="lp-price">₦{plan.price_ngn:,}<span>/month</span></div>
          <div class="lp-price-alt">or ₦{plan.price_ngn * ANNUAL_MONTHS_CHARGED:,}/year — 2 months free</div>
          <ul>
            <li>{cap_line}</li>
            <li>{branch_line}</li>
            <li>WhatsApp ordering bot, fully managed</li>
            <li>Owner alerts &amp; payment confirmation</li>
            <li>Web dashboard &amp; live order queue</li>
          </ul>
          <a class="lp-btn{' lp-btn-primary' if featured else ''}" href="#contact">Get started</a>
        </div>
        """

    if sent == "1":
        contact_notice = "<div class='lp-notice ok'>✅ Thanks — we got your message! We'll reply within one business day.</div>"
    elif sent == "0":
        contact_notice = "<div class='lp-notice'>📬 Your message was saved — we'll get back to you shortly.</div>"
    else:
        contact_notice = ""

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Collxct — Turn WhatsApp into your ordering machine</title>
        <meta name="description" content="Collxct gives Nigerian businesses a WhatsApp ordering bot: menus, carts, automatic delivery fees, instant Paystack payment links, and a live dashboard." />
        <link rel="icon" type="image/svg+xml" href="/static/img/logo-icon.svg" />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet" />
        <style>
          :root {{
            --bg:#090c0b; --surface:#101413; --surface-2:#161c1a; --text:#f1f5f3; --muted:#93a29b;
            --green:#10b981; --green-strong:#34d399; --gold:#f59e0b;
            --border:rgba(255,255,255,.08); --border-strong:rgba(255,255,255,.16);
          }}
          * {{ box-sizing:border-box; margin:0; }}
          html {{ scroll-behavior:smooth; }}
          body {{ font-family:'Inter',system-ui,sans-serif; background:var(--bg); color:var(--text); line-height:1.6; }}
          .wrap {{ max-width:1100px; margin:0 auto; padding:0 22px; }}
          .lp-nav {{ position:sticky; top:0; z-index:50; backdrop-filter:blur(12px); background:rgba(9,12,11,.8); border-bottom:1px solid var(--border); }}
          .lp-nav .wrap {{ display:flex; align-items:center; gap:22px; height:64px; }}
          .lp-nav img {{ height:30px; display:block; }}
          .lp-nav a {{ color:var(--muted); text-decoration:none; font-size:.9rem; font-weight:600; }}
          .lp-nav a:hover {{ color:var(--text); }}
          .lp-nav .spacer {{ flex:1; }}
          .lp-btn {{ display:inline-block; padding:11px 20px; border-radius:10px; font-weight:700; font-size:.92rem; text-decoration:none; border:1px solid var(--border-strong); color:var(--text); transition:transform .12s ease, background .15s ease; }}
          .lp-btn:hover {{ transform:translateY(-1px); background:var(--surface-2); }}
          .lp-btn-primary {{ background:linear-gradient(135deg,#34d399,#059669); border-color:transparent; color:#03130c; box-shadow:0 8px 24px rgba(16,185,129,.35); }}
          .lp-hero {{ padding:88px 0 60px; background:radial-gradient(900px circle at 15% 0%, rgba(16,185,129,.16), transparent 55%), radial-gradient(700px circle at 95% 15%, rgba(245,158,11,.08), transparent 50%); }}
          .lp-hero .wrap {{ display:grid; grid-template-columns:1.15fr .85fr; gap:48px; align-items:center; }}
          .lp-eyebrow {{ display:inline-block; padding:6px 14px; border-radius:999px; border:1px solid rgba(52,211,153,.35); background:rgba(52,211,153,.1); color:var(--green-strong); font-size:.78rem; font-weight:700; letter-spacing:.06em; text-transform:uppercase; margin-bottom:18px; }}
          h1 {{ font-size:clamp(2rem,4.6vw,3.3rem); line-height:1.08; letter-spacing:-.03em; font-weight:900; }}
          h1 .grad {{ background:linear-gradient(90deg,#34d399,#f59e0b); -webkit-background-clip:text; background-clip:text; color:transparent; }}
          .lp-hero p.sub {{ margin:20px 0 28px; color:var(--muted); font-size:1.08rem; max-width:520px; }}
          .hero-ctas {{ display:flex; gap:12px; flex-wrap:wrap; }}
          .hero-facts {{ display:flex; gap:26px; margin-top:34px; flex-wrap:wrap; }}
          .hero-facts div strong {{ display:block; font-size:1.25rem; letter-spacing:-.02em; }}
          .hero-facts div span {{ color:var(--muted); font-size:.82rem; }}
          .phone {{ background:linear-gradient(160deg,#111815,#0b100e); border:1px solid var(--border-strong); border-radius:34px; padding:18px 14px; box-shadow:0 30px 70px rgba(0,0,0,.55), inset 0 1px 0 rgba(255,255,255,.06); max-width:360px; margin-left:auto; width:100%; }}
          .phone-head {{ display:flex; align-items:center; gap:10px; padding:4px 8px 12px; border-bottom:1px solid var(--border); margin-bottom:12px; }}
          .phone-avatar {{ width:34px; height:34px; border-radius:50%; background:linear-gradient(135deg,#34d399,#059669); display:flex; align-items:center; justify-content:center; font-weight:800; color:#03130c; }}
          .phone-head b {{ font-size:.92rem; }} .phone-head small {{ color:var(--green-strong); font-size:.72rem; display:block; }}
          .bubble {{ max-width:85%; padding:9px 13px; border-radius:14px; font-size:.84rem; margin-bottom:9px; line-height:1.45; }}
          .them {{ background:var(--surface-2); border:1px solid var(--border); border-bottom-left-radius:4px; }}
          .me {{ background:#0c3d2c; border:1px solid rgba(52,211,153,.25); margin-left:auto; border-bottom-right-radius:4px; }}
          section {{ padding:72px 0; }}
          .sec-head {{ text-align:center; max-width:640px; margin:0 auto 44px; }}
          .sec-head h2 {{ font-size:clamp(1.5rem,3vw,2.2rem); letter-spacing:-.02em; font-weight:800; }}
          .sec-head p {{ color:var(--muted); margin-top:10px; }}
          .feat-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:16px; }}
          .feat {{ background:var(--surface); border:1px solid var(--border); border-radius:16px; padding:22px; transition:transform .15s ease, border-color .15s ease; }}
          .feat:hover {{ transform:translateY(-3px); border-color:rgba(52,211,153,.35); }}
          .feat .ico {{ font-size:1.5rem; }}
          .feat h3 {{ font-size:1rem; margin:10px 0 6px; }}
          .feat p {{ color:var(--muted); font-size:.88rem; }}
          .steps {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:16px; counter-reset:step; margin-top:26px; }}
          .step {{ background:var(--bg); border:1px solid var(--border); border-radius:16px; padding:24px; position:relative; }}
          .step::before {{ counter-increment:step; content:counter(step); position:absolute; top:-14px; left:20px; width:30px; height:30px; border-radius:50%; background:linear-gradient(135deg,#34d399,#059669); color:#03130c; font-weight:800; display:flex; align-items:center; justify-content:center; font-size:.9rem; }}
          .step h3 {{ font-size:.98rem; margin-bottom:6px; margin-top:4px; }}
          .step p {{ color:var(--muted); font-size:.86rem; }}
          .lp-plans {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:18px; align-items:stretch; max-width:760px; margin:0 auto; }}
          .lp-plan {{ background:var(--surface); border:1px solid var(--border); border-radius:18px; padding:28px; display:flex; flex-direction:column; position:relative; }}
          .lp-plan.featured {{ border-color:rgba(52,211,153,.5); box-shadow:0 0 0 1px rgba(52,211,153,.35), 0 20px 50px rgba(0,0,0,.4); }}
          .lp-plan-badge {{ position:absolute; top:-12px; right:20px; background:linear-gradient(135deg,#34d399,#059669); color:#03130c; font-size:.7rem; font-weight:800; padding:4px 12px; border-radius:999px; letter-spacing:.04em; }}
          .lp-plan h3 {{ font-size:1.05rem; }}
          .lp-price {{ font-size:2rem; font-weight:900; letter-spacing:-.03em; margin-top:8px; }}
          .lp-price span {{ font-size:.9rem; font-weight:500; color:var(--muted); }}
          .lp-price-alt {{ color:var(--gold); font-size:.82rem; font-weight:600; margin-bottom:14px; }}
          .lp-plan ul {{ list-style:none; padding:0; margin:0 0 22px; flex:1; }}
          .lp-plan li {{ padding:7px 0 7px 26px; position:relative; color:var(--muted); font-size:.88rem; border-bottom:1px solid var(--border); }}
          .lp-plan li::before {{ content:"✓"; position:absolute; left:2px; color:var(--green-strong); font-weight:800; }}
          .lp-plan .lp-btn {{ text-align:center; }}
          .lp-setup {{ margin-top:18px; text-align:center; color:var(--muted); font-size:.9rem; max-width:640px; margin-left:auto; margin-right:auto; }}
          .lp-setup strong {{ color:var(--gold); }}
          .req-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:14px; }}
          .req {{ display:flex; gap:12px; align-items:flex-start; background:var(--surface); border:1px solid var(--border); border-radius:14px; padding:16px 18px; }}
          .req .tick {{ color:var(--green-strong); font-weight:800; }}
          .req div b {{ font-size:.92rem; display:block; }}
          .req div span {{ color:var(--muted); font-size:.82rem; }}
          .contact-grid {{ display:grid; grid-template-columns:1fr 1.1fr; gap:34px; align-items:start; }}
          .contact-info h2 {{ font-size:1.7rem; letter-spacing:-.02em; margin-bottom:12px; }}
          .contact-info p {{ color:var(--muted); margin-bottom:16px; }}
          .contact-card {{ background:var(--bg); border:1px solid var(--border); border-radius:18px; padding:28px; }}
          .contact-card input, .contact-card textarea {{ width:100%; padding:12px 14px; margin-bottom:12px; border-radius:10px; border:1px solid var(--border-strong); background:var(--surface-2); color:var(--text); font-family:inherit; font-size:.92rem; }}
          .contact-card input:focus, .contact-card textarea:focus {{ outline:none; border-color:var(--green); box-shadow:0 0 0 3px rgba(16,185,129,.18); }}
          .contact-card button {{ width:100%; padding:13px; border:none; border-radius:10px; background:linear-gradient(135deg,#34d399,#059669); color:#03130c; font-weight:800; font-size:.95rem; cursor:pointer; font-family:inherit; }}
          .contact-card button:hover {{ filter:brightness(1.08); }}
          .lp-notice {{ padding:13px 16px; border-radius:12px; border:1px solid rgba(245,158,11,.4); background:rgba(245,158,11,.08); color:#ffd866; font-size:.9rem; margin-bottom:16px; }}
          .lp-notice.ok {{ border-color:rgba(52,211,153,.4); background:rgba(52,211,153,.08); color:var(--green-strong); }}
          .hp-field {{ position:absolute; left:-9999px; opacity:0; height:0; }}
          footer {{ border-top:1px solid var(--border); padding:34px 0; }}
          footer .wrap {{ display:flex; align-items:center; gap:18px; flex-wrap:wrap; }}
          footer img {{ height:26px; }}
          footer span {{ color:var(--muted); font-size:.84rem; }}
          footer .spacer {{ flex:1; }}
          @media (max-width:860px) {{
            .lp-hero .wrap {{ grid-template-columns:1fr; }}
            .phone {{ margin:0 auto; }}
            .contact-grid {{ grid-template-columns:1fr; }}
            .lp-nav a.hide-sm {{ display:none; }}
          }}
        </style>
      </head>
      <body>
        <nav class="lp-nav">
          <div class="wrap">
            <a href="/"><img src="/static/img/logo-white.svg" alt="Collxct" /></a>
            <span class="spacer"></span>
            <a class="hide-sm" href="#features">Features</a>
            <a class="hide-sm" href="#how">How it works</a>
            <a class="hide-sm" href="#pricing">Pricing</a>
            <a class="hide-sm" href="#contact">Contact</a>
            <a class="lp-btn" href="/login">Log in</a>
            <a class="lp-btn lp-btn-primary" href="#contact">Get started</a>
          </div>
        </nav>

        <header class="lp-hero">
          <div class="wrap">
            <div>
              <span class="lp-eyebrow">WhatsApp ordering for Nigerian businesses</span>
              <h1>Turn WhatsApp into your <span class="grad">ordering machine</span>.</h1>
              <p class="sub">Your customers already live on WhatsApp. Collxct gives them a menu, a cart, automatic delivery fees, and instant payment — while you run everything from one dashboard that won't let an order slip.</p>
              <div class="hero-ctas">
                <a class="lp-btn lp-btn-primary" href="#contact">Set up my business</a>
                <a class="lp-btn" href="#how">See how it works</a>
              </div>
              <div class="hero-facts">
                <div><strong>24–48h</strong><span>to go live</span></div>
                <div><strong>24/7</strong><span>orders taken for you</span></div>
                <div><strong>0 missed</strong><span>orders — loud alerts</span></div>
              </div>
            </div>
            <div class="phone">
              <div class="phone-head">
                <div class="phone-avatar">C</div>
                <div><b>Mama Ada's Kitchen</b><small>online</small></div>
              </div>
              <div class="bubble me">Hi 👋</div>
              <div class="bubble them">Hi! 👋 Welcome to <b>Mama Ada's Kitchen</b>.<br />Choose a category:<br /><b>1.</b> Meals&nbsp;&nbsp;<b>2.</b> Drinks</div>
              <div class="bubble me">1</div>
              <div class="bubble them"><b>1.</b> Jollof Rice — ₦1,500<br /><b>2.</b> Fried Chicken — ₦2,500</div>
              <div class="bubble me">1, then checkout</div>
              <div class="bubble them">Delivery to Lekki Phase 1 is <b>₦1,400</b> (4.2 km).<br />Total: <b>₦2,900</b> — 💳 pay securely: <span style="color:#34d399;">paystack.com/…</span></div>
              <div class="bubble them">🎉 Payment confirmed! Your order is being prepared.</div>
            </div>
          </div>
        </header>

        <section id="features">
          <div class="wrap">
            <div class="sec-head">
              <h2>Everything the bot does for you</h2>
              <p>From "hi" to "delivered" — the whole ordering journey runs itself, and pulls you in only when you're truly needed.</p>
            </div>
            <div class="feat-grid">
              <div class="feat"><div class="ico">🛍️</div><h3>Menu &amp; cart on WhatsApp</h3><p>Categories, item descriptions, quantities, and a running cart — customers order by replying with simple numbers.</p></div>
              <div class="feat"><div class="ico">📍</div><h3>Automatic delivery fees</h3><p>Fees calculated from real distance to the customer's address, priced like ride apps: base fare + per-km. Unmappable address? You set the fee in one tap.</p></div>
              <div class="feat"><div class="ico">💳</div><h3>Instant payment links</h3><p>Paystack checkout — card, transfer, USSD — confirmed automatically the second the money lands. Prefer bank transfer? That works too.</p></div>
              <div class="feat"><div class="ico">🚨</div><h3>Alerts you can't miss</h3><p>New orders ring your dashboard with a loud chime until handled, plus WhatsApp pings and reminders every 10 minutes.</p></div>
              <div class="feat"><div class="ico">⏰</div><h3>Opening hours</h3><p>The bot politely tells customers when you're closed and starts selling again the minute you open. Overnight hours supported.</p></div>
              <div class="feat"><div class="ico">📦</div><h3>Live order tracking</h3><p>Customers check status anytime; you move orders through paid → out for delivery → delivered with one tap each.</p></div>
              <div class="feat"><div class="ico">🏪</div><h3>Branches &amp; stock control</h3><p>Multiple locations, per-branch menus, and out-of-stock toggles that update the bot instantly.</p></div>
              <div class="feat"><div class="ico">🔐</div><h3>Serious security</h3><p>Two-factor authentication, encrypted sessions, and payments that settle straight to your own account — we never hold your money.</p></div>
            </div>
          </div>
        </section>

        <section id="how" style="background:var(--surface); border-top:1px solid var(--border); border-bottom:1px solid var(--border);">
          <div class="wrap">
            <div class="sec-head">
              <h2>Live in four simple steps</h2>
              <p>No paperwork needed to start — we can launch on a trial while you finish your payment setup.</p>
            </div>
            <div class="steps">
              <div class="step"><h3>Tell us about your business</h3><p>Your WhatsApp number, menu with prices, opening hours, and how you want to get paid.</p></div>
              <div class="step"><h3>We build your bot</h3><p>Menu, categories, branches, delivery pricing, and payment details — all configured for you.</p></div>
              <div class="step"><h3>Test it together</h3><p>You place a real order end-to-end and watch it land on your dashboard with the alert chime.</p></div>
              <div class="step"><h3>Go live in 24–48 hours</h3><p>Share your WhatsApp number everywhere. Orders start flowing; you stay in control.</p></div>
            </div>
          </div>
        </section>

        <section id="pricing">
          <div class="wrap">
            <div class="sec-head">
              <h2>Simple, honest pricing</h2>
              <p>One-time setup, then a flat monthly plan. WhatsApp messaging costs included — no per-message surprises.</p>
            </div>
            <div class="lp-plans">
              {plan_cards}
            </div>
            <p class="lp-setup">+ one-time onboarding &amp; setup fee: <strong>₦{ONBOARDING_FEE_NGN:,}</strong> — covers your menu build, payment setup, and a guided test launch. Order caps are soft: we never block your sales, we just talk about the right plan.</p>
          </div>
        </section>

        <section id="requirements" style="padding-top:0;">
          <div class="wrap">
            <div class="sec-head">
              <h2>What we need to onboard you</h2>
              <p>Have these ready and setup takes a single afternoon.</p>
            </div>
            <div class="req-grid">
              <div class="req"><span class="tick">✓</span><div><b>A WhatsApp number</b><span>The number customers will order from (we can help you set up a business number).</span></div></div>
              <div class="req"><span class="tick">✓</span><div><b>Your menu &amp; prices</b><span>A simple list or photo is fine — we'll structure it into categories for the bot.</span></div></div>
              <div class="req"><span class="tick">✓</span><div><b>How you get paid</b><span>Bank account details, or a free Paystack account for instant payment links.</span></div></div>
              <div class="req"><span class="tick">✓</span><div><b>Opening hours &amp; delivery</b><span>When you sell, where you deliver from, and your delivery pricing (or let us auto-calculate it).</span></div></div>
            </div>
          </div>
        </section>

        <section id="contact" style="background:var(--surface); border-top:1px solid var(--border);">
          <div class="wrap">
            <div class="contact-grid">
              <div class="contact-info">
                <h2>Ready to stop missing orders?</h2>
                <p>Tell us about your business and we'll reply within one business day — usually much faster. Prefer email? Write to <a href="mailto:{CONTACT_EMAIL}" style="color:var(--green-strong);">{CONTACT_EMAIL}</a>.</p>
                <p>We'll walk you through setup, build your menu, and stay with you until your first live orders are flowing.</p>
              </div>
              <div class="contact-card">
                {contact_notice}
                <form method="post" action="/contact">
                  <input name="name" placeholder="Your name" required />
                  <input name="business_name" placeholder="Business name" />
                  <input name="phone" placeholder="WhatsApp / phone number" required />
                  <input name="email" type="email" placeholder="Email (optional)" />
                  <textarea name="message" rows="4" placeholder="Tell us what you sell and where you are…" required></textarea>
                  <input class="hp-field" type="text" name="website" tabindex="-1" autocomplete="off" />
                  <button type="submit">Request my setup →</button>
                </form>
              </div>
            </div>
          </div>
        </section>

        <footer>
          <div class="wrap">
            <img src="/static/img/logo-white.svg" alt="Collxct" />
            <span>WhatsApp ordering, done properly.</span>
            <span class="spacer"></span>
            <span><a href="mailto:{CONTACT_EMAIL}" style="color:var(--muted);">{CONTACT_EMAIL}</a> · <a href="/login" style="color:var(--muted);">Portal login</a></span>
          </div>
        </footer>
      </body>
    </html>
    """
    return HTMLResponse(html)


@app.post("/contact")
def contact_submit(
    request: Request,
    name: str = Form(...),
    phone: str = Form(...),
    message: str = Form(...),
    business_name: str = Form(default=""),
    email: str = Form(default=""),
    website: str = Form(default=""),
) -> RedirectResponse:
    # Honeypot: real visitors never fill the invisible "website" field.
    if website.strip():
        return RedirectResponse(url="/?sent=1#contact", status_code=303)
    throttle_key = f"contact|{client_ip(request)}"
    if login_rate_limited(throttle_key):
        return RedirectResponse(url="/?sent=0#contact", status_code=303)
    record_login_failure(throttle_key)

    emailed = False
    db = SessionLocal()
    try:
        entry = ContactMessage(
            name=name.strip()[:255],
            business_name=business_name.strip()[:255] or None,
            phone=phone.strip()[:50] or None,
            email=email.strip()[:255] or None,
            message=message.strip()[:4000],
        )
        db.add(entry)
        db.commit()
        emailed = send_email(
            subject=f"New Collxct lead: {entry.name}" + (f" ({entry.business_name})" if entry.business_name else ""),
            body=(
                f"Name: {entry.name}\nBusiness: {entry.business_name or '-'}\n"
                f"Phone/WhatsApp: {entry.phone or '-'}\nEmail: {entry.email or '-'}\n\n"
                f"Message:\n{entry.message}\n\nSent from the Collxct landing page contact form."
            ),
            to_address=CONTACT_EMAIL,
        )
        if emailed:
            entry.emailed = 1
            db.commit()
    finally:
        db.close()
    return RedirectResponse(url=f"/?sent={'1' if emailed else '0'}#contact", status_code=303)


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
def login_submit(request: Request, email: str = Form(...), password: str = Form(...)):
    throttle_key = f"{client_ip(request)}|{email.strip().lower()}"
    if login_rate_limited(throttle_key):
        body = """
        <div class="card">
          <h3>Too many login attempts</h3>
          <p class="form-hint">For your security, this account is temporarily locked. Try again in about 15 minutes.</p>
          <div class="form-actions"><a class="btn" href="/login">Back to login</a></div>
        </div>
        """
        return render_page("Too Many Attempts", body, nav_html=make_nav(None))
    db = SessionLocal()
    try:
        user = get_user_by_email(db, email)
        if user and verify_password(password, user.password_hash):
            if not user.password_hash.startswith("pbkdf2:"):
                user.password_hash = hash_password(password)
                db.commit()
            _login_attempts.pop(throttle_key, None)
            if user.totp_enabled and user.totp_secret:
                is_https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
                redirect = RedirectResponse(url="/login/verify", status_code=303)
                redirect.set_cookie(
                    key="pending_2fa", value=create_pending_2fa_token(user.email), httponly=True,
                    samesite="lax", secure=is_https, max_age=PENDING_2FA_TTL_SECONDS,
                )
                return redirect
            return issue_session_redirect(request, user)
    finally:
        db.close()
    record_login_failure(throttle_key)
    return RedirectResponse(url="/login", status_code=303)


def landing_url_for(user: User) -> str:
    if user.role == "admin":
        return "/admin/"
    if user.role in {"business_owner", "business-owner", "owner"}:
        return "/owner/portal" if not user.business_id else f"/business/{user.business_id}/dashboard"
    return "/"


def issue_session_redirect(request: Request, user: User) -> RedirectResponse:
    token = create_auth_token(user.email)
    is_https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    redirect = RedirectResponse(url=landing_url_for(user), status_code=303)
    redirect.set_cookie(
        key="auth_token", value=token, httponly=True, samesite="lax",
        secure=is_https, max_age=AUTH_TOKEN_TTL_SECONDS,
    )
    redirect.delete_cookie("pending_2fa")
    return redirect


@app.get("/login/verify", response_class=HTMLResponse)
def login_verify_page(request: Request) -> HTMLResponse:
    if not verify_pending_2fa_token(request.cookies.get("pending_2fa", "")):
        return RedirectResponse(url="/login", status_code=303)
    body = """
    <div class="auth-shell">
      <div class="auth-hero">
        <div class="eyebrow">Two-factor authentication</div>
        <h2>One more step</h2>
        <p>Enter the 6-digit code from your authenticator app to finish signing in.</p>
      </div>
      <div class="card auth-form">
        <h2>Enter your code</h2>
        <form method="post" action="/login/verify">
          <div class="form-row">
            <input name="code" inputmode="numeric" pattern="[0-9 ]*" placeholder="123 456" autocomplete="one-time-code" autofocus required />
          </div>
          <div class="form-actions">
            <button type="submit">Verify</button>
            <a class="btn" href="/login">Start over</a>
          </div>
        </form>
      </div>
    </div>
    """
    return render_page("Verify Sign-in", body, nav_html=make_nav(None))


@app.post("/login/verify")
def login_verify_submit(request: Request, code: str = Form(...)):
    email = verify_pending_2fa_token(request.cookies.get("pending_2fa", ""))
    if not email:
        return RedirectResponse(url="/login", status_code=303)
    throttle_key = f"2fa|{client_ip(request)}|{email.lower()}"
    if login_rate_limited(throttle_key):
        return RedirectResponse(url="/login", status_code=303)
    db = SessionLocal()
    try:
        user = get_user_by_email(db, email)
        if user and user.totp_enabled and verify_totp(user.totp_secret, code):
            _login_attempts.pop(throttle_key, None)
            return issue_session_redirect(request, user)
    finally:
        db.close()
    record_login_failure(throttle_key)
    return RedirectResponse(url="/login/verify", status_code=303)


@app.get("/account/security", response_class=HTMLResponse)
def account_security(request: Request) -> HTMLResponse:
    current_user = get_current_user(request)
    if not current_user or current_user.role not in STAFF_ROLES:
        return RedirectResponse(url="/login", status_code=303)
    if current_user.totp_enabled:
        body = """
        <div class="card">
          <div class="section-head">
            <h3>Two-factor authentication</h3>
            <span class="status-pill">✅ Enabled</span>
          </div>
          <p>Every sign-in to this account requires a code from your authenticator app.</p>
          <form method="post" action="/account/security/disable">
            <label>Current code <input name="code" inputmode="numeric" placeholder="123456" required /></label>
            <div class="form-actions">
              <button type="submit" class="btn">Disable 2FA</button>
            </div>
          </form>
        </div>
        """
        return render_page("Account Security", body, nav_html=make_nav(current_user))

    # Not yet enabled: make sure a secret exists to enrol against.
    db = SessionLocal()
    try:
        user = get_user_by_email(db, current_user.email)
        if not user.totp_secret:
            user.totp_secret = generate_totp_secret()
            db.commit()
        secret = user.totp_secret
    finally:
        db.close()
    uri = totp_provisioning_uri(current_user.email, secret)
    body = f"""
    <div class="card">
      <div class="section-head">
        <h3>Enable two-factor authentication</h3>
        <span class="status-pill" style="background:rgba(255,196,0,.12);border-color:rgba(255,196,0,.35);color:#ffd866;">Not enabled</span>
      </div>
      <p>Add a second lock on your account: after your password, sign-in will also require a 6-digit code from an authenticator app (Google Authenticator, Authy, 1Password…).</p>
      <ol>
        <li>Open your authenticator app and choose <strong>Add account → Enter setup key</strong>.</li>
        <li>Account name: <code>{escape(current_user.email)}</code> — Key: <code>{escape(secret)}</code> (time-based).</li>
        <li>On a phone you can also tap this link directly: <a href="{escape(uri)}">{escape(uri)}</a></li>
        <li>Enter the code the app shows to confirm:</li>
      </ol>
      <form method="post" action="/account/security/enable">
        <input name="code" inputmode="numeric" placeholder="123456" required />
        <div class="form-actions">
          <button type="submit">Turn on 2FA</button>
        </div>
      </form>
    </div>
    """
    return render_page("Account Security", body, nav_html=make_nav(current_user))


@app.post("/account/security/enable")
def account_security_enable(request: Request, code: str = Form(...)) -> RedirectResponse:
    current_user = get_current_user(request)
    if not current_user or current_user.role not in STAFF_ROLES:
        return RedirectResponse(url="/login", status_code=303)
    db = SessionLocal()
    try:
        user = get_user_by_email(db, current_user.email)
        if user and user.totp_secret and verify_totp(user.totp_secret, code):
            user.totp_enabled = 1
            db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/account/security", status_code=303)


@app.post("/account/security/disable")
def account_security_disable(request: Request, code: str = Form(...)) -> RedirectResponse:
    current_user = get_current_user(request)
    if not current_user or current_user.role not in STAFF_ROLES:
        return RedirectResponse(url="/login", status_code=303)
    db = SessionLocal()
    try:
        user = get_user_by_email(db, current_user.email)
        if user and user.totp_enabled and verify_totp(user.totp_secret, code):
            user.totp_enabled = 0
            user.totp_secret = None
            db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/account/security", status_code=303)


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
    current_user = get_current_user(request)
    if not current_user or current_user.role != "admin":
        return RedirectResponse(url="/login", status_code=303)
    db = SessionLocal()
    try:
        businesses = db.query(Business).order_by(Business.id).all()
        business_names = {b.id: b.name for b in businesses}
        action_orders = action_needed_orders(db)
        open_orders = db.query(Order).filter(Order.status.in_(ACTIVE_ORDER_STATUSES)).count()
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        orders_today = db.query(Order).filter(Order.created_at >= today_start).count()
        revenue_today = sum(
            o.total for o in db.query(Order)
            .filter(Order.created_at >= today_start, Order.status.in_(("paid", "out_for_delivery", "delivered")))
            .all()
        )
        recent_orders = db.query(Order).order_by(Order.created_at.desc()).limit(10).all()
        conversations = db.query(Conversation).order_by(Conversation.updated_at.desc()).limit(8).all()

        action_queue_html = render_action_queue(action_orders, business_names)
        orders_rows = "".join(
            render_order_row(order, show_business_name=True, business_name=business_names.get(order.business_id, ""))
            for order in recent_orders
        )
        orders_table = (
            f"<div class='table-wrap'><table><tr><th>Business</th><th>Order</th><th>Customer</th><th>Address</th><th>Total</th><th>Age</th><th>Status</th></tr>{orders_rows}</table></div>"
            if recent_orders else "<p class='form-hint'>No orders yet.</p>"
        )
        conversation_rows = "".join(
            f"<tr><td>{escape(business_names.get(conversation.business_id, 'Unknown'))}</td>"
            f"<td><a href='/conversations/{conversation.id}'>{escape(conversation.phone_number)}</a></td>"
            f"<td>{escape(CONV_STAGE_LABELS.get(conversation.stage, conversation.stage))}</td>"
            f"<td>{format_age(conversation.updated_at)}</td></tr>"
            for conversation in conversations
        )
        conversations_table = (
            f"<div class='table-wrap'><table><tr><th>Business</th><th>Phone</th><th>Stage</th><th>Last active</th></tr>{conversation_rows}</table></div>"
            if conversations else "<p class='form-hint'>No conversations yet.</p>"
        )
        business_list = "".join(
            f"<li><a href='/admin/businesses/{business.id}'>{escape(business.name)}</a></li>" for business in businesses
        )
        action_stat_class = " alert" if action_orders else ""
        body = f"""
        <div class="hero-panel">
          <div>
            <div class="eyebrow">Control tower</div>
            <h1>Admin command center</h1>
            <p>Anything in the red queue below is blocking a customer right now — clear it first.</p>
          </div>
          <div class="actions">
            <a class="btn primary" href="/admin/orders">All orders</a>
            <a class="btn" href="/admin/conversations">Conversations</a>
          </div>
        </div>
        <div class="stats-grid">
          <div class="card stat-card metric{action_stat_class}">
            <span class="label">Needs action now</span>
            <span class="value">{len(action_orders)}</span>
          </div>
          <div class="card stat-card metric">
            <span class="label">Open orders</span>
            <span class="value">{open_orders}</span>
          </div>
          <div class="card stat-card metric">
            <span class="label">Orders today</span>
            <span class="value">{orders_today}</span>
          </div>
          <div class="card stat-card metric">
            <span class="label">Confirmed revenue today</span>
            <span class="value">₦{revenue_today}</span>
          </div>
          <div class="card stat-card metric">
            <span class="label">Businesses</span>
            <span class="value">{len(businesses)}</span>
          </div>
        </div>
        <div class="card">
          <div class="section-head">
            <h3>⚡ Needs your action</h3>
            <span class="status-pill">Customers are waiting on these</span>
          </div>
          {action_queue_html}
        </div>
        <div class="panel-grid">
          <div class="card">
            <div class="section-head">
              <h3>Recent orders</h3>
              <a class="btn" href="/admin/orders">View all</a>
            </div>
            {orders_table}
          </div>
          <div class="card">
            <div class="section-head">
              <h3>Live conversations</h3>
              <a class="btn" href="/admin/conversations">View all</a>
            </div>
            {conversations_table}
          </div>
        </div>
        <div class="card">
          <h3>Businesses</h3>
          <ul>{business_list}</ul>
        </div>
        """
    finally:
        db.close()
    return render_page("Admin Dashboard", body, nav_html=make_nav(current_user))


@app.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request) -> HTMLResponse:
    current_user = get_current_user(request)
    if not current_user or current_user.role != "admin":
        return RedirectResponse(url="/login", status_code=303)
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
        reset_2fa_html = (
            "<label><input type='checkbox' name='reset_2fa' /> Reset two-factor authentication (user has 2FA enabled — use this if they lost their device)</label>"
            if user.totp_enabled else "<p class='form-hint'>2FA: not enabled by this user.</p>"
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
            {reset_2fa_html}
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
def update_user(
    request: Request,
    user_id: int,
    role: str = Form(...),
    business_id: Optional[int] = Form(default=None),
    reset_2fa: Optional[str] = Form(default=None),
) -> RedirectResponse:
    current_user = get_current_user(request)
    if not current_user or current_user.role != "admin":
        return RedirectResponse(url="/login", status_code=303)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).one_or_none()
        if user:
            user.role = role
            user.business_id = business_id or None
            if reset_2fa:
                user.totp_enabled = 0
                user.totp_secret = None
            db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/admin/users", status_code=303)


@app.get("/admin/businesses", response_class=HTMLResponse)
def admin_businesses(request: Request) -> HTMLResponse:
    current_user = get_current_user(request)
    if not current_user or current_user.role != "admin":
        return RedirectResponse(url="/login", status_code=303)
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
            <label>How will customers pay?
              <select name="payment_method">
                <option value="bank_transfer">Bank transfer — owner confirms payments manually</option>
                <option value="paystack">Paystack payment link — confirmed automatically</option>
              </select>
            </label>
            <p class="form-hint">Add the matching details (bank account or Paystack secret key) on the business page after creating it.</p>
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
    payment_method: str = Form(default="bank_transfer"),
) -> RedirectResponse:
    current_user = get_current_user(request)
    if not current_user or current_user.role != "admin":
        return RedirectResponse(url="/login", status_code=303)
    if payment_method not in PAYMENT_METHOD_LABELS:
        payment_method = "bank_transfer"
    db = SessionLocal()
    try:
        if db.query(Business).filter(Business.whatsapp_number == whatsapp_number).first():
            return RedirectResponse(url="/admin/businesses", status_code=303)
        business = Business(name=name, whatsapp_number=whatsapp_number, owner_notify_number=owner_notify_number or None, payment_method=payment_method)
        db.add(business)
        db.commit()
        db.refresh(business)
    finally:
        db.close()
    return RedirectResponse(url=f"/admin/businesses/{business.id}", status_code=303)


NOTICE_MESSAGES = {
    "branch_limit": "⚠️ Your current plan includes a single branch. Upgrade to a multi-branch plan to add more locations.",
}


@app.get("/admin/businesses/{business_id}", response_class=HTMLResponse)
def business_detail(request: Request, business_id: int, notice: Optional[str] = None) -> HTMLResponse:
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
    notice_html = (
        f"<div class='notice-banner'>{escape(NOTICE_MESSAGES[notice])}</div>"
        if notice in NOTICE_MESSAGES else ""
    )
    method = business.payment_method or "bank_transfer"
    key_mode = paystack_key_mode(business.paystack_secret_key)
    key_badges = {
        "live": "<span class='status-pill'>✅ Live Paystack key saved</span>",
        "test": "<span class='status-pill' style='background:rgba(255,196,0,.12);border-color:rgba(255,196,0,.35);color:#ffd866;'>⚠️ TEST key saved — real customers can't pay with this</span>",
        "unknown": "<span class='status-pill' style='background:rgba(255,94,122,.12);border-color:rgba(255,94,122,.3);color:var(--danger);'>⚠️ Key doesn't look like sk_test_… / sk_live_…</span>",
        "missing": "",
    }
    key_badge = key_badges.get(key_mode, "")
    if business.delivery_autocalc:
        if business.geo_lat is not None and business.geo_lng is not None:
            geo_hint = f"📍 Pickup point located ({business.geo_lat:.4f}, {business.geo_lng:.4f})."
        else:
            geo_hint = "⚠️ Pickup address not located on the map yet — auto-pricing is off until it is."
    else:
        geo_hint = ""
    body = f"""
    {notice_html}
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
            <label>Opens at <input name="open_time" type="time" value="{escape(business.open_time or '')}" /></label>
            <label>Closes at <input name="close_time" type="time" value="{escape(business.close_time or '')}" /></label>
            <p class="form-hint">Leave both times empty to take orders 24/7. Outside these hours the bot politely tells customers you're closed (status checks and pending payments still work). Overnight windows like 18:00–02:00 are supported. Times are in your local time (WAT).</p>
            <hr style="border:none;border-top:1px solid var(--border);margin:14px 0;" />
            <label>How do customers pay?
              <select name="payment_method">
                <option value="bank_transfer" {"selected" if method == "bank_transfer" else ""}>Bank transfer — you confirm each payment manually</option>
                <option value="paystack" {"selected" if method == "paystack" else ""}>Paystack payment link — confirmed automatically</option>
              </select>
            </label>
            <input name="paystack_secret_key" type="password" value="{escape(business.paystack_secret_key or '')}" placeholder="Paystack secret key (sk_live_… — required for payment links)" autocomplete="off" />
            {key_badge}
            <p class="form-hint">With Paystack, customers get a secure checkout link (card, transfer, USSD) and payment is confirmed automatically — no bank-alert checking. Use the secret key from <em>your own</em> Paystack dashboard: an sk_live_ key takes real payments; an sk_test_ key only works with test cards.</p>
            <hr style="border:none;border-top:1px solid var(--border);margin:14px 0;" />
            <label><input type="checkbox" name="delivery_autocalc" {"checked" if business.delivery_autocalc else ""} /> Auto-calculate delivery fees by distance</label>
            <textarea name="location_address" placeholder="Pickup address — where deliveries leave from (defaults to your first branch's address)">{escape(business.location_address or '')}</textarea>
            <input name="delivery_base_fee" type="number" min="0" value="{business.delivery_base_fee or 0}" placeholder="Base delivery fee (₦)" />
            <input name="delivery_per_km" type="number" min="0" value="{business.delivery_per_km or 0}" placeholder="Additional fee per km (₦)" />
            <p class="form-hint">Fee = base + per-km × distance, rounded to the nearest ₦50 — like dispatch apps price rides (e.g. ₦1,000 base + ₦200/km). {geo_hint} If a customer's address can't be found on the map, the order falls back to you setting the fee manually, with a note on the alert.</p>
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
    billing_cycle: str = Form(default="monthly"),
) -> RedirectResponse:
    current_user = get_current_user(request)
    if not current_user or (current_user.role != "admin" and current_user.business_id != business_id):
        return RedirectResponse(url="/login", status_code=303)

    if billing_cycle not in {"monthly", "annual"}:
        billing_cycle = "monthly"
    db = SessionLocal()
    try:
        business = get_business(db, business_id)
        plan = get_plan(db, plan_id)
        if not business or not plan:
            return RedirectResponse(url=f"/admin/businesses/{business_id}", status_code=303)
        auto_renew_flag = auto_renew == "1"
        # Capture scalars before commit/close: commit expires ORM instances and
        # attribute access after close raises DetachedInstanceError.
        amount = plan.price_ngn * (ANNUAL_MONTHS_CHARGED if billing_cycle == "annual" else 1)
        reference = build_paystack_reference(business.id, plan.id)
        upsert_payment(db, business_id, current_user.email, plan_id, amount, reference, auto_renew_flag, billing_cycle)
    finally:
        db.close()

    auth_url = get_paystack_redirect(business_id, plan_id, amount, auto_renew_flag, current_user)
    return RedirectResponse(url=auth_url, status_code=303)


@app.get("/paystack/simulate", response_class=HTMLResponse)
def paystack_simulate(
    business_id: int,
    plan_id: int,
    amount: int,
    auto_renew: int = 0,
    reference: str = "",
    request: Request = None,
) -> HTMLResponse:
    # Simulation is a dev fallback only: never available once Paystack is
    # configured, and only for a logged-in staff user — otherwise anyone who
    # guesses a reference could activate a paid plan for free.
    current_user = get_current_user(request) if request else None
    if os.getenv("PAYSTACK_SECRET_KEY") or not current_user or current_user.role not in {"admin", "business_owner", "business-owner", "owner"}:
        return RedirectResponse(url="/login", status_code=303)
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
    open_time: str = Form(default=""),
    close_time: str = Form(default=""),
    payment_method: str = Form(default="bank_transfer"),
    paystack_secret_key: str = Form(default=""),
    delivery_autocalc: Optional[str] = Form(default=None),
    location_address: str = Form(default=""),
    delivery_base_fee: int = Form(default=0),
    delivery_per_km: int = Form(default=0),
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
            # Hours only stick when both parse as HH:MM; anything else means 24/7.
            if parse_hhmm(open_time) and parse_hhmm(close_time):
                business.open_time = open_time.strip()
                business.close_time = close_time.strip()
            else:
                business.open_time = None
                business.close_time = None
            if payment_method in PAYMENT_METHOD_LABELS:
                business.payment_method = payment_method
            business.paystack_secret_key = paystack_secret_key.strip() or None
            business.delivery_autocalc = 1 if delivery_autocalc else 0
            business.delivery_base_fee = max(0, delivery_base_fee)
            business.delivery_per_km = max(0, delivery_per_km)
            new_location = location_address.strip() or None
            if not new_location and business.delivery_autocalc:
                # Fall back to the first branch's address as the pickup point.
                branch = db.query(Branch).filter(Branch.business_id == business_id).order_by(Branch.id).first()
                if branch and branch.address:
                    new_location = branch.address.strip()
            if new_location != (business.location_address or None) or (new_location and business.geo_lat is None):
                business.location_address = new_location
                coords = geocode_address(new_location) if new_location else None
                business.geo_lat = coords[0] if coords else None
                business.geo_lng = coords[1] if coords else None
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
        business = get_business(db, business_id)
        if not business:
            return RedirectResponse(url="/admin/businesses", status_code=303)
        # Plan gating: single-branch plans (and trial) get one branch. Admins may override.
        if current_user.role != "admin":
            plan = get_plan(db, business.plan_id) if business.plan_id else None
            multi_branch = bool(plan and plan.branch_access == 1)
            existing = db.query(Branch).filter(Branch.business_id == business_id).count()
            if not multi_branch and existing >= 1:
                return RedirectResponse(url=f"/admin/businesses/{business_id}?notice=branch_limit", status_code=303)
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
    is_pending = order.status not in {"delivered", "cancelled"}
    is_stale = is_pending and order.created_at and (datetime.utcnow() - order.created_at) > timedelta(hours=2)
    age_style = "color:var(--danger);font-weight:700;" if is_stale else "color:var(--muted);"
    age_cell = f"<td style='{age_style}'>{format_age(order.created_at)}</td>"
    status_pill_style = "background:rgba(255,94,122,.12);border-color:rgba(255,94,122,.3);color:var(--danger);" if is_stale else ""
    status_label = ORDER_STATUS_LABELS.get(order.status, order.status)
    status_cell = f"<span class='status-pill' style='{status_pill_style}'>{escape(status_label)}</span>"
    customer_cell = escape(order.customer_name) if order.customer_name else escape(order.customer_phone)
    return (
        f"<tr>{business_cell}<td><a href='/orders/{order.id}'>#{order.id}</a></td><td>{customer_cell}</td><td>{escape(order.address)}</td>"
        f"<td>₦{order.total}</td>{age_cell}<td>{status_cell}</td></tr>"
    )


def render_action_queue(orders: List[Order], business_names: Optional[Dict[int, str]] = None) -> str:
    if not orders:
        return "<div class='empty-state'>✅ All clear — nothing needs your attention right now.</div>"
    rows = []
    for order in orders:
        waiting_since = order.status_changed_at or order.created_at
        business_cell = (
            f"<span class='queue-biz'>{escape(business_names.get(order.business_id, ''))}</span>"
            if business_names else ""
        )
        action = ACTION_LABELS.get(order.status, "Review")
        rows.append(
            f"<a class='queue-item' href='/orders/{order.id}'>"
            f"<div class='queue-main'><span class='queue-id'>#{order.id}</span>"
            f"<span class='queue-customer'>{escape(order.customer_name or order.customer_phone)}</span>{business_cell}</div>"
            f"<div class='queue-meta'><span class='queue-total'>₦{order.total}</span>"
            f"<span class='queue-status'>{escape(ORDER_STATUS_LABELS.get(order.status, order.status))}</span>"
            f"<span class='queue-age'>waiting {format_age(waiting_since)}</span></div>"
            f"<span class='btn primary queue-cta'>{escape(action)}</span></a>"
        )
    return f"<div class='queue-list'>{''.join(rows)}</div>"


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
        set_order_status(order, "awaiting_payment")
        if business and business.payment_method == "paystack":
            create_paystack_order_link(business, order)
        # If the customer's chat drifted back to idle/menu (e.g. they said "hi"
        # while waiting), snap it to the payment stage so their next reply —
        # even a bare "ok" — is treated as payment confirmation, not menu input.
        conversation = (
            db.query(Conversation)
            .filter(Conversation.phone_number == order.customer_phone, Conversation.business_id == order.business_id)
            .one_or_none()
        )
        if conversation and conversation.stage in (CONV_NEW, CONV_CATEGORY):
            conversation.stage = CONV_AWAITING_PAYMENT
        db.commit()

        send_whatsapp_message(
            order.customer_phone,
            format_payment_request(order, business) + COLLXCT_FOOTER,
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
        set_order_status(order, "paid")
        db.commit()
        business = get_business(db, order.business_id)
        send_whatsapp_message(
            order.customer_phone,
            f"🎉 Payment confirmed for order *#{order.id}*! *{business.name if business else 'The business'}* is preparing your order now.{COLLXCT_FOOTER}",
            from_number=business.whatsapp_number if business else None,
        )
        business_id = order.business_id
    finally:
        db.close()
    if current_user.role == "admin":
        return RedirectResponse(url="/admin/orders", status_code=303)
    return RedirectResponse(url=f"/business/{business_id}/dashboard", status_code=303)


@app.post("/orders/{order_id}/dispatch")
def dispatch_order(request: Request, order_id: int) -> RedirectResponse:
    current_user = get_current_user(request)
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == order_id).one_or_none()
        if not order:
            return RedirectResponse(url="/admin/orders", status_code=303)
        if not current_user or (current_user.role != "admin" and current_user.business_id != order.business_id):
            return RedirectResponse(url="/login", status_code=303)
        set_order_status(order, "out_for_delivery")
        db.commit()
        business = get_business(db, order.business_id)
        send_whatsapp_message(
            order.customer_phone,
            f"🚴 Your order *#{order.id}* is on its way!",
            from_number=business.whatsapp_number if business else None,
        )
        business_id = order.business_id
    finally:
        db.close()
    if current_user.role == "admin":
        return RedirectResponse(url="/admin/orders", status_code=303)
    return RedirectResponse(url=f"/business/{business_id}/dashboard", status_code=303)


@app.post("/orders/{order_id}/mark-delivered")
def mark_order_delivered(request: Request, order_id: int) -> RedirectResponse:
    current_user = get_current_user(request)
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == order_id).one_or_none()
        if not order:
            return RedirectResponse(url="/admin/orders", status_code=303)
        if not current_user or (current_user.role != "admin" and current_user.business_id != order.business_id):
            return RedirectResponse(url="/login", status_code=303)
        set_order_status(order, "delivered")
        db.commit()
        business = get_business(db, order.business_id)
        send_whatsapp_message(
            order.customer_phone,
            f"✅ Order *#{order.id}* delivered. Thanks for ordering from *{business.name if business else 'us'}*!{COLLXCT_FOOTER}",
            from_number=business.whatsapp_number if business else None,
        )
        business_id = order.business_id
    finally:
        db.close()
    if current_user.role == "admin":
        return RedirectResponse(url="/admin/orders", status_code=303)
    return RedirectResponse(url=f"/business/{business_id}/dashboard", status_code=303)


@app.post("/orders/{order_id}/verify-payment")
def verify_order_payment(request: Request, order_id: int) -> RedirectResponse:
    current_user = get_current_user(request)
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == order_id).one_or_none()
        if not order:
            return RedirectResponse(url="/admin/orders", status_code=303)
        if not current_user or (current_user.role != "admin" and current_user.business_id != order.business_id):
            return RedirectResponse(url="/login", status_code=303)
        business = get_business(db, order.business_id)
        if business and order.status in {"awaiting_payment", "payment_claimed"} and verify_paystack_order_payment(business, order):
            set_order_status(order, "paid")
            db.commit()
            send_whatsapp_message(
                order.customer_phone,
                f"🎉 Payment confirmed for order *#{order.id}*! *{business.name}* is preparing your order now.{COLLXCT_FOOTER}",
                from_number=business.whatsapp_number,
            )
    finally:
        db.close()
    return RedirectResponse(url=f"/orders/{order_id}", status_code=303)


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


ORDER_STATUS_LABELS = {
    "awaiting_delivery_fee": "Awaiting delivery fee",
    "awaiting_payment": "Awaiting customer payment",
    "payment_claimed": "Payment claimed — needs review",
    "paid": "Paid — ready to dispatch",
    "out_for_delivery": "Out for delivery",
    "delivered": "Delivered",
    "cancelled": "Cancelled",
}


@app.get("/api/action-required")
def api_action_required(request: Request) -> JSONResponse:
    current_user = get_current_user(request)
    if not current_user or current_user.role not in STAFF_ROLES:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    db = SessionLocal()
    try:
        if current_user.role == "admin":
            orders = action_needed_orders(db)
        elif current_user.business_id:
            orders = action_needed_orders(db, current_user.business_id)
        else:
            orders = []
        business_names = {b.id: b.name for b in db.query(Business).all()} if orders else {}
        items = []
        for order in orders:
            waiting_since = order.status_changed_at or order.created_at
            items.append({
                "id": order.id,
                "business": business_names.get(order.business_id, ""),
                "customer": order.customer_name or order.customer_phone,
                "total": order.total,
                "status": order.status,
                "label": ORDER_STATUS_LABELS.get(order.status, order.status),
                "action": ACTION_LABELS.get(order.status, "Review"),
                "age": format_age(waiting_since),
                "url": f"/orders/{order.id}",
            })
    finally:
        db.close()
    return JSONResponse({"count": len(items), "orders": items})


@app.get("/orders/{order_id}", response_class=HTMLResponse)
def order_detail(request: Request, order_id: int) -> HTMLResponse:
    current_user = get_current_user(request)
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == order_id).one_or_none()
        if not order:
            return render_page("Order Not Found", "<p>Order not found.</p>", nav_html=make_nav(current_user))
        if not current_user or (current_user.role != "admin" and current_user.business_id != order.business_id):
            return RedirectResponse(url="/login", status_code=303)
        business = get_business(db, order.business_id)
    finally:
        db.close()

    items = load_cart(order.items_json)
    items_rows = "".join(
        f"<tr><td>{escape(str(entry.get('name', 'Item')))}</td><td>{entry.get('qty', 1)}</td>"
        f"<td>N{entry.get('price', 0)}</td><td>N{int(entry.get('price', 0)) * int(entry.get('qty', 1))}</td></tr>"
        for entry in items
    )
    subtotal = cart_total(items)
    status_label = ORDER_STATUS_LABELS.get(order.status, order.status)

    proof_html = ""
    if business and business.payment_method == "paystack":
        proof_html += f"<p><span class='pill'>💳 Paystack ({escape(paystack_key_mode(business.paystack_secret_key))} mode)</span></p>"
        if order.payment_link:
            proof_html += f"<p><strong>Payment link:</strong> <a href='{escape(order.payment_link)}' target='_blank'>{escape(order.payment_link)}</a></p>"
        if order.payment_reference:
            proof_html += f"<p><strong>Gateway reference:</strong> {escape(order.payment_reference)}</p>"
    if order.payment_proof_text:
        proof_html += f"<p><strong>Customer note:</strong> {escape(order.payment_proof_text)}</p>"
    if order.payment_receipt_path:
        proof_html += f"<a href='/orders/{order.id}/receipt' target='_blank'><img class='receipt-preview' src='/orders/{order.id}/receipt' alt='Payment receipt' /></a>"
    if not proof_html:
        proof_html = "<p class='form-hint'>No payment proof submitted yet.</p>"

    verify_button = ""
    if business and business.payment_method == "paystack" and order.payment_reference and order.status in {"awaiting_payment", "payment_claimed"}:
        verify_button = (
            f"<form method='post' action='/orders/{order.id}/verify-payment' style='margin:0;'>"
            f"<button type='submit'>Check Paystack status</button></form>"
        )

    action_button = ""
    action_modal = ""
    if order.status == "awaiting_delivery_fee":
        action_button = "<button type='button' class='btn primary' onclick=\"document.getElementById('delivery-fee-modal').showModal()\">Set delivery fee</button>"
        action_modal = f"""
        <dialog id="delivery-fee-modal" class="modal">
          <div class="modal-body">
            <h3>Set delivery fee</h3>
            <p class="form-hint">Subtotal is N{subtotal}. Enter the delivery fee to send the customer their full total and your bank details.</p>
            <form method="post" action="/orders/{order.id}/delivery-fee">
              <input name="delivery_fee" type="number" min="0" placeholder="Delivery fee" required autofocus />
              <div class="modal-actions">
                <button type="submit" class="btn primary">Send total to customer</button>
                <button type="button" class="btn secondary" onclick="document.getElementById('delivery-fee-modal').close()">Cancel</button>
              </div>
            </form>
          </div>
        </dialog>
        """
    elif order.status in {"awaiting_payment", "payment_claimed"}:
        action_button = "<button type='button' class='btn primary' onclick=\"document.getElementById('mark-paid-modal').showModal()\">Mark paid</button>"
        action_modal = f"""
        <dialog id="mark-paid-modal" class="modal">
          <div class="modal-body">
            <h3>Mark order #{order.id} as paid?</h3>
            <p class="form-hint">Total: N{order.total}. Only confirm after checking your own bank alert for this exact amount.</p>
            <form method="post" action="/orders/{order.id}/mark-paid">
              <div class="modal-actions">
                <button type="submit" class="btn primary">Yes, mark as paid</button>
                <button type="button" class="btn secondary" onclick="document.getElementById('mark-paid-modal').close()">Cancel</button>
              </div>
            </form>
          </div>
        </dialog>
        """
    elif order.status == "paid":
        action_button = "<button type='button' class='btn primary' onclick=\"document.getElementById('dispatch-modal').showModal()\">Mark out for delivery</button>"
        action_modal = f"""
        <dialog id="dispatch-modal" class="modal">
          <div class="modal-body">
            <h3>Send order #{order.id} out for delivery?</h3>
            <p class="form-hint">This lets the customer know their order is on its way.</p>
            <form method="post" action="/orders/{order.id}/dispatch">
              <div class="modal-actions">
                <button type="submit" class="btn primary">Yes, it's on its way</button>
                <button type="button" class="btn secondary" onclick="document.getElementById('dispatch-modal').close()">Cancel</button>
              </div>
            </form>
          </div>
        </dialog>
        """
    elif order.status == "out_for_delivery":
        action_button = "<button type='button' class='btn primary' onclick=\"document.getElementById('delivered-modal').showModal()\">Mark delivered</button>"
        action_modal = f"""
        <dialog id="delivered-modal" class="modal">
          <div class="modal-body">
            <h3>Mark order #{order.id} as delivered?</h3>
            <p class="form-hint">This completes the order and thanks the customer.</p>
            <form method="post" action="/orders/{order.id}/mark-delivered">
              <div class="modal-actions">
                <button type="submit" class="btn primary">Yes, it's delivered</button>
                <button type="button" class="btn secondary" onclick="document.getElementById('delivered-modal').close()">Cancel</button>
              </div>
            </form>
          </div>
        </dialog>
        """

    body = f"""
    <div class="hero-panel">
      <div>
        <div class="eyebrow">Order #{order.id}</div>
        <h1>{escape(order.customer_name) if order.customer_name else escape(business.name) if business else 'Unknown business'}</h1>
        <p>{escape(order.customer_phone)} &middot; placed {format_age(order.created_at)}</p>
      </div>
      <div class="actions">
        <span class="status-pill">{escape(status_label)}</span>
        {verify_button}
        {action_button}
      </div>
    </div>
    <div class="detail-grid">
      <div class="card">
        <h3>Items</h3>
        <div class="table-wrap"><table><tr><th>Item</th><th>Qty</th><th>Price</th><th>Line total</th></tr>{items_rows}</table></div>
      </div>
      <div class="card">
        <h3>Summary</h3>
        <div class="kv-list">
          <div class="kv-row"><span class="kv-label">Business</span><span class="kv-value">{escape(business.name) if business else 'Unknown'}</span></div>
          <div class="kv-row"><span class="kv-label">Customer</span><span class="kv-value">{escape(order.customer_name) if order.customer_name else '—'}</span></div>
          <div class="kv-row"><span class="kv-label">Subtotal</span><span class="kv-value">N{subtotal}</span></div>
          <div class="kv-row"><span class="kv-label">Delivery fee</span><span class="kv-value">N{order.delivery_fee}</span></div>
          <div class="kv-row"><span class="kv-label">Total</span><span class="kv-value">N{order.total}</span></div>
          <div class="kv-row"><span class="kv-label">Delivery address</span><span class="kv-value">{escape(order.address)}{" ⚠️ <em>not found on map</em>" if order.address_unverified else ""}</span></div>
        </div>
      </div>
    </div>
    <div class="card">
      <h3>Payment</h3>
      {proof_html}
    </div>
    {action_modal}
    """
    return render_page(f"Order #{order.id}", body, nav_html=make_nav(current_user))


@app.get("/admin/orders", response_class=HTMLResponse)
def admin_orders(request: Request) -> HTMLResponse:
    current_user = get_current_user(request)
    if not current_user or current_user.role != "admin":
        return RedirectResponse(url="/login", status_code=303)
    db = SessionLocal()
    try:
        orders = db.query(Order).order_by(Order.created_at.desc()).limit(200).all()
        business_names = {b.id: b.name for b in db.query(Business).all()}
        rows = "".join(render_order_row(order, show_business_name=True, business_name=business_names.get(order.business_id, "")) for order in orders)
    finally:
        db.close()
    body = f"<div class=\"card\"><div class=\"table-wrap\"><table><tr><th>Business</th><th>Order</th><th>Customer</th><th>Address</th><th>Total</th><th>Age</th><th>Status</th></tr>{rows}</table></div></div>"
    return render_page("Orders", body, nav_html=make_nav(current_user))


CONV_STAGE_LABELS = {
    CONV_NEW: "New / idle",
    CONV_CATEGORY: "Choosing category",
    CONV_ITEM: "Browsing items",
    CONV_NAME: "Entering name",
    CONV_ADDRESS: "Entering address",
    CONV_AWAITING_PAYMENT: "Awaiting payment",
}


@app.get("/admin/conversations", response_class=HTMLResponse)
def admin_conversations(request: Request) -> HTMLResponse:
    current_user = get_current_user(request)
    if not current_user or current_user.role != "admin":
        return RedirectResponse(url="/login", status_code=303)
    db = SessionLocal()
    try:
        conversations = db.query(Conversation).order_by(Conversation.updated_at.desc()).limit(200).all()
        business_names = {b.id: b.name for b in db.query(Business).all()}
        rows = "".join(
            f"<tr><td>{escape(business_names.get(conversation.business_id, 'Unknown'))}</td>"
            f"<td><a href='/conversations/{conversation.id}'>{escape(conversation.phone_number)}</a></td>"
            f"<td>{escape(CONV_STAGE_LABELS.get(conversation.stage, conversation.stage))}</td>"
            f"<td>{escape(format_cart_summary(conversation.cart_json) or (conversation.address or ''))}</td>"
            f"<td>{format_age(conversation.updated_at)}</td></tr>"
            for conversation in conversations
        )
    finally:
        db.close()
    body = f"<div class=\"card\"><div class=\"table-wrap\"><table><tr><th>Business</th><th>Phone</th><th>Stage</th><th>Cart / Address</th><th>Last active</th></tr>{rows}</table></div></div>"
    return render_page("Conversations", body, nav_html=make_nav(current_user))


@app.get("/conversations/{conversation_id}", response_class=HTMLResponse)
def conversation_detail(request: Request, conversation_id: int) -> HTMLResponse:
    current_user = get_current_user(request)
    db = SessionLocal()
    try:
        conversation = db.query(Conversation).filter(Conversation.id == conversation_id).one_or_none()
        if not conversation:
            return render_page("Conversation Not Found", "<p>Conversation not found.</p>", nav_html=make_nav(current_user))
        if not current_user or (current_user.role != "admin" and current_user.business_id != conversation.business_id):
            return RedirectResponse(url="/login", status_code=303)
        business = get_business(db, conversation.business_id)
        orders = (
            db.query(Order)
            .filter(Order.customer_phone == conversation.phone_number, Order.business_id == conversation.business_id)
            .order_by(Order.created_at.desc())
            .all()
        )
    finally:
        db.close()

    cart = load_cart(conversation.cart_json)
    cart_rows = "".join(
        f"<tr><td>{escape(str(entry.get('name', 'Item')))}</td><td>{entry.get('qty', 1)}</td><td>₦{entry.get('price', 0)}</td></tr>"
        for entry in cart
    )
    cart_html = (
        f"<div class='table-wrap'><table><tr><th>Item</th><th>Qty</th><th>Price</th></tr>{cart_rows}</table></div>"
        if cart else "<p class='form-hint'>Cart is empty.</p>"
    )

    orders_html = "".join(render_order_row(order) for order in orders)
    orders_section = (
        f"<div class='table-wrap'><table><tr><th>Order</th><th>Customer</th><th>Address</th><th>Total</th><th>Age</th><th>Status</th></tr>{orders_html}</table></div>"
        if orders else "<p class='form-hint'>No orders yet from this conversation.</p>"
    )

    stage_label = CONV_STAGE_LABELS.get(conversation.stage, conversation.stage)
    body = f"""
    <div class="hero-panel">
      <div>
        <div class="eyebrow">Conversation</div>
        <h1>{escape(conversation.phone_number)}</h1>
        <p>{escape(business.name) if business else 'Unknown business'} &middot; last active {format_age(conversation.updated_at)}</p>
      </div>
      <div class="actions">
        <span class="status-pill">{escape(stage_label)}</span>
      </div>
    </div>
    <div class="detail-grid">
      <div class="card">
        <h3>Current cart</h3>
        {cart_html}
      </div>
      <div class="card">
        <h3>Details</h3>
        <div class="kv-list">
          <div class="kv-row"><span class="kv-label">Stage</span><span class="kv-value">{escape(stage_label)}</span></div>
          <div class="kv-row"><span class="kv-label">Address on file</span><span class="kv-value">{escape(conversation.address or '—')}</span></div>
          <div class="kv-row"><span class="kv-label">Last active</span><span class="kv-value">{format_age(conversation.updated_at)}</span></div>
        </div>
      </div>
    </div>
    <div class="card">
      <h3>Orders from this customer</h3>
      {orders_section}
    </div>
    """
    return render_page(f"Conversation — {conversation.phone_number}", body, nav_html=make_nav(current_user))


@app.get("/business/{business_id}", response_class=HTMLResponse)
@app.get("/business/{business_id}/dashboard", response_class=HTMLResponse)
def business_dashboard(request: Request, business_id: int) -> HTMLResponse:
    current_user = get_current_user(request)
    if not current_user or (current_user.role != "admin" and current_user.business_id != business_id):
        return RedirectResponse(url="/login", status_code=303)
    db = SessionLocal()
    try:
        business = get_business(db, business_id)
        if not business:
            return render_page("Business Not Found", "<p>Business not found.</p>", nav_html=make_nav(current_user))
        action_orders = action_needed_orders(db, business_id)
        open_orders = (
            db.query(Order)
            .filter(Order.business_id == business_id, Order.status.in_(ACTIVE_ORDER_STATUSES))
            .count()
        )
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        orders_today = db.query(Order).filter(Order.business_id == business_id, Order.created_at >= today_start).count()
        revenue_today = sum(
            o.total for o in db.query(Order)
            .filter(
                Order.business_id == business_id,
                Order.created_at >= today_start,
                Order.status.in_(("paid", "out_for_delivery", "delivered")),
            )
            .all()
        )
        recent_orders = (
            db.query(Order)
            .filter(Order.business_id == business_id)
            .order_by(Order.created_at.desc())
            .limit(10)
            .all()
        )
        item_count = db.query(MenuItem).filter(MenuItem.business_id == business_id).count()

        action_queue_html = render_action_queue(action_orders)
        orders_rows = "".join(render_order_row(order) for order in recent_orders)
        orders_table = (
            f"<div class='table-wrap'><table><tr><th>Order</th><th>Customer</th><th>Address</th><th>Total</th><th>Age</th><th>Status</th></tr>{orders_rows}</table></div>"
            if recent_orders else "<p class='form-hint'>No orders yet — they'll appear here the moment a customer checks out on WhatsApp.</p>"
        )
        plan_banner = ""
        if business.plan_expiry:
            now = datetime.utcnow()
            plans_url = f"/business/{business.id}/plans"
            if plan_is_blocked(business):
                plan_banner = (
                    f"<div class='notice-banner danger'>🚫 Your plan expired on {business.plan_expiry.strftime('%b %d')} and WhatsApp ordering is paused. "
                    f"<a href='{plans_url}'>Renew now</a> to switch it back on.</div>"
                )
            elif business.plan_expiry < now:
                resume = (business.plan_expiry + timedelta(days=PLAN_GRACE_DAYS)).strftime("%b %d")
                plan_banner = (
                    f"<div class='notice-banner danger'>🚨 Your plan has expired — ordering pauses on {resume} unless you "
                    f"<a href='{plans_url}'>renew</a>.</div>"
                )
            elif business.plan_expiry - now <= timedelta(days=PLAN_GRACE_DAYS):
                plan_banner = (
                    f"<div class='notice-banner'>⚠️ Your plan expires on {business.plan_expiry.strftime('%b %d')}. "
                    f"<a href='{plans_url}'>Renew</a> to avoid any pause in ordering.</div>"
                )
        cap_banner = ""
        used, cap, cap_plan = monthly_order_usage(db, business)
        if cap and used >= max(1, int(cap * 0.8)):
            plans_url = f"/business/{business.id}/plans"
            if used > cap:
                cap_banner = (
                    f"<div class='notice-banner'>📈 {used}/{cap} monthly orders used — you're past your {escape(cap_plan.name)} plan's included allowance. "
                    f"Orders are <strong>not</strong> blocked, but please <a href='{plans_url}'>upgrade</a>.</div>"
                )
            else:
                cap_banner = (
                    f"<div class='notice-banner'>📈 {used}/{cap} monthly orders used on your {escape(cap_plan.name)} plan. "
                    f"<a href='{plans_url}'>Upgrade</a> if you're trending past it.</div>"
                )
        action_stat_class = " alert" if action_orders else ""
        if business.open_time and business.close_time:
            if business_is_open(business):
                hours_pill = f"<span class='status-pill'>🟢 Open now · {escape(business.open_time)}–{escape(business.close_time)}</span>"
            else:
                hours_pill = f"<span class='status-pill' style='background:rgba(255,94,122,.12);border-color:rgba(255,94,122,.3);color:var(--danger);'>🔴 Closed now · opens {escape(business.open_time)}</span>"
        else:
            hours_pill = "<span class='status-pill'>🟢 Open 24/7</span>"
        body = f"""
        {plan_banner}
        {cap_banner}
        <div class="hero-panel">
          <div>
            <div class="eyebrow">Owner workspace</div>
            <h1>{escape(business.name)} operations</h1>
            <p>Anything in the red queue below is blocking a customer right now — clear it first.</p>
          </div>
          <div class="actions">
            {hours_pill}
            <a class="btn primary" href="/business/{business.id}/config">Manage setup</a>
            <a class="btn" href="/business/{business.id}/plans">Plans</a>
          </div>
        </div>
        <div class="stats-grid">
          <div class="card stat-card metric{action_stat_class}">
            <span class="label">Needs action now</span>
            <span class="value">{len(action_orders)}</span>
          </div>
          <div class="card stat-card metric">
            <span class="label">Open orders</span>
            <span class="value">{open_orders}</span>
          </div>
          <div class="card stat-card metric">
            <span class="label">Orders today</span>
            <span class="value">{orders_today}</span>
          </div>
          <div class="card stat-card metric">
            <span class="label">Confirmed revenue today</span>
            <span class="value">₦{revenue_today}</span>
          </div>
          <div class="card stat-card metric">
            <span class="label">Menu items</span>
            <span class="value">{item_count}</span>
          </div>
        </div>
        <div class="card">
          <div class="section-head">
            <h3>⚡ Needs your action</h3>
            <span class="status-pill">Customers are waiting on these</span>
          </div>
          {action_queue_html}
        </div>
        <div class="card">
          <div class="section-head">
            <h3>Recent orders</h3>
          </div>
          {orders_table}
        </div>
        """
    finally:
        db.close()
    return render_page(f"{business.name} Dashboard", body, nav_html=make_nav(current_user))


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
        f"<div class=\"plan-card{' active' if active_plan and active_plan.id == plan.id else ''}\"><span class=\"tag\">{'Current' if active_plan and active_plan.id == plan.id else 'Recommended'}</span><h4>{escape(plan.name)}</h4><div class=\"price\">₦{plan.price_ngn}<span style=\"font-size:.85rem;font-weight:500;color:var(--muted);\">/mo</span></div><p class=\"form-hint\">or ₦{plan.price_ngn * ANNUAL_MONTHS_CHARGED}/year — 2 months free</p><p>{escape(plan.description or 'Premium tools for daily order and branch management.')}</p><p>{'Single branch access' if plan.branch_access == 0 else 'Unlimited branches'} · {f'{plan.monthly_order_cap} orders/mo included' if plan.monthly_order_cap else 'unlimited orders'}</p><label><input type=\"radio\" name=\"plan_id\" value=\"{plan.id}\" {'checked' if idx == 0 else ''} /> Select this plan</label></div>"
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
        <label><input type="radio" name="billing_cycle" value="monthly" checked /> Monthly billing</label>
        <label><input type="radio" name="billing_cycle" value="annual" /> Annual billing — pay for {ANNUAL_MONTHS_CHARGED} months, get 12 (2 months free)</label>
        <label><input type="checkbox" name="auto_renew" value="1" checked /> Auto renew</label>
        <button type="submit" class="btn primary">Checkout with Paystack</button>
      </div>
    </form>
    """
    return render_page(f"{business.name} Plans", body, nav_html=make_nav(current_user))


@app.get("/admin/messages", response_class=HTMLResponse)
def admin_messages(request: Request) -> HTMLResponse:
    current_user = get_current_user(request)
    if not current_user or current_user.role != "admin":
        return RedirectResponse(url="/login", status_code=303)
    db = SessionLocal()
    try:
        messages = db.query(ContactMessage).order_by(ContactMessage.created_at.desc()).limit(200).all()
        rows = "".join(
            f"<tr><td>{escape(m.name)}</td><td>{escape(m.business_name or '—')}</td>"
            f"<td>{escape(m.phone or '—')}</td><td>{escape(m.email or '—')}</td>"
            f"<td>{escape(m.message[:200])}{'…' if len(m.message) > 200 else ''}</td>"
            f"<td>{'✅' if m.emailed else '📥'}</td><td>{format_age(m.created_at)}</td></tr>"
            for m in messages
        )
    finally:
        db.close()
    table = (
        f"<div class='table-wrap'><table><tr><th>Name</th><th>Business</th><th>Phone</th><th>Email</th><th>Message</th><th>Emailed</th><th>When</th></tr>{rows}</table></div>"
        if rows else "<div class='empty-state'>No contact messages yet — they'll appear here when someone uses the website form.</div>"
    )
    body = f"""
    <div class="card">
      <div class="section-head">
        <h3>Website leads</h3>
        <span class="status-pill">✅ = also emailed to {escape(CONTACT_EMAIL)}</span>
      </div>
      {table}
    </div>
    """
    return render_page("Leads", body, nav_html=make_nav(current_user))


@app.get("/admin/plans", response_class=HTMLResponse)
def admin_plans(request: Request) -> HTMLResponse:
    current_user = get_current_user(request)
    if not current_user or current_user.role != "admin":
        return RedirectResponse(url="/login", status_code=303)
    db = SessionLocal()
    try:
        plans = db.query(Plan).order_by(Plan.price_ngn).all()
        counts = {
            plan.id: db.query(Business).filter(Business.plan_id == plan.id).count()
            for plan in plans
        }
        plan_cards = "".join(
            f"""
            <div class="card">
              <div class="section-head">
                <h3>{escape(plan.name)}</h3>
                <span class="status-pill">{counts.get(plan.id, 0)} business(es) on this plan</span>
              </div>
              <form method="post" action="/admin/plans/{plan.id}">
                <label>Name <input name="name" value="{escape(plan.name)}" required /></label>
                <label>Monthly price (₦) <input name="price_ngn" type="number" min="0" value="{plan.price_ngn}" required /></label>
                <label>Included orders/month (0 = unlimited) <input name="monthly_order_cap" type="number" min="0" value="{plan.monthly_order_cap}" /></label>
                <textarea name="description" placeholder="What's included?">{escape(plan.description or '')}</textarea>
                <label><input type="checkbox" name="branch_access" {"checked" if plan.branch_access == 1 else ""} /> Multi-branch access</label>
                <p class="form-hint">Annual price is automatic: {ANNUAL_MONTHS_CHARGED}× the monthly price for 12 months. The order cap is soft — owners get nudged at 80% and past the cap, but orders are never blocked.</p>
                <div class="form-actions">
                  <button type="submit">Save plan</button>
                </div>
              </form>
            </div>
            """
            for plan in plans
        )
    finally:
        db.close()
    body = f"""
    <div class="hero-panel">
      <div>
        <div class="eyebrow">Pricing control</div>
        <h1>Subscription plans</h1>
        <p>Changes apply to new checkouts immediately. Existing subscriptions keep the price they already paid until renewal.</p>
      </div>
    </div>
    <div class="panel-grid">
      {plan_cards}
    </div>
    """
    return render_page("Plans & Pricing", body, nav_html=make_nav(current_user))


@app.post("/admin/plans/{plan_id}")
def update_plan(
    request: Request,
    plan_id: int,
    name: str = Form(...),
    price_ngn: int = Form(...),
    description: str = Form(default=""),
    branch_access: Optional[str] = Form(default=None),
    monthly_order_cap: int = Form(default=0),
) -> RedirectResponse:
    current_user = get_current_user(request)
    if not current_user or current_user.role != "admin":
        return RedirectResponse(url="/login", status_code=303)
    db = SessionLocal()
    try:
        plan = get_plan(db, plan_id)
        if plan:
            plan.name = name
            plan.price_ngn = max(0, price_ngn)
            plan.description = description or None
            plan.branch_access = 1 if branch_access else 0
            plan.monthly_order_cap = max(0, monthly_order_cap)
            db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/admin/plans", status_code=303)


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
        f"<div class=\"plan-card{' active' if active_plan and active_plan.id == plan.id else ''}\"><span class=\"tag\">{'Current' if active_plan and active_plan.id == plan.id else 'Recommended'}</span><h4>{escape(plan.name)}</h4><div class=\"price\">₦{plan.price_ngn}<span style=\"font-size:.85rem;font-weight:500;color:var(--muted);\">/mo</span></div><p class=\"form-hint\">or ₦{plan.price_ngn * ANNUAL_MONTHS_CHARGED}/year — 2 months free</p><p>{escape(plan.description or 'Premium tools for daily order and branch management.')}</p><p>{'Single branch access' if plan.branch_access == 0 else 'Unlimited branches'} · {f'{plan.monthly_order_cap} orders/mo included' if plan.monthly_order_cap else 'unlimited orders'}</p><label><input type=\"radio\" name=\"plan_id\" value=\"{plan.id}\" {'checked' if idx == 0 else ''} /> Select this plan</label></div>"
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
        <label><input type="radio" name="billing_cycle" value="monthly" checked /> Monthly billing</label>
        <label><input type="radio" name="billing_cycle" value="annual" /> Annual billing — pay for {ANNUAL_MONTHS_CHARGED} months, get 12 (2 months free)</label>
        <label><input type="checkbox" name="auto_renew" value="1" checked /> Auto renew</label>
        <button type="submit" class="btn primary">Checkout with Paystack</button>
      </div>
    </form>
    """
    return render_page(f"{business.name} Plan Settings", body, nav_html=make_nav(current_user))


@app.get("/business/{business_id}/config", response_class=HTMLResponse)
def business_config(request: Request, business_id: int) -> HTMLResponse:
    return business_detail(request, business_id)
