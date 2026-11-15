import logging
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field

from config import env
from security import PASSWORDS, digest, password_matches, token

router = APIRouter()
COOKIE = "camera_session"
SESSION_SECONDS = 8 * 3600
DUMMY_HASH = PASSWORDS.hash("unused-account-placeholder")
LOGGER = logging.getLogger(__name__)


class Login(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class EmailInput(BaseModel):
    email: EmailStr


class NewPassword(BaseModel):
    password: str = Field(min_length=10, max_length=128)


class Reset(NewPassword):
    token: str = Field(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]+$")


def db_pool(request: Request):
    return request.app.state.pool


def write_header(x_camera_request: str = Header(default="")):
    if x_camera_request != "1":
        raise HTTPException(403, "Yêu cầu không hợp lệ.")


def current_user(request: Request, camera_session: str | None = Cookie(default=None)):
    if not camera_session or len(camera_session) != 43:
        raise HTTPException(401, "Vui lòng đăng nhập.")
    with db_pool(request).connection() as db:
        user = db.execute(
            """SELECT u.id,u.email,u.name,u.role FROM sessions s JOIN users u ON u.id=s.user_id
               WHERE s.token_hash=%s AND s.expires_at>now() AND u.active""",
            (digest(camera_session),),
        ).fetchone()
    if user is None:
        raise HTTPException(401, "Phiên đăng nhập đã hết hạn.")
    return user


def admin_user(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Chỉ quản trị viên có quyền thực hiện.")
    return user


def check_rate(pool, action: str, identity: str, maximum: int):
    with pool.connection() as db:
        row = db.execute(
            """INSERT INTO auth_limits(action,identity,bucket,attempts)
               VALUES (%s,%s,floor(extract(epoch FROM now())/900),1)
               ON CONFLICT (action,identity) DO UPDATE
               SET attempts=CASE WHEN auth_limits.bucket=excluded.bucket
                                 THEN auth_limits.attempts+1 ELSE 1 END,
                   bucket=excluded.bucket
               RETURNING attempts""",
            (action, digest(identity).hex()),
        ).fetchone()
    if row["attempts"] > maximum:
        raise HTTPException(429, "Bạn đã thử quá nhiều lần. Vui lòng thử lại sau.")


@router.post("/auth/login", dependencies=[Depends(write_header)])
def login(body: Login, request: Request, response: Response):
    email = body.email.lower()
    pool = db_pool(request)
    check_rate(pool, "login", email, 10)
    with pool.connection() as db:
        user = db.execute(
            "SELECT id,email,name,role,password_hash,active FROM users WHERE email=%s", (email,)
        ).fetchone()
        valid = password_matches(user["password_hash"] if user else DUMMY_HASH, body.password)
        if not user or not user["active"] or not valid:
            raise HTTPException(401, "Email hoặc mật khẩu không đúng.")
        raw = token()
        row = db.execute(
            """INSERT INTO sessions(token_hash,user_id,expires_at)
               SELECT %s,id,now()+interval '8 hours' FROM users
               WHERE id=%s AND active AND password_hash=%s
               FOR UPDATE RETURNING user_id""",
            (digest(raw), user["id"], user["password_hash"]),
        ).fetchone()
        if row is None:
            raise HTTPException(401, "Vui lòng đăng nhập lại.")
        db.execute("DELETE FROM auth_limits WHERE action='login' AND identity=%s", (digest(email).hex(),))
    response.set_cookie(COOKIE, raw, max_age=SESSION_SECONDS, httponly=True,
                        secure=env("COOKIE_SECURE").lower() == "true", samesite="lax")
    return {key: user[key] for key in ("id", "email", "name", "role")}


@router.post("/auth/logout", dependencies=[Depends(write_header)])
def logout(request: Request, response: Response, camera_session: str | None = Cookie(default=None)):
    if camera_session and len(camera_session) == 43:
        with db_pool(request).connection() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=%s", (digest(camera_session),))
    response.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/auth/me")
def me(user=Depends(current_user)):
    return user


def send_reset(email: str, raw: str):
    message = EmailMessage()
    link = f"{env('APP_URL', 'http://127.0.0.1:3000').rstrip('/')}/dat-lai-mat-khau#{urlencode({'token': raw})}"
    message["Subject"] = "Đặt lại mật khẩu cảnh báo camera"
    message["From"] = env("SMTP_FROM")
    message["To"] = email
    message.set_content(f"Mở liên kết để đặt lại mật khẩu. Liên kết có hiệu lực trong 30 phút.\n\n{link}")
    mode = env("SMTP_MODE", "starttls")
    try:
        context = ssl.create_default_context()
        host, port = env("SMTP_HOST"), int(env("SMTP_PORT", "587"))
        client = smtplib.SMTP_SSL(host, port, timeout=10, context=context) if mode == "ssl" else smtplib.SMTP(host, port, timeout=10)
        with client:
            if mode == "starttls":
                client.starttls(context=context)
            if env("SMTP_USER"):
                client.login(env("SMTP_USER"), env("SMTP_PASSWORD"))
            client.send_message(message)
    except (OSError, ValueError, smtplib.SMTPException):
        LOGGER.warning("Gửi email đặt lại mật khẩu thất bại. Kiểm tra cấu hình SMTP.")


@router.post("/auth/forgot", dependencies=[Depends(write_header)])
def forgot(body: EmailInput, request: Request, tasks: BackgroundTasks):
    if not env("SMTP_HOST") or not env("SMTP_FROM"):
        raise HTTPException(503, "Email khôi phục chưa được cấu hình. Vui lòng liên hệ quản trị viên.")
    email = body.email.lower()
    pool = db_pool(request)
    check_rate(pool, "forgot", email, 3)
    with pool.connection() as db:
        user = db.execute("SELECT id FROM users WHERE email=%s AND active FOR UPDATE", (email,)).fetchone()
        if user:
            raw = token()
            db.execute(
                "INSERT INTO password_resets(token_hash,user_id,expires_at) VALUES (%s,%s,now()+interval '30 minutes')",
                (digest(raw), user["id"]),
            )
            tasks.add_task(send_reset, email, raw)
    return {"ok": True}


def replace_password(db, user_id: int, password_hash: str):
    db.execute("UPDATE users SET password_hash=%s WHERE id=%s", (password_hash, user_id))
    db.execute("DELETE FROM sessions WHERE user_id=%s", (user_id,))
    db.execute("DELETE FROM password_resets WHERE user_id=%s", (user_id,))


@router.post("/auth/reset", dependencies=[Depends(write_header)])
def reset(body: Reset, request: Request):
    hashed = digest(body.token)
    with db_pool(request).connection() as db:
        user = db.execute(
            """SELECT u.id FROM users u JOIN password_resets p ON p.user_id=u.id
               WHERE p.token_hash=%s AND p.expires_at>now() AND u.active FOR UPDATE OF u""",
            (hashed,),
        ).fetchone()
        valid = user and db.execute(
            "SELECT 1 FROM password_resets WHERE token_hash=%s AND expires_at>now()", (hashed,)
        ).fetchone()
        if not valid:
            raise HTTPException(400, "Liên kết không hợp lệ hoặc đã hết hạn.")
        replace_password(db, user["id"], PASSWORDS.hash(body.password))
    return {"ok": True}
