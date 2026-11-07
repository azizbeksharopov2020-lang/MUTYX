from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from passlib.context import CryptContext
from pathlib import Path
import sqlite3
import re
from fastapi.middleware.cors import CORSMiddleware
app = FastAPI(
    title="MUTX API",
    description="MUTX logistika platformasi serveri",
    version="1.0.0"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Parollarni xavfsiz xeshlash
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)

# Ma'lumotlar bazasi
DB_PATH = Path(__file__).parent / "mutx.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            phone TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            roles TEXT NOT NULL,
            verified INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


init_db()


# Ro'yxatdan o'tish ma'lumotlari
class RegisterUser(BaseModel):
    full_name: str = Field(min_length=3, max_length=100)
    phone: str
    password: str = Field(min_length=8)
    roles: list[str]


@app.get("/")
def home():
    return {
        "message": "MUTX serveri ishlayapti!",
        "status": "online"
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/register")
def register(user: RegisterUser):
    full_name = user.full_name.strip()
    phone = user.phone.strip()

    if not re.fullmatch(r"\+998\d{9}", phone):
        raise HTTPException(
            status_code=400,
            detail="Telefon raqam +998 formatida bo'lishi kerak"
        )

    allowed_roles = {"driver", "owner"}

    if not user.roles or not set(user.roles).issubset(allowed_roles):
        raise HTTPException(
            status_code=400,
            detail="Haydovchi yoki yuk egasi rolini tanlang"
        )

    if len(set(user.roles)) != len(user.roles):
        raise HTTPException(
            status_code=400,
            detail="Bir xil rolni takror tanlamang"
        )

    password_hash = pwd_context.hash(user.password)

    conn = get_db()

    try:
        cursor = conn.execute("""
            INSERT INTO users
            (full_name, phone, password_hash, roles)
            VALUES (?, ?, ?, ?)
        """, (
            full_name,
            phone,
            password_hash,
            ",".join(user.roles)
        ))

        conn.commit()

        return {
            "success": True,
            "message": "MUTX hisobingiz yaratildi",
            "user_id": cursor.lastrowid,
            "verified": False
        }

    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Bu telefon raqam avval ro'yxatdan o'tgan"
        )

    finally:
        conn.close()


@app.get("/users/{user_id}")
def get_user(user_id: int):
    conn = get_db()

    user = conn.execute("""
        SELECT id, full_name, phone, roles, verified, created_at
        FROM users
        WHERE id = ?
    """, (user_id,)).fetchone()

    conn.close()

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="Foydalanuvchi topilmadi"
        )

    return dict(user)