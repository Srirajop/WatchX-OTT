import os
import re
import secrets
import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta
import jwt
from passlib.context import CryptContext
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel, EmailStr
from database import get_connection

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

JWT_SECRET = os.getenv("JWT_SECRET", "super_secret_jwt_key_ewandz_2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

# Pydantic Models
class SignupRequest(BaseModel):
    email: EmailStr
    password: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

class VerifyEmailRequest(BaseModel):
    token: str

# Helper Functions
def get_password_hash(password):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)
    return encoded_jwt

def send_reset_email(to_email: str, token: str):
    try:
        reset_url = f"{os.getenv('FRONTEND_URL', 'http://localhost:5173')}/?reset_token={token}"
        msg = EmailMessage()
        msg.set_content(f"Hello,\n\nYou requested a password reset. Click the link below to reset your password:\n\n{reset_url}\n\nIf you did not request this, please ignore this email.")
        msg['Subject'] = 'SubtitleAI Password Reset'
        msg['From'] = SMTP_USER
        msg['To'] = to_email

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"[AUTH] Reset email sent to {to_email}")
    except Exception as e:
        print(f"[AUTH ERROR] Failed to send email: {e}")

def send_verification_email(to_email: str, token: str):
    try:
        verify_url = f"{os.getenv('FRONTEND_URL', 'http://localhost:5173')}/?verify_token={token}"
        msg = EmailMessage()
        msg.set_content(f"Welcome to SubtitleAI!\n\nPlease verify your email address by clicking the link below:\n\n{verify_url}\n\nIf you did not sign up, please ignore this email.")
        msg['Subject'] = 'SubtitleAI Email Verification'
        msg['From'] = SMTP_USER
        msg['To'] = to_email

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"[AUTH] Verification email sent to {to_email}")
    except Exception as e:
        print(f"[AUTH ERROR] Failed to send verification email: {e}")

# Endpoints
@router.post("/signup")
def signup(req: SignupRequest):
    if not req.email.endswith("@ewandzdigital.com"):
        raise HTTPException(status_code=403, detail="Only @ewandzdigital.com emails are allowed.")
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    if not re.search(r"[A-Z]", req.password):
        raise HTTPException(status_code=400, detail="Password must contain at least one uppercase letter.")
    if not re.search(r"[a-z]", req.password):
        raise HTTPException(status_code=400, detail="Password must contain at least one lowercase letter.")
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", req.password):
        raise HTTPException(status_code=400, detail="Password must contain at least one special character.")
    
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id FROM users WHERE email = %s", (req.email,))
    if cursor.fetchone():
        cursor.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Email already registered.")
    
    hashed_password = get_password_hash(req.password)
    verification_token = secrets.token_urlsafe(32)
    
    cursor.execute(
        "INSERT INTO users (email, password_hash, is_verified, verification_token) VALUES (%s, %s, False, %s)",
        (req.email, hashed_password, verification_token)
    )
    conn.commit()
    cursor.close()
    conn.close()
    
    send_verification_email(req.email, verification_token)
    return {"message": "User created successfully. Please check your email to verify your account."}

@router.post("/login")
def login(req: LoginRequest):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE email = %s", (req.email,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()

    if not user or not verify_password(req.password, user['password_hash']):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    
    if not user.get('is_verified'):
        raise HTTPException(status_code=403, detail="Please verify your email address to log in. Check your inbox.")
    
    access_token = create_access_token(data={"sub": user['email']})
    return {"access_token": access_token, "token_type": "bearer", "email": user['email']}

@router.post("/forgot-password")
def forgot_password(req: ForgotPasswordRequest):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id FROM users WHERE email = %s", (req.email,))
    user = cursor.fetchone()
    
    if not user:
        cursor.close()
        conn.close()
        return {"message": "If that email exists, a reset link has been sent."}
    
    token = secrets.token_urlsafe(32)
    expires = datetime.now() + timedelta(hours=1)
    
    cursor.execute(
        "UPDATE users SET reset_token = %s, reset_token_expires = %s WHERE id = %s",
        (token, expires, user['id'])
    )
    conn.commit()
    cursor.close()
    conn.close()
    
    send_reset_email(req.email, token)
    return {"message": "If that email exists, a reset link has been sent."}

@router.post("/reset-password")
def reset_password(req: ResetPasswordRequest):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, reset_token_expires FROM users WHERE reset_token = %s", (req.token,))
    user = cursor.fetchone()
    
    if not user:
        cursor.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid or expired reset token.")
    
    if user['reset_token_expires'] < datetime.now():
        cursor.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Reset token has expired.")
    
    if len(req.new_password) < 6:
        cursor.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
    
    hashed_password = get_password_hash(req.new_password)
    cursor.execute(
        "UPDATE users SET password_hash = %s, reset_token = NULL, reset_token_expires = NULL WHERE id = %s",
        (hashed_password, user['id'])
    )
    conn.commit()
    cursor.close()
    conn.close()
    
    return {"message": "Password has been reset successfully."}

@router.post("/verify-email")
def verify_email(req: VerifyEmailRequest):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id FROM users WHERE verification_token = %s", (req.token,))
    user = cursor.fetchone()
    
    if not user:
        cursor.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid or expired verification token.")
    
    cursor.execute(
        "UPDATE users SET is_verified = True, verification_token = NULL WHERE id = %s",
        (user['id'],)
    )
    conn.commit()
    cursor.close()
    conn.close()
    
    return {"message": "Email verified successfully."}

def get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return email
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
