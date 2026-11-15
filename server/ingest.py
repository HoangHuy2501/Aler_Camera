import logging
import subprocess
from datetime import datetime
from urllib.parse import quote, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import requests
from requests.auth import HTTPDigestAuth

from config import env
from security import decrypt

ZONE = ZoneInfo("Asia/Ho_Chi_Minh")
MAX_IMAGE = 2_000_000
LOG = logging.getLogger(__name__)

RECIPIENTS = """
    SELECT u.id FROM users u JOIN schedules s ON s.user_id=u.id
    WHERE u.active AND s.enabled AND CASE %s WHEN 'person' THEN s.person
          WHEN 'motion' THEN s.motion WHEN 'intrusion' THEN s.intrusion ELSE false END
      AND (u.role='admin' OR EXISTS (
           SELECT 1 FROM camera_access ca WHERE ca.user_id=u.id AND ca.camera_id=%s
      ))
      AND (s.start_time=s.end_time OR CASE WHEN s.start_time<s.end_time
           THEN (%s>=s.start_time AND %s<s.end_time)
           ELSE (%s>=s.start_time OR %s<s.end_time) END)
"""


def camera_endpoint(raw: str, host: str) -> str:
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Camera trả về địa chỉ HTTP không hợp lệ.")
    authority = f"{host}:{parsed.port}" if parsed.port else host
    return urlunsplit((parsed.scheme, authority, parsed.path, parsed.query, ""))


def jpeg(data: bytes) -> bytes | None:
    return data if 4 <= len(data) <= MAX_IMAGE and data.startswith(b"\xff\xd8") and data.endswith(b"\xff\xd9") else None


def fetch_jpeg(url: str, auth=None) -> bytes | None:
    with requests.Session() as session:
        session.trust_env = False
        with session.get(url, auth=auth, timeout=(3, 5), stream=True, allow_redirects=False) as response:
            if response.status_code != 200:
                return None
            data = bytearray()
            for chunk in response.iter_content(65536):
                data.extend(chunk)
                if len(data) > MAX_IMAGE:
                    return None
            return jpeg(bytes(data))


def capture(camera: dict, event_id: str | None = None, snapshot_uri: str | None = None) -> bytes | None:
    try:
        if camera["source"] == "frigate" and env("FRIGATE_URL"):
            base = env("FRIGATE_URL").rstrip("/")
            if event_id:
                path = f"events/{quote(event_id, safe='')}/snapshot.jpg"
            else:
                path = f"{quote(camera['frigate_name'], safe='')}/latest.jpg?h=720"
            image = fetch_jpeg(f"{base}/api/{path}")
            if image:
                return image
    except (requests.RequestException, ValueError):
        pass
    try:
        if snapshot_uri:
            url = camera_endpoint(snapshot_uri, camera["host"])
            auth = HTTPDigestAuth(camera["username"], decrypt(camera["secret"])) if camera["username"] else None
            image = fetch_jpeg(url, auth)
            if image:
                return image
    except (requests.RequestException, ValueError):
        pass
    if camera["rtsp_secret"]:
        try:
            result = subprocess.run(
                [env("FFMPEG_BIN", "ffmpeg"), "-nostdin", "-loglevel", "error", "-rtsp_transport", "tcp",
                 "-protocol_whitelist", "rtsp,rtsps,tcp,tls,rtp,udp,crypto",
                 "-i", decrypt(camera["rtsp_secret"]), "-frames:v", "1", "-vf", "scale=1280:-2",
                 "-f", "image2pipe", "-c:v", "mjpeg", "pipe:1"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10, check=False,
            )
            if result.returncode == 0:
                return jpeg(result.stdout)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return None


def mark_status(pool, camera: dict, status: str):
    with pool.connection() as db:
        db.execute(
            """UPDATE cameras SET status=%s,status_at=now()
               WHERE id=%s AND revision=%s AND active AND
                 (status<>%s OR status_at IS NULL OR status_at<now()-interval '30 seconds')""",
            (status, camera["id"], camera["revision"], status),
        )


def ingest(pool, camera: dict, kind: str, key: str, occurred_at: datetime, image_fn, *, existing_only=False):
    camera_id = camera["id"]
    minute = occurred_at.astimezone(ZONE).time()
    params = (kind, camera_id, minute, minute, minute, minute)
    with pool.connection() as db:
        existing = db.execute(
            "SELECT id,snapshot IS NOT NULL AS has_snapshot FROM alerts WHERE camera_id=%s AND kind=%s AND event_key=%s",
            (camera_id, kind, key),
        ).fetchone()
        if existing and existing["has_snapshot"]:
            return
        if not existing and (existing_only or not db.execute(RECIPIENTS + " LIMIT 1", params).fetchone()):
            return
    image = image_fn()
    if image is None:
        LOG.info("Camera %s: sự kiện %s chưa có ảnh.", camera_id, kind)
    with pool.connection() as db:
        valid = db.execute(
            "SELECT 1 FROM cameras WHERE id=%s AND revision=%s AND active FOR SHARE",
            (camera_id, camera["revision"]),
        ).fetchone()
        if not valid:
            return
        if existing:
            if image:
                db.execute("UPDATE alerts SET snapshot=%s WHERE id=%s AND snapshot IS NULL", (image, existing["id"]))
            return
        recipients = db.execute(RECIPIENTS, params).fetchall()
        if not recipients:
            return
        row = db.execute(
            """INSERT INTO alerts(camera_id,kind,event_key,occurred_at,snapshot)
               VALUES (%s,%s,%s,%s,%s) ON CONFLICT(camera_id,kind,event_key)
               DO UPDATE SET snapshot=COALESCE(alerts.snapshot,excluded.snapshot) RETURNING id""",
            (camera_id, kind, key, occurred_at, image),
        ).fetchone()
        db.execute(
            """INSERT INTO alert_recipients(user_id,alert_id)
               SELECT unnest(%s::bigint[]),%s ON CONFLICT DO NOTHING""",
            ([user["id"] for user in recipients], row["id"]),
        )
