from datetime import time
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, EmailStr, Field, model_validator

from auth import NewPassword, admin_user, current_user, db_pool, replace_password, write_header
from security import PASSWORDS, encrypt

router = APIRouter()
admin = APIRouter(prefix="/admin", dependencies=[Depends(admin_user)])
WRITE = [Depends(write_header)]
CAMERA_FIELDS = """id,name,source,host,port,username,frigate_name,intrusion_zone,imou_device_id,imou_channel_id,
                   active,status,status_at,(secret IS NOT NULL) AS has_password,
                   (rtsp_secret IS NOT NULL) AS has_rtsp"""
USER_FIELDS = "id,email,name,role,active,created_at"
ACCESS = """(u.role='admin' OR EXISTS (
    SELECT 1 FROM camera_access ca WHERE ca.user_id=u.id AND ca.camera_id=c.id
))"""


class Schedule(BaseModel):
    start_time: time
    end_time: time
    enabled: bool = True
    person: bool = True
    motion: bool = True
    intrusion: bool = True

    @model_validator(mode="after")
    def whole_minutes(self):
        for value in (self.start_time, self.end_time):
            if value.tzinfo or value.second or value.microsecond:
                raise ValueError("Giờ phải có định dạng HH:MM.")
        return self


class NewUser(NewPassword):
    email: EmailStr
    name: str = Field(min_length=1, max_length=100, pattern=r"\S")


class UserAccess(BaseModel):
    active: bool
    camera_ids: list[int] = Field(max_length=20)


