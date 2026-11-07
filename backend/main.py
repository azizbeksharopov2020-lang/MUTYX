[07.11.2026 22:18] Azizbek Sharopov: """
MUTX API (FastAPI)

Muhim sozlamalar Render'dagi Environment bo'limida turadi (kodga yozilmaydi):
  DATABASE_URL  - bazaga ulanish manzili (Supabase "Session pooler" manzili)
  SECRET_KEY    - uzun tasodifiy qator (kirish tokenlarini imzolash uchun)
Ular berilmasa, server sinov rejimida ishlaydi: SQLite fayl va vaqtinchalik kalit.
Render'ning bepul tarifida SQLite fayl har deploy'da o'chadi, shuning uchun
haqiqiy foydalanish uchun DATABASE_URL shart.
"""

import hashlib
import hmac
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import jwt
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
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

SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_urlsafe(48)
TOKEN_DAYS = 7

FEE_PER_TONNA = 10000  # har bir tomon uchun so'm / tonna

ALLOWED_ORIGINS = [
    "https://azizbeksharopov2020-lang.github.io",
    "http://127.0.0.1:5500",
    "http://localhost:5500",
]

PHONE_RE = re.compile(r"^\+998[0-9]{9}$")

ROLE_ALIASES = {
    "driver": "driver",
    "haydovchi": "driver",
    "owner": "owner",
    "yuk_egasi": "owner",
    "cargo_owner": "owner",
}

TRANSPORTS = {"Yuk mashinasi", "Gazel", "Fura / Tirkama", "Refrijerator", "Boshqa"}

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
    tablename = "mutx_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    roles: Mapped[str] = mapped_column(String(40))  # "driver", "owner" yoki "driver,owner"
    verified: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Load(Base):
    tablename = "mutx_loads"

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
[07.11.2026 22:18] Azizbek Sharopov: class Rating(Base):
    tablename = "mutx_ratings"
    table_args = (UniqueConstraint("load_id", "rater_id", name="uq_rating_once"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    load_id: Mapped[int] = mapped_column(ForeignKey("mutx_loads.id"), index=True)
    rater_id: Mapped[int] = mapped_column(ForeignKey("mutx_users.id"))
    rated_id: Mapped[int] = mapped_column(ForeignKey("mutx_users.id"), index=True)
    rated_role: Mapped[str] = mapped_column(String(10))  # "driver" yoki "owner"
    score: Mapped[int] = mapped_column(Integer)
    comment: Mapped[Optional[str]] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Base.metadata.create_all(engine)


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
    payload = {"sub": str(user_id), "exp": utcnow() + timedelta(days=TOKEN_DAYS)}
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


bearer = HTTPBearer(auto_error=False)


def current_user(
    cred: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if cred is None:
        raise HTTPException(status_code=401, detail="Avval tizimga kiring")
    try:
        data = jwt.decode(cred.credentials, SECRET_KEY, algorithms=["HS256"])
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


def user_public(user: User) -> dict:
    return {
        "id": user.id,
        "full_name": user.full_name,
        "phone": user.phone,
        "roles": role_list(user),
        "verified": user.verified,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }
[07.11.2026 22:18] Azizbek Sharopov: def load_public(load: Load, viewer_id: int) -> dict:
    fee_each = round(load.tonna * FEE_PER_TONNA)
    if load.owner_id == viewer_id:
        my_role = "owner"
    elif load.driver_id == viewer_id:
        my_role = "driver"
    else:
        my_role = None
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
        "fee_each": fee_each,
        "fee_total": fee_each * 2,
        "my_role": my_role,
    }


# ----------------------------------------------------------------------------
# Ilova
# ----------------------------------------------------------------------------

app = FastAPI(title="MUTX API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "database": "sqlite" if IS_SQLITE else "postgresql"}


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
    if not 8 <= len(data.password) <= 100:
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
        "message": "MUTX hisobingiz yaratildi",
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


@app.get("/me")
def me(user: User = Depends(current_user)):
    return user_public(user)


@app.get("/users/{user_id}")
[07.11.2026 22:18] Azizbek Sharopov: def get_user(user_id: int, user: User = Depends(current_user)):
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


@app.post("/loads")
def create_load(data: LoadIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
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
    if data.transport not in TRANSPORTS:
        raise HTTPException(status_code=400, detail="Transport turi noto'g'ri")
    if data.price < 0:
        raise HTTPException(status_code=400, detail="Narx manfiy bo'lmasin")
    if note and len(note) > 300:
        raise HTTPException(status_code=400, detail="Izoh 300 belgidan oshmasin")

    load = Load(
        owner_id=user.id,
        cargo=cargo,
        tonna=round(data.tonna, 1),
        from_city=from_city,
        to_city=to_city,
        transport=data.transport,
        price=data.price,
        note=note,
        status="new",
    )
    db.add(load)
    db.commit()
    db.refresh(load)
    return load_public(load, user.id)


@app.get("/loads")
def list_loads(
    scope: str = Query("available", pattern="^(available|mine)$"),
    q: Optional[str] = None,
    transport: Optional[str] = None,
    max_tonna: Optional[float] = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Load)

    if scope == "available":
        require_role(user, "driver")
        stmt = stmt.where(Load.status == "new", Load.owner_id != user.id)
        if transport:
            stmt = stmt.where(Load.transport == transport)
        if max_tonna:
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
        .values(status="accepted", driver_id=user.id, accepted_at=utcnow())
    )
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=409, detail="Bu yuk allaqachon qabul qilingan yoki mavjud emas")
    return load_public(db.get(Load, load_id), user.id)


@app.post("/loads/{load_id}/complete")
def complete_load(load_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
[07.11.2026 22:18] Azizbek Sharopov: result = db.execute(
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
