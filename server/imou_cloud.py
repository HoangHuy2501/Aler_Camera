import base64
import hashlib
import hmac
import logging
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

import requests

from config import env
from ingest import ZONE, fetch_jpeg, ingest, mark_status
from security import decrypt, encrypt

LOG = logging.getLogger(__name__)
PERSON = "detection.person.detected"
TIME_FORMAT = "%Y%m%dT%H%M%S"


class ImouError(RuntimeError):
    pass


def settings():
    center = env("IMOU_DATA_CENTER").strip().lower()
    access = env("IMOU_PROJECT_ACCESS_KEY")
    secret = env("IMOU_PROJECT_SECRET_KEY")
    if not re.fullmatch(r"[a-z0-9-]+", center) or not access or not secret:
        raise ImouError("Thiếu cấu hình dự án OAuth Imou.")
    return f"https://openapi-{center}.easy4ip.com", access, secret


def request(path, **kwargs):
    host, _, _ = settings()
    try:
        response = requests.post(host + path, timeout=(5, 12), allow_redirects=False, **kwargs)
        if not response.ok:
            raise ImouError(f"Imou trả về HTTP {response.status_code}.")
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError
        return data
    except (requests.RequestException, ValueError):
        raise ImouError("Không đọc được phản hồi từ Imou.") from None


def oauth(**fields):
    _, access, secret = settings()
    data = request("/openapi/oauthTokenV2", auth=(access, secret), data=fields)
    if not all(isinstance(data.get(key), str) and data[key] for key in ("access_token", "refresh_token")):
        raise ImouError("Imou chưa cấp token OAuth hợp lệ.")
    try:
        expires = int(data["expires_in"])
        if not 0 < expires <= 86_400:
            raise ValueError
    except (TypeError, ValueError, KeyError):
        raise ImouError("Thời hạn token OAuth không hợp lệ.") from None
    return (encrypt(data["access_token"]), encrypt(data["refresh_token"]),
            datetime.now(UTC) + timedelta(seconds=expires))