class Camera(BaseModel):
    name: str = Field(min_length=1, max_length=100, pattern=r"\S")
    source: Literal["onvif", "frigate", "imou"]
    host: str | None = Field(default=None, max_length=253, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9.-]*$")
    port: int = Field(default=80, ge=1, le=65535)
    username: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, max_length=256)
    rtsp_url: str | None = Field(default=None, max_length=2048)
    frigate_name: str | None = Field(default=None, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    intrusion_zone: str | None = Field(default=None, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    imou_device_id: str | None = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    imou_channel_id: str | None = Field(default=None, pattern=r"^[0-9]{1,4}$")
    active: bool = True

    @model_validator(mode="after")
    def validate_source(self):
        if self.source == "onvif" and (not self.host or self.frigate_name or self.intrusion_zone):
            raise ValueError("ONVIF cần địa chỉ camera.")
        if self.source == "frigate" and (not self.frigate_name or self.host or self.username or self.password):
            raise ValueError("Frigate cần tên camera trong Frigate.")
        if self.source == "imou":
            if not self.imou_device_id or self.imou_channel_id is None:
                raise ValueError("Imou Cloud cần số serial và kênh camera.")
            if any(value is not None for value in (self.host, self.username, self.password, self.rtsp_url,
                                                    self.frigate_name, self.intrusion_zone)):
                raise ValueError("Thông tin kết nối không phù hợp với Imou Cloud.")
        elif self.imou_device_id is not None or self.imou_channel_id is not None:
            raise ValueError("Số serial và kênh chỉ dùng cho Imou Cloud.")
        if self.rtsp_url:
            parsed = urlsplit(self.rtsp_url)
            if parsed.scheme not in {"rtsp", "rtsps"} or not parsed.hostname or any(ch.isspace() for ch in self.rtsp_url):
                raise ValueError("Địa chỉ luồng phải bắt đầu bằng rtsp:// hoặc rtsps://.")
            if parsed.port is not None and parsed.port < 1:
                raise ValueError("Cổng RTSP không hợp lệ.")
        return self


@router.get("/schedule", response_model=Schedule)
def get_schedule(request: Request, user=Depends(current_user)):
    with db_pool(request).connection() as db:
        return db.execute("SELECT * FROM schedules WHERE user_id=%s", (user["id"],)).fetchone()


@router.put("/schedule", response_model=Schedule, dependencies=WRITE)
def save_schedule(body: Schedule, request: Request, user=Depends(current_user)):
    with db_pool(request).connection() as db:
        db.execute(
            """UPDATE schedules SET start_time=%s,end_time=%s,enabled=%s,person=%s,motion=%s,intrusion=%s
               WHERE user_id=%s""",
            (body.start_time, body.end_time, body.enabled, body.person, body.motion, body.intrusion, user["id"]),
        )
    return body


@router.get("/cameras")
def cameras(request: Request, user=Depends(current_user)):
    with db_pool(request).connection() as db:
        return db.execute(
            f"""SELECT c.id,c.name,c.source,c.active,c.status,c.status_at
                FROM cameras c CROSS JOIN users u WHERE u.id=%s AND {ACCESS} ORDER BY c.name,c.id""",
            (user["id"],),
        ).fetchall()


@router.get("/alerts")
def alerts(request: Request, camera_id: int | None = None,
           kind: Literal["person", "motion", "intrusion"] | None = None, user=Depends(current_user)):
    with db_pool(request).connection() as db:
        return db.execute(
            f"""SELECT a.id,a.camera_id,c.name AS camera,a.kind,a.occurred_at,
                       a.snapshot IS NOT NULL AS has_snapshot
                FROM alert_recipients r JOIN alerts a ON a.id=r.alert_id
                JOIN cameras c ON c.id=a.camera_id JOIN users u ON u.id=r.user_id
                WHERE u.id=%s AND {ACCESS}
                  AND (%s::bigint IS NULL OR a.camera_id=%s) AND (%s::text IS NULL OR a.kind=%s)
                ORDER BY a.id DESC LIMIT 100""",
            (user["id"], camera_id, camera_id, kind, kind),
        ).fetchall()


@router.get("/alerts/{alert_id}/snapshot")
def snapshot(alert_id: int, request: Request, user=Depends(current_user)):
    with db_pool(request).connection() as db:
        record = db.execute(
            f"""SELECT a.snapshot FROM alert_recipients r JOIN alerts a ON r.alert_id=a.id
                JOIN cameras c ON c.id=a.camera_id JOIN users u ON u.id=r.user_id
                WHERE u.id=%s AND a.id=%s AND {ACCESS}""",
            (user["id"], alert_id),
        ).fetchone()
    if not record or record["snapshot"] is None:
        raise HTTPException(404, "Không tìm thấy ảnh.")
    return Response(record["snapshot"], media_type="image/jpeg")


@admin.get("/users")
def list_users(request: Request):
    with db_pool(request).connection() as db:
        return db.execute(
            f"""SELECT {USER_FIELDS}, ARRAY(SELECT camera_id FROM camera_access
                WHERE user_id=users.id ORDER BY camera_id) AS camera_ids
                FROM users WHERE role='user' ORDER BY id DESC"""
        ).fetchall()


@admin.post("/users", status_code=201, dependencies=WRITE)
def create_user(body: NewUser, request: Request):
    encoded = PASSWORDS.hash(body.password)
    with db_pool(request).connection() as db:
        row = db.execute(
            f"""INSERT INTO users(email,name,role,password_hash) VALUES (%s,%s,'user',%s)
                ON CONFLICT(email) DO NOTHING RETURNING {USER_FIELDS}""",
            (body.email.lower(), body.name.strip(), encoded),
        ).fetchone()
        if not row:
            raise HTTPException(409, "Email đã tồn tại.")
        db.execute("INSERT INTO schedules(user_id) VALUES (%s)", (row["id"],))
        return {**row, "camera_ids": []}


@admin.put("/users/{user_id}/access", dependencies=WRITE)
def user_access(user_id: int, body: UserAccess, request: Request):
    selected = sorted(set(body.camera_ids))
    with db_pool(request).connection() as db:
        user = db.execute("SELECT id FROM users WHERE id=%s AND role='user' FOR UPDATE", (user_id,)).fetchone()
        if not user:
            raise HTTPException(404, "Không tìm thấy người dùng.")
        cameras = db.execute("SELECT id FROM cameras WHERE id=ANY(%s::bigint[]) ORDER BY id FOR KEY SHARE", (selected,)).fetchall()
        if len(cameras) != len(selected):
            raise HTTPException(400, "Danh sách có camera không tồn tại.")
        db.execute("UPDATE users SET active=%s WHERE id=%s", (body.active, user_id))
        db.execute("DELETE FROM camera_access WHERE user_id=%s", (user_id,))
        db.execute(
            "INSERT INTO camera_access(user_id,camera_id) SELECT %s, unnest(%s::bigint[])",
            (user_id, selected),
        )
        if not body.active:
            db.execute("DELETE FROM sessions WHERE user_id=%s", (user_id,))
            db.execute("DELETE FROM password_resets WHERE user_id=%s", (user_id,))
    return {"ok": True}


@admin.post("/users/{user_id}/password", dependencies=WRITE)
def set_password(user_id: int, body: NewPassword, request: Request):
    hashed = PASSWORDS.hash(body.password)
    with db_pool(request).connection() as db:
        user = db.execute("SELECT id FROM users WHERE id=%s AND role='user' FOR UPDATE", (user_id,)).fetchone()
        if not user:
            raise HTTPException(404, "Không tìm thấy người dùng.")
        replace_password(db, user_id, hashed)
    return {"ok": True}


@admin.get("/cameras")
def list_camera_settings(request: Request):
    with db_pool(request).connection() as db:
        return db.execute(f"SELECT {CAMERA_FIELDS} FROM cameras ORDER BY id").fetchall()


def save_camera(body: Camera, request: Request, camera_id: int | None = None):
    password = encrypt(body.password)
    rtsp = encrypt(body.rtsp_url)
    with db_pool(request).connection() as db:
        # Serialize camera writes so concurrent creates cannot bypass the limit.
        db.execute("SELECT pg_advisory_xact_lock(840820)")
        record = None
        if camera_id is None:
            count = db.execute("SELECT count(*) AS count FROM cameras").fetchone()
            if count["count"] >= 20:
                raise HTTPException(409, "Đã đạt giới hạn 20 camera.")
        else:
            record = db.execute("SELECT * FROM cameras WHERE id=%s FOR UPDATE", (camera_id,)).fetchone()
            if record is None:
                raise HTTPException(404, "Không tìm thấy camera.")
        if record and record["source"] == body.source:
            if body.password is None:
                password = record["secret"]
            if body.rtsp_url is None:
                rtsp = record["rtsp_secret"]
        values = (body.name.strip(), body.source, body.host, body.port, body.username, password,
                  rtsp, body.frigate_name, body.intrusion_zone, body.imou_device_id, body.imou_channel_id, body.active)
        try:
            if camera_id is None:
                return db.execute(
                    f"""INSERT INTO cameras(name,source,host,port,username,secret,rtsp_secret,
                               frigate_name,intrusion_zone,imou_device_id,imou_channel_id,active)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING {CAMERA_FIELDS}""", values,
                ).fetchone()
            return db.execute(
                f"""UPDATE cameras SET name=%s,source=%s,host=%s,port=%s,username=%s,secret=%s,
                           rtsp_secret=%s,frigate_name=%s,intrusion_zone=%s,imou_device_id=%s,imou_channel_id=%s,active=%s,
                           imou_cursor=NULL,status='pending',status_at=NULL,revision=revision+1
                    WHERE id=%s RETURNING {CAMERA_FIELDS}""", (*values, camera_id),
            ).fetchone()
        except UniqueViolation:
            raise HTTPException(409, "Tên Frigate hoặc kênh Imou Cloud đã được sử dụng.") from None


@admin.post("/cameras", status_code=201, dependencies=WRITE)
def create_camera(body: Camera, request: Request):
    return save_camera(body, request)


@admin.put("/cameras/{camera_id}", dependencies=WRITE)
def edit_camera(camera_id: int, body: Camera, request: Request):
    return save_camera(body, request, camera_id)


@admin.delete("/cameras/{camera_id}", status_code=204, dependencies=WRITE)
def delete_camera(camera_id: int, request: Request):
    with db_pool(request).connection() as db:
        row = db.execute("DELETE FROM cameras WHERE id=%s RETURNING id", (camera_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Không tìm thấy camera.")
    return Response(status_code=204)
