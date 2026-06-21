"""
auth_server.py
--------------
Standalone FastAPI auth service using SQLite.
Run alongside your main RAG FastAPI app.

Usage:
    pip install fastapi uvicorn python-jose[cryptography] passlib[bcrypt] python-multipart
    uvicorn auth_server:app --port 8001 --reload
"""

import sqlite3
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from jose import JWTError, jwt
import bcrypt

# ── Config ───────────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "change-me-in-production-please-use-env-var")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours
DB_PATH = os.getenv("AUTH_DB_PATH", "data/auth.db")

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="RAG Auth Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# ── Database ──────────────────────────────────────────────────────────────────
def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            email       TEXT    UNIQUE NOT NULL,
            username    TEXT    UNIQUE NOT NULL,
            hashed_password TEXT NOT NULL,
            is_active   INTEGER DEFAULT 1,
            created_at  TEXT    DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS upload_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            filename    TEXT    NOT NULL,
            chunks      INTEGER DEFAULT 0,
            uploaded_at TEXT    DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.commit()
    conn.close()


init_db()

# ── Schemas ───────────────────────────────────────────────────────────────────
class UserCreate(BaseModel):
    email: str
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    username: str
    is_active: bool
    created_at: str


class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserOut


class UploadLogEntry(BaseModel):
    filename: str
    chunks: int


# ── Helpers ───────────────────────────────────────────────────────────────────
def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_user_by_email(email: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_username(username: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return dict(row) if row else None


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = get_user_by_username(username)
    if user is None:
        raise credentials_exception
    return user


# ── Routes ────────────────────────────────────────────────────────────────────
@app.post("/auth/register", response_model=UserOut, status_code=201)
def register(payload: UserCreate):
    if get_user_by_email(payload.email):
        raise HTTPException(status_code=400, detail="Email already registered.")
    if get_user_by_username(payload.username):
        raise HTTPException(status_code=400, detail="Username already taken.")
    if len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    hashed = hash_password(payload.password)
    conn = get_db()
    conn.execute(
        "INSERT INTO users (email, username, hashed_password) VALUES (?, ?, ?)",
        (payload.email, payload.username, hashed),
    )
    conn.commit()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (payload.username,)).fetchone()
    conn.close()
    return dict(user)


@app.post("/auth/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    # Accept email or username in the username field
    user = get_user_by_username(form_data.username) or get_user_by_email(form_data.username)
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Account is disabled.")

    token = create_access_token(
        data={"sub": user["username"]},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {"access_token": token, "token_type": "bearer", "user": user}


@app.get("/auth/me", response_model=UserOut)
def me(current_user=Depends(get_current_user)):
    return current_user


@app.post("/auth/log-upload")
def log_upload(entry: UploadLogEntry, current_user=Depends(get_current_user)):
    conn = get_db()
    conn.execute(
        "INSERT INTO upload_log (user_id, filename, chunks) VALUES (?, ?, ?)",
        (current_user["id"], entry.filename, entry.chunks),
    )
    conn.commit()
    conn.close()
    return {"status": "logged"}


@app.get("/auth/my-uploads")
def my_uploads(current_user=Depends(get_current_user)):
    conn = get_db()
    rows = conn.execute(
        "SELECT filename, chunks, uploaded_at FROM upload_log WHERE user_id = ? ORDER BY uploaded_at DESC",
        (current_user["id"],),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/")
def health():
    return {"status": "online", "service": "RAG Auth"}

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()