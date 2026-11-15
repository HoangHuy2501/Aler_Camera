import os
import sqlite3
from contextlib import asynccontextmanager, closing
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from pydantic import BaseModel, Field

LOCAL_ZONE = ZoneInfo("Asia/Ho_Chi_Minh")
DATABASE = Path(os.getenv("CAMERA_DB_PATH", Path(__file__).parent / "data" / "camera.db"))


def connect():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    return db


@asynccontextmanager
async def lifespan(app: FastAPI):
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect()) as db, db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS schedule (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                start TEXT NOT NULL,
                end TEXT NOT NULL
            );
            INSERT OR IGNORE INTO schedule VALUES (1, '22:00', '06:00');
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY,
                camera TEXT NOT NULL,
                kind TEXT NOT NULL,
                occurred_at TEXT NOT NULL
            );
        """)
    yield


app = FastAPI(title="Camera Alert API", lifespan=lifespan)


class Schedule(BaseModel):
    start: str = Field(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    end: str = Field(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")


class DemoEvent(BaseModel):
    kind: Literal["person", "motion", "intrusion"] = "person"
    test_time: str | None = Field(default=None, pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")


def within_schedule(occurred_at: datetime, schedule: sqlite3.Row) -> bool:
    current = occurred_at.astimezone(LOCAL_ZONE).time()
    start = time.fromisoformat(schedule["start"])
    end = time.fromisoformat(schedule["end"])
    if start == end:
        return True
    if start < end:
        return start <= current < end
    return current >= start or current < end


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/schedule", response_model=Schedule)
def get_schedule():
    with closing(connect()) as db:
        return dict(db.execute("SELECT start, end FROM schedule WHERE id = 1").fetchone())


@app.put("/schedule", response_model=Schedule)
def update_schedule(schedule: Schedule):
    with closing(connect()) as db, db:
        db.execute("UPDATE schedule SET start = ?, end = ? WHERE id = 1",
                   (schedule.start, schedule.end))
    return schedule


@app.get("/alerts")
def list_alerts():
    with closing(connect()) as db:
        rows = db.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT 50").fetchall()
        return [dict(row) for row in rows]


@app.post("/demo/events")
def create_demo_event(event: DemoEvent):
    occurred_at = datetime.now(LOCAL_ZONE)
    if event.test_time is not None:
        occurred_at = datetime.combine(occurred_at.date(), time.fromisoformat(event.test_time), LOCAL_ZONE)
    with closing(connect()) as db, db:
        schedule = db.execute("SELECT start, end FROM schedule WHERE id = 1").fetchone()
        if not within_schedule(occurred_at, schedule):
            return {"accepted": False}
        db.execute(
            "INSERT INTO alerts (camera, kind, occurred_at) VALUES (?, ?, ?)",
            ("IMOU mô phỏng", event.kind, occurred_at.astimezone(UTC).isoformat()),
        )
    return {"accepted": True}