def authorize(db, code: str, callback_url: str):
    parsed = urlsplit(callback_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ImouError("Callback cần là URL HTTPS đã khai báo trong Imou.")
    with db.transaction():
        db.execute("SELECT pg_advisory_xact_lock(840822)")
        values = oauth(grant_type="authorization_code", code=code, redirect_uri=callback_url)
        db.execute(
            """INSERT INTO imou_oauth(id,access_token,refresh_token,expires_at) VALUES (1,%s,%s,%s)
               ON CONFLICT (id) DO UPDATE SET access_token=excluded.access_token,
               refresh_token=excluded.refresh_token,expires_at=excluded.expires_at""",
            values,
        )


def access_token(pool):
    with pool.connection() as db:
        row = db.execute("SELECT * FROM imou_oauth WHERE id=1 FOR UPDATE").fetchone()
        if not row:
            raise ImouError("Chưa cấp quyền Imou. Chạy manage.py imou-authorize.")
        if row["expires_at"] > datetime.now(UTC) + timedelta(seconds=60):
            return decrypt(row["access_token"])
        values = oauth(grant_type="refresh_token", refresh_token=decrypt(row["refresh_token"]))
        db.execute("UPDATE imou_oauth SET access_token=%s,refresh_token=%s,expires_at=%s WHERE id=1", values)
        return decrypt(values[0])


def search(token, camera, start, end, cursor):
    _, access, secret = settings()
    now = int(datetime.now(UTC).timestamp())
    nonce = str(uuid4())
    signing_key = hashlib.sha256(secret.encode()).hexdigest().encode()
    signed = hmac.digest(signing_key, f"time:{now},nonce:{nonce},appSecret:{secret}".encode(), "sha256")
    zone = ZoneInfo(env("IMOU_DEVICE_TIMEZONE", "Asia/Ho_Chi_Minh"))
    data = request("/openapi/v2/device.message.search", json={
        "id": str(uuid4()),
        "system": {"ver": "1.0", "appId": access, "time": now, "nonce": nonce,
                   "sign": base64.b64encode(signed).decode()},
        "params": {"token": token, "deviceId": camera["imou_device_id"],
                   "channelId": camera["imou_channel_id"], "labelType": "humanAlarm",
                   "beginTime": start.astimezone(zone).strftime(TIME_FORMAT),
                   "endTime": end.astimezone(zone).strftime(TIME_FORMAT), "nextAlarmId": cursor},
    })
    result = data.get("result") or {}
    if str(result.get("code")) != "0":
        code = str(result.get("code", "unknown"))
        safe_code = code if re.fullmatch(r"[A-Za-z0-9_-]{1,30}", code) else "unknown"
        raise ImouError(f"Imou từ chối truy vấn sự kiện ({safe_code}).")
    payload = result.get("data") or {}
    messages = payload.get("messages", [])
    if not isinstance(messages, list):
        raise ImouError("Danh sách sự kiện Imou không hợp lệ.")
    return messages, payload.get("nextAlarmId")


def person_events(token, camera, start, end):
    cursor = "-1"
    visited = set()
    for _ in range(20):
        messages, following = search(token, camera, start, end, cursor)
        for event in messages:
            if not isinstance(event, dict) or event.get("msgType") != PERSON:
                continue
            if event.get("deviceId") != camera["imou_device_id"]:
                continue
            channel = event.get("channelId")
            if channel is not None and str(channel) != camera["imou_channel_id"]:
                continue
            key = event.get("alarmId")
            try:
                when = datetime.fromtimestamp(int(event["time"]), UTC)
            except (KeyError, TypeError, ValueError, OverflowError, OSError):
                continue
            if isinstance(key, str) and 0 < len(key) <= 200 and start <= when <= end:
                yield event, key, when
        if following in (None, "", "-1", -1):
            return
        cursor = str(following)
        if cursor in visited:
            break
        visited.add(cursor)
    raise ImouError("Không thể hoàn tất phân trang lịch sử Imou.")


def event_image(event):
    urls = event.get("picUrlArray")
    candidates = urls[:3] if isinstance(urls, list) else []
    candidates.append(event.get("thumbUrl"))
    for url in candidates:
        if not isinstance(url, str):
            continue
        try:
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                continue
            image = fetch_jpeg(url)
            if image:
                return image
        except (ValueError, requests.RequestException):
            continue
    return None


def poll(pool, camera, stopped):
    try:
        seconds = min(600, max(60, int(env("IMOU_POLL_SECONDS", "300"))))
    except ValueError:
        LOG.warning("IMOU_POLL_SECONDS không hợp lệ. Dùng mặc định 300 giây.")
        seconds = 300
    while not stopped.is_set():
        try:
            now = datetime.now(UTC).replace(microsecond=0)
            with pool.connection() as db:
                row = db.execute(
                    "SELECT imou_cursor FROM cameras WHERE id=%s AND revision=%s AND active",
                    (camera["id"], camera["revision"]),
                ).fetchone()
            if not row:
                return
            last = row["imou_cursor"] or now - timedelta(minutes=10)
            last = max(last, now - timedelta(hours=24))
            start = last - timedelta(minutes=5)
            end = min(now, last + timedelta(minutes=30))
            for event, key, when in person_events(access_token(pool), camera, start, end):
                if stopped.is_set():
                    return
                ingest(pool, camera, "person", f"imou:{key}", when, lambda: event_image(event))
            with pool.connection() as db:
                db.execute("UPDATE cameras SET imou_cursor=%s WHERE id=%s AND revision=%s",
                           (end, camera["id"], camera["revision"]))
            mark_status(pool, camera, "connected")
        except Exception as failure:
            detail = str(failure) if isinstance(failure, ImouError) else type(failure).__name__
            LOG.warning("Camera %s: truy vấn Imou thất bại (%s).", camera["id"], detail)
            try:
                mark_status(pool, camera, "error")
            except Exception:
                LOG.warning("Không thể lưu trạng thái camera %s.", camera["id"])
        stopped.wait(seconds)
