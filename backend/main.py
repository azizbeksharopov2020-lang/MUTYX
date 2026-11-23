"""YUKNOVA API (FastAPI)

Muhim sozlamalar Render'dagi Environment bo'limida turadi (kodga yozilmaydi):
  DATABASE_URL  - bazaga ulanish manzili (Supabase "Session pooler" manzili)
  SECRET_KEY    - uzun tasodifiy qator (kirish tokenlarini imzolash uchun)
Ular berilmasa, server sinov rejimida ishlaydi: SQLite fayl va vaqtinchalik kalit.
Render'ning bepul tarifida SQLite fayl har deploy'da o'chadi, shuning uchun
haqiqiy foydalanish uchun DATABASE_URL shart.
"""

import hashlib
import logging
import hmac
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import jwt
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import Response
from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, Field, StringConstraints
from typing_extensions import Annotated
from openai import AsyncOpenAI

logger = logging.getLogger('mutx.ai')
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    create_engine,
    func,
    or_,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

# ----------------------------------------------------------------------------
# Sozlamalar
# ----------------------------------------------------------------------------

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./mutx.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

IS_SQLITE = DATABASE_URL.startswith("sqlite")

SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    if os.getenv("RENDER"):
        raise RuntimeError("Render Environment'da SECRET_KEY majburiy. Kamida 64 ta tasodifiy belgi kiriting.")
    SECRET_KEY = secrets.token_urlsafe(48)
if len(SECRET_KEY) < 32:
    raise RuntimeError("SECRET_KEY kamida 32 belgidan iborat bo'lishi kerak.")
TOKEN_DAYS = 1
JWT_ISSUER = "mutx-api"
JWT_AUDIENCE = "mutx-users"

FEE_PER_TONNA = 10000  # har bir tomon uchun so'm / tonna

# Frontend domenlari: Render Environment'da YUKNOVA_FRONTEND_ORIGINS orqali
# vergul bilan ajratib qo'shish mumkin (masalan https://yuknova.uz,https://www.yuknova.uz).
_default_origins = [
    "https://azizbeksharopov2020-lang.github.io",
    "http://127.0.0.1:5500",
    "http://localhost:5500",
]
_custom_origins = [
    origin.strip().rstrip("/")
    for origin in os.getenv("YUKNOVA_FRONTEND_ORIGINS", os.getenv("MUTX_FRONTEND_ORIGINS", "")).split(",")
    if origin.strip()
]
ALLOWED_ORIGINS = list(dict.fromkeys(_default_origins + _custom_origins))

PHONE_RE = re.compile(r"^\+998[0-9]{9}$")

ROLE_ALIASES = {
    "driver": "driver",
    "haydovchi": "driver",
    "owner": "owner",
    "yuk_egasi": "owner",
    "cargo_owner": "owner",
}

TRANSPORTS = {"Yuk mashinasi", "Gazel", "Fura / Tirkama", "Refrijerator", "Boshqa"}

DOCUMENT_ENCRYPTION_KEY = os.getenv("DOCUMENT_ENCRYPTION_KEY", "").strip()
document_cipher = Fernet(DOCUMENT_ENCRYPTION_KEY.encode()) if DOCUMENT_ENCRYPTION_KEY else None
MAX_ID_DOCUMENT_BYTES = 5 * 1024 * 1024

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if IS_SQLITE else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ----------------------------------------------------------------------------
# Jadvallar
# ----------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "mutx_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    roles: Mapped[str] = mapped_column(String(40))  # "driver", "owner" yoki "driver,owner"
    verified: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Load(Base):
    __tablename__ = "mutx_loads"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("mutx_users.id"), index=True)
    driver_id: Mapped[Optional[int]] = mapped_column(ForeignKey("mutx_users.id"), index=True)
    cargo: Mapped[str] = mapped_column(String(60))
    tonna: Mapped[float] = mapped_column(Float)
    from_city: Mapped[str] = mapped_column(String(60))
    to_city: Mapped[str] = mapped_column(String(60))
    transport: Mapped[str] = mapped_column(String(30))
    price: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[Optional[str]] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(12), default="new", index=True)  # new/accepted/done/cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    pickup_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pickup_lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    dropoff_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    dropoff_lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
class IdentityDocument(Base):
    __tablename__ = "mutx_identity_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("mutx_users.id"), index=True)
    document_type: Mapped[str] = mapped_column(String(20))
    filename: Mapped[str] = mapped_column(String(120))
    mime_type: Mapped[str] = mapped_column(String(40))
    encrypted_content: Mapped[bytes] = mapped_column(LargeBinary)
    encrypted_jshshir: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    encrypted_document_number: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("mutx_users.id"), nullable=True)
    review_note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)


class AdminAccess(Base):
    __tablename__ = "mutx_admin_access"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("mutx_users.id"), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(20))  # admin yoki superadmin
    permissions: Mapped[str] = mapped_column(String(1000), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("mutx_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AdminAudit(Base):
    __tablename__ = "mutx_admin_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("mutx_users.id"), index=True)
    action: Mapped[str] = mapped_column(String(80))
    target_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    details: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Complaint(Base):
    __tablename__ = "mutx_complaints"

    id: Mapped[int] = mapped_column(primary_key=True)
    load_id: Mapped[int] = mapped_column(ForeignKey("mutx_loads.id"), index=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("mutx_users.id"), index=True)
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    admin_id: Mapped[Optional[int]] = mapped_column(ForeignKey("mutx_users.id"), nullable=True)
    decision: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    penalty_amount: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Rating(Base):
    __tablename__ = "mutx_ratings"
    __table_args__ = (UniqueConstraint("load_id", "rater_id", name="uq_rating_once"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    load_id: Mapped[int] = mapped_column(ForeignKey("mutx_loads.id"), index=True)
    rater_id: Mapped[int] = mapped_column(ForeignKey("mutx_users.id"))
    rated_id: Mapped[int] = mapped_column(ForeignKey("mutx_users.id"), index=True)
    rated_role: Mapped[str] = mapped_column(String(10))  # "driver" yoki "owner"
    score: Mapped[int] = mapped_column(Integer)
    comment: Mapped[Optional[str]] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Base.metadata.create_all(engine)

# Mavjud bazaga lokatsiya ustunlarini qo‘shish.
def migrate_load_location_columns():
    from sqlalchemy import inspect, text
    existing = {c["name"] for c in inspect(engine).get_columns("mutx_loads")}
    with engine.begin() as connection:
        for name in ("pickup_lat", "pickup_lng", "dropoff_lat", "dropoff_lng"):
            if name not in existing:
                connection.execute(text(f"ALTER TABLE mutx_loads ADD COLUMN {name} FLOAT"))

migrate_load_location_columns()

# Mavjud IdentityDocument jadvaliga shifrlangan identifikator ustunlarini qo'shish.
def migrate_identity_number_columns():
    from sqlalchemy import inspect, text
    existing = {c["name"] for c in inspect(engine).get_columns("mutx_identity_documents")}
    with engine.begin() as connection:
        if "encrypted_jshshir" not in existing:
            connection.execute(text("ALTER TABLE mutx_identity_documents ADD COLUMN encrypted_jshshir BLOB"))
        if "encrypted_document_number" not in existing:
            connection.execute(text("ALTER TABLE mutx_identity_documents ADD COLUMN encrypted_document_number BLOB"))

migrate_identity_number_columns()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ----------------------------------------------------------------------------
# Parol va token
# ----------------------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt$" + salt.hex() + "$" + digest.hex()


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, hash_hex = stored.split("$")
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2 ** 14, r=8, p=1, dklen=32
        )
        return hmac.compare_digest(digest.hex(), hash_hex)
    except Exception:
        return False


DUMMY_HASH = hash_password("mutx-dummy-password")


def make_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id), "iat": utcnow(),
        "exp": utcnow() + timedelta(days=TOKEN_DAYS),
        "iss": JWT_ISSUER, "aud": JWT_AUDIENCE,
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


bearer = HTTPBearer(auto_error=False)


def current_user(
    cred: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if cred is None:
        raise HTTPException(status_code=401, detail="Avval tizimga kiring")
    try:
        data = jwt.decode(
            cred.credentials, SECRET_KEY, algorithms=["HS256"],
            issuer=JWT_ISSUER, audience=JWT_AUDIENCE,
            options={"require": ["sub", "iat", "exp", "iss", "aud", "jti"]},
        )
        user = db.get(User, int(data["sub"]))
    except Exception:
        raise HTTPException(status_code=401, detail="Sessiya tugagan, qayta kiring")
    if user is None:
        raise HTTPException(status_code=401, detail="Foydalanuvchi topilmadi")
    return user


# Kirishda ketma-ket xato urinishlarini cheklash (xotirada)
FAILED_LOGINS = {}
MAX_FAILS = 5
WINDOW_SECONDS = 15 * 60


def check_throttle(phone: str) -> None:
    now = time.time()
    recent = [t for t in FAILED_LOGINS.get(phone, []) if now - t < WINDOW_SECONDS]
    FAILED_LOGINS[phone] = recent
    if len(recent) >= MAX_FAILS:
        raise HTTPException(
            status_code=429,
            detail="Juda ko'p xato urinish. 15 daqiqadan keyin qayta urinib ko'ring.",
        )


def record_fail(phone: str) -> None:
    FAILED_LOGINS.setdefault(phone, []).append(time.time())


# ----------------------------------------------------------------------------
# Yordamchi funksiyalar
# ----------------------------------------------------------------------------

def role_list(user: User) -> List[str]:
    return [r for r in user.roles.split(",") if r]


def require_role(user: User, role: str) -> None:
    if role not in role_list(user):
        nom = "haydovchi" if role == "driver" else "yuk egasi"
        raise HTTPException(status_code=403, detail="Bu amal faqat " + nom + " uchun.")


def admin_access(user: User, db: Session) -> Optional[AdminAccess]:
    return db.scalar(
        select(AdminAccess).where(AdminAccess.user_id == user.id, AdminAccess.active.is_(True))
    )


def require_admin(user: User, db: Session, permission: Optional[str] = None) -> AdminAccess:
    access = admin_access(user, db)
    if access is None:
        raise HTTPException(status_code=403, detail="Admin ruxsati talab qilinadi")
    if access.role == "superadmin":
        return access
    permissions = [p for p in access.permissions.split(",") if p]
    if permission and permission not in permissions:
        raise HTTPException(status_code=403, detail="Bu amal uchun ruxsatingiz yo'q")
    return access


def user_public(user: User) -> dict:
    return {
        "id": user.id,
        "full_name": user.full_name,
        "phone": user.phone,
        "roles": role_list(user),
        "verified": user.verified,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }
def load_public(load: Load, viewer_id: int) -> dict:
    fee_each = round(load.tonna * FEE_PER_TONNA)
    if load.owner_id == viewer_id:
        my_role = "owner"
    elif load.driver_id == viewer_id:
        my_role = "driver"
    else:
        my_role = None
    can_view_location = (
        load.owner_id == viewer_id
        or (load.driver_id == viewer_id and load.status in ("accepted", "done"))
    )
    return {
        "id": load.id,
        "cargo": load.cargo,
        "tonna": load.tonna,
        "from_city": load.from_city,
        "to_city": load.to_city,
        "transport": load.transport,
        "price": load.price,
        "note": load.note,
        "status": load.status,
        "created_at": load.created_at.isoformat() if load.created_at else None,
        "accepted_at": load.accepted_at.isoformat() if load.accepted_at else None,
        "confirmation_deadline": (
            (load.accepted_at + timedelta(minutes=60)).isoformat()
            if load.accepted_at and load.status == "pending" else None
        ),
        "fee_each": fee_each,
        "fee_total": fee_each * 2,
        "my_role": my_role,
        "pickup_lat": load.pickup_lat if can_view_location else None,
        "pickup_lng": load.pickup_lng if can_view_location else None,
        "dropoff_lat": load.dropoff_lat if can_view_location else None,
        "dropoff_lng": load.dropoff_lng if can_view_location else None,
    }


# ----------------------------------------------------------------------------
# Ilova
# ----------------------------------------------------------------------------

app = FastAPI(title="YUKNOVA API")

if os.getenv("RENDER"):
    app.add_middleware(HTTPSRedirectMiddleware)

@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(self)"
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/admin/me")
def admin_me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    access = require_admin(user, db)
    return {
        "role": access.role,
        "permissions": (["*"] if access.role == "superadmin" else [p for p in access.permissions.split(",") if p]),
        "active": access.active,
    }


class SuperAdminSetupIn(BaseModel):
    setup_key: str


@app.post("/setup/superadmin")
def setup_superadmin(
    data: SuperAdminSetupIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    # Birinchi Super Admin faqat Render Environment'dagi maxfiy kalit
    # va SUPERADMIN_PHONE bilan mos kelgan ro'yxatdan o'tgan akkauntga beriladi.
    expected_key = os.getenv("SUPERADMIN_SETUP_KEY", "")
    expected_phone = os.getenv("SUPERADMIN_PHONE", "").strip()
    if not expected_key or not expected_phone:
        raise HTTPException(status_code=503, detail="Super Admin sozlamalari serverda hali kiritilmagan")
    if not hmac.compare_digest(data.setup_key, expected_key):
        raise HTTPException(status_code=403, detail="Sozlash kaliti noto'g'ri")
    if user.phone != expected_phone:
        raise HTTPException(status_code=403, detail="Bu akkaunt Super Admin uchun belgilangan emas")
    if db.scalar(select(AdminAccess).where(AdminAccess.role == "superadmin")):
        raise HTTPException(status_code=409, detail="Super Admin allaqachon sozlangan")
    access = AdminAccess(
        user_id=user.id,
        role="superadmin",
        permissions="*",
        active=True,
        created_by=user.id,
    )
    db.add(access)
    db.add(AdminAudit(actor_id=user.id, action="superadmin_bootstrap", target_user_id=user.id))
    db.commit()
    return {"success": True, "role": "superadmin", "message": "Super Admin sozlandi"}


@app.get("/admin/users")
def admin_users(
    q: Optional[str] = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    access = require_admin(user, db, "users.read")
    stmt = select(User)
    if q and q.strip():
        term = "%" + q.strip().lower() + "%"
        stmt = stmt.where(or_(func.lower(User.full_name).like(term), User.phone.like("%" + q.strip() + "%"), User.id == (int(q) if q.isdigit() else -1)))
    users = db.scalars(stmt.order_by(User.id.desc()).limit(200))
    return [
        {
            "id": item.id,
            "full_name": item.full_name,
            "phone": item.phone if access.role == "superadmin" else item.phone[:4] + "****" + item.phone[-2:],
            "roles": role_list(item),
            "verified": item.verified,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "admin_role": (
                admin_access(item, db).role if admin_access(item, db) else None
            ),
        }
        for item in users
    ]


class AdminGrantIn(BaseModel):
    user_id: int
    permissions: List[str] = Field(default_factory=list)


ALLOWED_ADMIN_PERMISSIONS = {
    "users.read", "users.manage", "loads.read", "loads.manage",
    "complaints.manage", "finance.read", "identity.review",
}


@app.post("/admin/admins")
def grant_admin(
    data: AdminGrantIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    actor_access = require_admin(user, db)
    if actor_access.role != "superadmin":
        raise HTTPException(status_code=403, detail="Adminni faqat Super Admin tayinlaydi")
    target = db.get(User, data.user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")
    if not target.verified:
        raise HTTPException(status_code=409, detail="Admin qilishdan oldin foydalanuvchi shaxsini tasdiqlash kerak")
    if data.user_id == user.id:
        raise HTTPException(status_code=400, detail="O'zingizga admin vakolati berib bo'lmaydi")
    if any(p not in ALLOWED_ADMIN_PERMISSIONS for p in data.permissions):
        raise HTTPException(status_code=400, detail="Noma'lum ruxsat turi")
    access = db.scalar(select(AdminAccess).where(AdminAccess.user_id == target.id))
    if access and access.role == "superadmin":
        raise HTTPException(status_code=409, detail="Super Admin vakolatini bu yerdan o'zgartirib bo'lmaydi")
    if access is None:
        access = AdminAccess(user_id=target.id, role="admin", active=True, created_by=user.id)
        db.add(access)
    access.role = "admin"
    access.permissions = ",".join(sorted(set(data.permissions)))
    access.active = True
    access.created_by = user.id
    db.add(AdminAudit(
        actor_id=user.id,
        action="admin_granted",
        target_user_id=target.id,
        details=access.permissions,
    ))
    db.commit()
    return {"success": True, "user_id": target.id, "role": "admin", "permissions": data.permissions}


@app.delete("/admin/admins/{target_user_id}")
def revoke_admin(
    target_user_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    actor_access = require_admin(user, db)
    if actor_access.role != "superadmin":
        raise HTTPException(status_code=403, detail="Adminni faqat Super Admin bekor qiladi")
    access = db.scalar(select(AdminAccess).where(AdminAccess.user_id == target_user_id))
    if access is None or access.role != "admin":
        raise HTTPException(status_code=404, detail="Admin topilmadi")
    access.active = False
    db.add(AdminAudit(actor_id=user.id, action="admin_revoked", target_user_id=target_user_id))
    db.commit()
    return {"success": True, "message": "Admin vakolati bekor qilindi"}


class ComplaintIn(BaseModel):
    load_id: int
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=500)]


class ComplaintDecisionIn(BaseModel):
    decision: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=500)]
    penalty_amount: int = Field(default=0, ge=0, le=100_000_000)
    status: str = "resolved"


@app.post("/complaints")
def create_complaint(
    data: ComplaintIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    load = db.get(Load, data.load_id)
    reason = data.reason.strip()
    if load is None or user.id not in (load.owner_id, load.driver_id):
        raise HTTPException(status_code=404, detail="Buyurtma topilmadi")
    if load.status not in ("accepted", "done", "cancelled"):
        raise HTTPException(status_code=409, detail="Shikoyat faqat boshlangan buyurtma bo'yicha yuboriladi")
    if not 5 <= len(reason) <= 500:
        raise HTTPException(status_code=400, detail="Sabab 5 dan 500 belgigacha bo'lsin")
    existing = db.scalar(select(Complaint).where(
        Complaint.load_id == load.id,
        Complaint.reporter_id == user.id,
        Complaint.status == "open",
    ))
    if existing:
        raise HTTPException(status_code=409, detail="Bu buyurtma bo'yicha ochiq shikoyatingiz bor")
    complaint = Complaint(load_id=load.id, reporter_id=user.id, reason=reason)
    db.add(complaint)
    db.commit()
    db.refresh(complaint)
    return {"success": True, "complaint_id": complaint.id, "status": complaint.status}


@app.get("/admin/complaints")
def admin_complaints(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_admin(user, db, "complaints.manage")
    rows = db.scalars(select(Complaint).order_by(Complaint.id.desc()).limit(200))
    return [{
        "id": c.id, "load_id": c.load_id, "reporter_id": c.reporter_id,
        "reason": c.reason, "status": c.status, "admin_id": c.admin_id,
        "decision": c.decision, "penalty_amount": c.penalty_amount,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
    } for c in rows]


@app.post("/admin/complaints/{complaint_id}/decision")
def decide_complaint(
    complaint_id: int,
    data: ComplaintDecisionIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_admin(user, db, "complaints.manage")
    complaint = db.get(Complaint, complaint_id)
    if complaint is None:
        raise HTTPException(status_code=404, detail="Shikoyat topilmadi")
    decision = data.decision.strip()
    if not 5 <= len(decision) <= 500:
        raise HTTPException(status_code=400, detail="Qaror 5 dan 500 belgigacha bo'lsin")
    if data.penalty_amount < 0 or data.penalty_amount > 100_000_000:
        raise HTTPException(status_code=400, detail="Jarima miqdori noto'g'ri")
    if data.status not in ("resolved", "rejected"):
        raise HTTPException(status_code=400, detail="Holat resolved yoki rejected bo'lishi kerak")
    if complaint.status != "open":
        raise HTTPException(status_code=409, detail="Bu shikoyat avval ko'rib chiqilgan")
    complaint.status = data.status
    complaint.admin_id = user.id
    complaint.decision = decision
    complaint.penalty_amount = data.penalty_amount
    complaint.resolved_at = utcnow()
    db.add(AdminAudit(
        actor_id=user.id, action="complaint_decided",
        target_user_id=complaint.reporter_id,
        details=f"complaint={complaint.id}; status={data.status}; penalty={data.penalty_amount}",
    ))
    db.commit()
    return {"success": True, "complaint_id": complaint.id, "status": complaint.status,
            "penalty_amount": complaint.penalty_amount}


# ------------------------- ID / pasport tekshiruvi ---------------------------

@app.post("/identity/documents")
async def submit_identity_document(
    document_type: str = Form(...),
    consent: bool = Form(...),
    jshshir: str = Form(...),
    document_number: str = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if document_type not in ("id_card", "passport"):
        raise HTTPException(status_code=400, detail="Hujjat turi ID karta yoki pasport bo'lishi kerak")
    if consent is not True:
        raise HTTPException(status_code=400, detail="Hujjatlarni qayta ishlashga rozilik talab qilinadi")
    normalized_jshshir = re.sub(r"\\D", "", jshshir or "")
    normalized_document_number = re.sub(r"\\s+", "", (document_number or "").upper())
    if not re.fullmatch(r"\\d{14}", normalized_jshshir):
        raise HTTPException(status_code=400, detail="JShShIR 14 ta raqamdan iborat bo'lishi kerak")
    if not re.fullmatch(r"[A-Z]{2}\\d{7}", normalized_document_number):
        raise HTTPException(status_code=400, detail="Hujjat seriyasi va raqami 2 ta lotin harfi va 7 ta raqam bo'lishi kerak")
    if document_cipher is None:
        raise HTTPException(status_code=503, detail="Hujjatlarni shifrlash kaliti serverda sozlanmagan")
    existing = db.scalar(select(IdentityDocument).where(
        IdentityDocument.user_id == user.id,
        IdentityDocument.status.in_(("pending", "approved")),
    ))
    if existing:
        raise HTTPException(status_code=409, detail="Sizda tekshiruvdagi yoki tasdiqlangan hujjat mavjud")
    content = await file.read(MAX_ID_DOCUMENT_BYTES + 1)
    if not content or len(content) > MAX_ID_DOCUMENT_BYTES:
        raise HTTPException(status_code=400, detail="Fayl bo'sh yoki 5 MB dan katta")
    detected = None
    if content.startswith(bytes.fromhex("FFD8FF")):
        detected = "image/jpeg"
    elif content.startswith(bytes.fromhex("89504E470D0A1A0A")):
        detected = "image/png"
    elif content.startswith(b"%PDF-"):
        detected = "application/pdf"
    if detected is None:
        raise HTTPException(status_code=400, detail="Faqat haqiqiy JPG, PNG yoki PDF fayl yuboring")
    encrypted = document_cipher.encrypt(content)
    safe_name = (file.filename or "document").replace("/", "_").replace(chr(92), "_")[:120]
    item = IdentityDocument(
        user_id=user.id, document_type=document_type, filename=safe_name,
        mime_type=detected, encrypted_content=encrypted,
        encrypted_jshshir=document_cipher.encrypt(normalized_jshshir.encode("utf-8")),
        encrypted_document_number=document_cipher.encrypt(normalized_document_number.encode("utf-8")),
        status="pending", consent_at=utcnow(),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"success": True, "document_id": item.id, "status": item.status,
            "message": "Hujjat qabul qilindi. Admin tekshiruvini kuting."}


@app.get("/identity/status")
def identity_status(user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.scalar(select(IdentityDocument).where(
        IdentityDocument.user_id == user.id
    ).order_by(IdentityDocument.id.desc()).limit(1))
    if item is None:
        return {"status": "not_submitted", "verified": user.verified}
    return {"status": item.status, "document_type": item.document_type,
            "review_note": item.review_note, "created_at": item.created_at.isoformat(),
            "verified": user.verified}


@app.get("/admin/identity/documents")
def admin_identity_documents(
    user: User = Depends(current_user), db: Session = Depends(get_db)
):
    require_admin(user, db, "identity.review")
    rows = db.scalars(select(IdentityDocument).where(
        IdentityDocument.status == "pending"
    ).order_by(IdentityDocument.created_at.asc()).limit(100))
    result = []
    for item in rows:
        owner = db.get(User, item.user_id)
        result.append({"id": item.id, "user_id": item.user_id,
                       "full_name": owner.full_name if owner else "Noma'lum",
                       "phone": owner.phone if owner else "",
                       "document_type": item.document_type, "filename": item.filename,
                       "mime_type": item.mime_type,
                       "created_at": item.created_at.isoformat() if item.created_at else None})
    return result


@app.get("/admin/identity/documents/{document_id}/file")
def admin_identity_document_file(
    document_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    require_admin(user, db, "identity.review")
    item = db.get(IdentityDocument, document_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    if document_cipher is None:
        raise HTTPException(status_code=503, detail="Hujjat shifrlash kaliti sozlanmagan")
    try:
        content = document_cipher.decrypt(item.encrypted_content)
    except InvalidToken:
        logger.exception("Identity document decryption failed: %s", document_id)
        raise HTTPException(status_code=500, detail="Hujjatni ochib bo'lmadi")
    return Response(content=content, media_type=item.mime_type,
                    headers={"Content-Disposition": "inline; filename=identity-document",
                             "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


class IdentityDecisionIn(BaseModel):
    status: str
    review_note: Optional[str] = None


@app.post("/admin/identity/documents/{document_id}/decision")
def decide_identity_document(
    document_id: int, data: IdentityDecisionIn,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    require_admin(user, db, "identity.review")
    item = db.get(IdentityDocument, document_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    if item.status != "pending":
        raise HTTPException(status_code=409, detail="Bu hujjat avval ko'rib chiqilgan")
    if data.status not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="Holat approved yoki rejected bo'lishi kerak")
    note = (data.review_note or "").strip() or None
    if note and len(note) > 500:
        raise HTTPException(status_code=400, detail="Izoh 500 belgidan oshmasin")
    if data.status == "rejected" and not note:
        raise HTTPException(status_code=400, detail="Rad etish sababini yozing")
    item.status = data.status
    item.review_note = note
    item.reviewed_by = user.id
    item.reviewed_at = utcnow()
    target = db.get(User, item.user_id)
    if target:
        target.verified = data.status == "approved"
    db.add(AdminAudit(actor_id=user.id, action="identity_" + data.status,
                      target_user_id=item.user_id, details="document_id=" + str(item.id)))
    db.commit()
    return {"success": True, "document_id": item.id, "status": item.status,
            "user_verified": bool(target and target.verified)}


@app.get("/admin/audit")
def admin_audit(user: User = Depends(current_user), db: Session = Depends(get_db)):
    access = require_admin(user, db)
    if access.role != "superadmin":
        raise HTTPException(status_code=403, detail="Audit tarixini faqat Super Admin ko'radi")
    rows = db.scalars(select(AdminAudit).order_by(AdminAudit.id.desc()).limit(200))
    return [
        {"id": row.id, "actor_id": row.actor_id, "action": row.action,
         "target_user_id": row.target_user_id, "details": row.details,
         "created_at": row.created_at.isoformat() if row.created_at else None}
        for row in rows
    ]



# ---------------------------- YUKNOVA AI yordamchisi ---------------------------
AI_SYSTEM_PROMPT = """
Siz YUKNOVA logistika platformasining rasmiy AI yordamchisisiz.
Faqat YUKNOVA xizmatlari: ro'yxatdan o'tish, haydovchi/yuk egasi, yuk joylash,
buyurtma qabul qilish, tariflar, admin va shikoyatlar haqida o'zbek tilida
aniq va xushmuomala javob bering. YUKNOVA qoidalarida noma'lum bo'lgan narsani
to'qib chiqarmang; "bu masalani admin tasdiqlashi kerak" deb ayting.
Har bir tomon uchun xizmat haqi 1 tonnaga 10 000 so'm deb tushuntiring.
Parol, SMS-kod, karta raqami, CVV, API kalit yoki pasport ma'lumotlarini
so'ramang. To'lovni bajarmang, jarima tayinlamang, admin vakolatini bermang.
Huquqiy, moliyaviy yoki xavfsizlik bo'yicha yakuniy qaror chiqarmang.
AI ekaningizni yashirmang. Kerak bo'lsa admin/operatorga murojaat qilishni tavsiya qiling.
"""


class AIChatIn(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


@app.post("/ai/chat")
async def ai_chat(data: AIChatIn, user: User = Depends(current_user)):
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="AI hozircha ulanmagan. Render Environment bo'limiga OPENAI_API_KEY qo'shilishi kerak.",
        )
    try:
        client = AsyncOpenAI(api_key=api_key, timeout=25.0, max_retries=1)
        response = await client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-5.5"),
            instructions=AI_SYSTEM_PROMPT,
            input=f"Foydalanuvchi roli: {','.join(role_list(user))}. Savol: {data.message}",
            max_output_tokens=500,
            store=False,
        )
        answer = (response.output_text or "").strip()
        if not answer:
            raise HTTPException(status_code=502, detail="AI javobi bo'sh qaytdi. Qayta urinib ko'ring.")
        return {"answer": answer, "assistant": "YUKNOVA AI"}
    except HTTPException:
        raise
    except Exception as exc:
        # Render Logs'da xato turi va OpenAI statusi ko'rinadi; maxfiy kalit logga yozilmaydi.
        logger.exception(
            "YUKNOVA AI request failed (type=%s, status=%s, code=%s)",
            type(exc).__name__,
            getattr(exc, "status_code", None),
            getattr(exc, "code", None),
        )
        raise HTTPException(status_code=502, detail="AI xizmatida vaqtinchalik xatolik. Render Logs orqali tekshirilmoqda.")


@app.get("/health")
def health():
    try:
        with engine.connect() as connection:
            connection.execute(select(1))
        return {"status": "ok", "database": "sqlite" if IS_SQLITE else "postgresql"}
    except Exception:
        logger.exception("YUKNOVA database health check failed")
        raise HTTPException(status_code=503, detail="Ma'lumotlar bazasiga ulanishda xatolik")


# ---------------------------- Ro'yxatdan o'tish / kirish --------------------

class RegisterIn(BaseModel):
    full_name: str
    phone: str
    password: str
    roles: List[str]


class LoginIn(BaseModel):
    phone: str
    password: str


@app.post("/register")
def register(data: RegisterIn, db: Session = Depends(get_db)):
    full_name = data.full_name.strip()
    phone = data.phone.strip()

    if not 2 <= len(full_name) <= 80:
        raise HTTPException(status_code=400, detail="Ism va familiya 2 dan 80 gacha belgi bo'lsin")
    if not PHONE_RE.match(phone):
        raise HTTPException(
            status_code=400,
            detail="Telefon raqam +998 formatida bo'lishi kerak (masalan +998901234567)",
        )
    if not 8 <= len(data.password) <= 128:
        raise HTTPException(status_code=400, detail="Parol kamida 8 ta belgidan iborat bo'lsin")

    roles = []
    for r in data.roles:
        norm = ROLE_ALIASES.get(r.strip().lower())
        if norm is None:
            raise HTTPException(status_code=400, detail="Noma'lum rol: " + r)
        if norm not in roles:
            roles.append(norm)
    if not roles:
        raise HTTPException(status_code=400, detail="Kamida bitta rolni tanlang")

    if db.scalar(select(User).where(User.phone == phone)):
        raise HTTPException(status_code=409, detail="Bu telefon raqam allaqachon ro'yxatdan o'tgan")

    user = User(
        full_name=full_name,
        phone=phone,
        password_hash=hash_password(data.password),
        roles=",".join(roles),
        verified=False,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Bu telefon raqam allaqachon ro'yxatdan o'tgan")

    return {
        "success": True,
        "message": "YUKNOVA hisobingiz yaratildi",
        "user_id": user.id,
        "verified": user.verified,
        "token": make_token(user.id),
    }


@app.post("/login")
def login(data: LoginIn, db: Session = Depends(get_db)):
    phone = data.phone.strip()
    check_throttle(phone)

    user = db.scalar(select(User).where(User.phone == phone))
    stored = user.password_hash if user else DUMMY_HASH
    ok = verify_password(data.password, stored)

    if not user or not ok:
        record_fail(phone)
        raise HTTPException(status_code=401, detail="Telefon raqam yoki parol noto'g'ri")

    FAILED_LOGINS.pop(phone, None)
    return {"token": make_token(user.id), "user": user_public(user)}


class ProfileUpdateIn(BaseModel):
    full_name: str


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str


@app.put("/me")
def update_me(data: ProfileUpdateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    full_name = data.full_name.strip()
    if not 2 <= len(full_name) <= 80:
        raise HTTPException(status_code=400, detail="Ism va familiya 2 dan 80 gacha belgi bo'lsin")
    user.full_name = full_name
    db.commit()
    db.refresh(user)
    return user_public(user)


@app.post("/me/password")
def change_password(data: PasswordChangeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Amaldagi parol noto'g'ri")
    if not 8 <= len(data.new_password) <= 128:
        raise HTTPException(status_code=400, detail="Yangi parol 8 dan 128 belgigacha bo'lsin")
    if data.current_password == data.new_password:
        raise HTTPException(status_code=400, detail="Yangi parol avvalgisidan farq qilishi kerak")
    user.password_hash = hash_password(data.new_password)
    db.commit()
    return {"success": True, "message": "Parol muvaffaqiyatli almashtirildi. Xavfsizlik uchun qayta kiring."}


@app.get("/me")
def me(user: User = Depends(current_user)):
    return user_public(user)


@app.get("/users/{user_id}")
def get_user(user_id: int, user: User = Depends(current_user)):
    # Faqat o'z ma'lumotini ko'ra oladi (boshqalarning telefoni yopiq)
    if user_id != user.id:
        raise HTTPException(status_code=403, detail="Boshqa foydalanuvchi ma'lumotini ko'rib bo'lmaydi")
    return user_public(user)


# ---------------------------- Yuklar ----------------------------------------

class LoadIn(BaseModel):
    cargo: str
    tonna: float
    from_city: str
    to_city: str
    transport: str
    price: int = 0
    note: Optional[str] = None
    pickup_lat: Optional[float] = None
    pickup_lng: Optional[float] = None
    dropoff_lat: Optional[float] = None
    dropoff_lng: Optional[float] = None


@app.post("/loads")
def create_load(data: LoadIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    # Yukni faqat yuk egasi roliga ega foydalanuvchi joylashtira oladi.
    require_role(user, "owner")

    cargo = data.cargo.strip()
    from_city = data.from_city.strip()
    to_city = data.to_city.strip()
    note = (data.note or "").strip() or None

    if not 2 <= len(cargo) <= 60:
        raise HTTPException(status_code=400, detail="Yuk turi 2 dan 60 gacha belgi bo'lsin")
    if not 0.1 <= data.tonna <= 100:
        raise HTTPException(status_code=400, detail="Og'irlik 0.1 dan 100 tonnagacha bo'lsin")
    if not (2 <= len(from_city) <= 60 and 2 <= len(to_city) <= 60):
        raise HTTPException(status_code=400, detail="Manzil nomi 2 dan 60 gacha belgi bo'lsin")
    if from_city.lower() == to_city.lower():
        raise HTTPException(status_code=400, detail="Jo'natish va yetkazish joyi bir xil bo'lmasin")
    transport = data.transport.strip()
    if transport.lower() == "fura / tirkama":
        transport = "Fura / Tirkama"
    if transport not in TRANSPORTS:
        raise HTTPException(status_code=400, detail="Transport turi noto'g'ri")
    if data.price < 0:
        raise HTTPException(status_code=400, detail="Narx manfiy bo'lmasin")
    coords = (data.pickup_lat, data.pickup_lng, data.dropoff_lat, data.dropoff_lng)
    if any(v is None for v in coords):
        raise HTTPException(status_code=400, detail="Yuk olish va yetkazish joylarini xaritada belgilang")
    if not (-90 <= data.pickup_lat <= 90 and -180 <= data.pickup_lng <= 180 and -90 <= data.dropoff_lat <= 90 and -180 <= data.dropoff_lng <= 180):
        raise HTTPException(status_code=400, detail="Xarita koordinatalari noto‘g‘ri")
    if note and len(note) > 300:
        raise HTTPException(status_code=400, detail="Izoh 300 belgidan oshmasin")

    load = Load(
        owner_id=user.id,
        cargo=cargo,
        tonna=round(data.tonna, 1),
        from_city=from_city,
        to_city=to_city,
        transport=transport,
        price=data.price,
        note=note,
        pickup_lat=data.pickup_lat,
        pickup_lng=data.pickup_lng,
        dropoff_lat=data.dropoff_lat,
        dropoff_lng=data.dropoff_lng,
        status="new",
    )
    db.add(load)
    db.commit()
    db.refresh(load)
    return load_public(load, user.id)


def expire_pending_loads(db: Session) -> None:
    """60 daqiqada egasi tasdiqlamagan haydovchi so'rovlarini qayta ochadi."""
    cutoff = utcnow() - timedelta(minutes=60)
    db.execute(
        update(Load)
        .where(
            Load.status == "pending",
            Load.accepted_at.is_not(None),
            Load.accepted_at <= cutoff,
        )
        .values(status="new", driver_id=None, accepted_at=None)
    )
    db.commit()


@app.get("/loads")
def list_loads(
    scope: str = Query("available", pattern="^(available|mine)$"),
    q: Optional[str] = None,
    transport: Optional[str] = None,
    max_tonna: Optional[float] = Query(None, gt=0, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    expire_pending_loads(db)
    stmt = select(Load)

    if scope == "available":
        # Barcha ro‘yxatdan o‘tgan foydalanuvchilar ochiq yuklarni ko‘ra oladi.
        stmt = stmt.where(Load.status == "new", Load.owner_id != user.id)
        if transport:
            stmt = stmt.where(Load.transport == transport)
        if max_tonna is not None:
            stmt = stmt.where(Load.tonna <= max_tonna)
        if q:
            like = "%" + q.strip().lower() + "%"
            stmt = stmt.where(
                or_(func.lower(Load.from_city).like(like), func.lower(Load.to_city).like(like))
            )
    else:
        stmt = stmt.where(or_(Load.owner_id == user.id, Load.driver_id == user.id))

    stmt = stmt.order_by(Load.id.desc()).limit(100)
    return [load_public(item, user.id) for item in db.scalars(stmt)]


@app.post("/loads/{load_id}/accept")
def accept_load(load_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_role(user, "driver")
    result = db.execute(
        update(Load)
        .where(Load.id == load_id, Load.status == "new", Load.owner_id != user.id)
        .values(status="pending", driver_id=user.id, accepted_at=utcnow())
    )
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=409, detail="Bu yuk allaqachon qabul qilingan yoki mavjud emas")
    return load_public(db.get(Load, load_id), user.id)


@app.post("/loads/{load_id}/confirm")
def confirm_load(load_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Yuk egasi haydovchi so'rovini 60 daqiqa ichida tasdiqlaydi."""
    expire_pending_loads(db)
    result = db.execute(
        update(Load)
        .where(
            Load.id == load_id,
            Load.owner_id == user.id,
            Load.status == "pending",
            Load.accepted_at.is_not(None),
            Load.accepted_at > utcnow() - timedelta(minutes=60),
        )
        .values(status="accepted")
    )
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(
            status_code=409,
            detail="Tasdiqlash so'rovi topilmadi yoki 60 daqiqalik muddat tugagan",
        )
    return load_public(db.get(Load, load_id), user.id)


@app.post("/loads/{load_id}/reject")
def reject_load(load_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Yuk egasi haydovchi so'rovini rad etib, yukni qayta ochadi."""
    result = db.execute(
        update(Load)
        .where(
            Load.id == load_id,
            Load.owner_id == user.id,
            Load.status == "pending",
        )
        .values(status="new", driver_id=None, accepted_at=None)
    )
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=409, detail="Rad etiladigan haydovchi so'rovi topilmadi")
    return load_public(db.get(Load, load_id), user.id)


@app.post("/loads/{load_id}/complete")
def complete_load(load_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    result = db.execute(
        update(Load)
        .where(Load.id == load_id, Load.status == "accepted", Load.driver_id == user.id)
        .values(status="done")
    )
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=409, detail="Yukni yakunlab bo'lmaydi")
    return load_public(db.get(Load, load_id), user.id)


@app.post("/loads/{load_id}/cancel")
def cancel_load(load_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    result = db.execute(
        update(Load)
        .where(Load.id == load_id, Load.status == "new", Load.owner_id == user.id)
        .values(status="cancelled")
    )
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(
            status_code=409,
            detail="Faqat yangi buyurtmani bekor qilish mumkin. Qabul qilinganini admin orqali.",
        )
    return load_public(db.get(Load, load_id), user.id)


@app.get("/loads/{load_id}/contact")
def load_contact(load_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    load = db.get(Load, load_id)
    if load is None or user.id not in (load.owner_id, load.driver_id):
        raise HTTPException(status_code=404, detail="Buyurtma topilmadi")
    if load.status not in ("accepted", "done") or load.driver_id is None:
        raise HTTPException(status_code=409, detail="Aloqa ma'lumoti yuk qabul qilingach ochiladi")
    owner = db.get(User, load.owner_id)
    driver = db.get(User, load.driver_id)
    return {
        "owner_name": owner.full_name,
        "owner_phone": owner.phone,
        "driver_name": driver.full_name,
        "driver_phone": driver.phone,
    }


# ---------------------------- Baholash --------------------------------------

class RatingIn(BaseModel):
    score: int
    comment: Optional[str] = None


@app.post("/loads/{load_id}/rate")
def rate_load(
    load_id: int, data: RatingIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    load = db.get(Load, load_id)
    if load is None or user.id not in (load.owner_id, load.driver_id):
        raise HTTPException(status_code=404, detail="Buyurtma topilmadi")
    if load.status != "done" or load.driver_id is None:
        raise HTTPException(status_code=409, detail="Baholash faqat yakunlangan buyurtma uchun mumkin")
    if not 1 <= data.score <= 5:
        raise HTTPException(status_code=400, detail="Baho 1 dan 5 gacha bo'lsin")

    comment = (data.comment or "").strip() or None
    if comment and len(comment) > 300:
        raise HTTPException(status_code=400, detail="Izoh 300 belgidan oshmasin")

    if user.id == load.owner_id:
        rated_id, rated_role = load.driver_id, "driver"
    else:
        rated_id, rated_role = load.owner_id, "owner"

    db.add(
        Rating(
            load_id=load.id,
            rater_id=user.id,
            rated_id=rated_id,
            rated_role=rated_role,
            score=data.score,
            comment=comment,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Siz bu buyurtmani allaqachon baholagansiz")
    return {"success": True, "message": "Rahmat! Bahoyingiz qabul qilindi"}


@app.get("/loads/{load_id}/my-rating")
def my_load_rating(load_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    load = db.get(Load, load_id)
    if load is None or user.id not in (load.owner_id, load.driver_id):
        raise HTTPException(status_code=404, detail="Buyurtma topilmadi")
    rating = db.scalar(select(Rating).where(Rating.load_id == load_id, Rating.rater_id == user.id))
    return {"has_rated": rating is not None, "score": rating.score if rating else None, "comment": rating.comment if rating else None}


@app.get("/me/rating")
def my_rating(user: User = Depends(current_user), db: Session = Depends(get_db)):
    result = {"as_driver": {"avg": None, "count": 0}, "as_owner": {"avg": None, "count": 0}}
    rows = db.execute(
        select(Rating.rated_role, func.avg(Rating.score), func.count(Rating.id))
        .where(Rating.rated_id == user.id)
        .group_by(Rating.rated_role)
    )
    for role, avg, count in rows:
        key = "as_driver" if role == "driver" else "as_owner"
        result[key] = {"avg": round(float(avg), 1), "count": count}
    return result
