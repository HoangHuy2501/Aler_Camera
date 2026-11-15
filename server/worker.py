import argparse
import json
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from hashlib import sha256
from queue import Empty, Full, Queue
from threading import Event, Thread
from time import monotonic
from uuid import uuid4

import paho.mqtt.client as mqtt
import psycopg

import onvif_source
from config import database_url, env
from db import connect_pool
from ingest import capture, ingest, mark_status

LOG = logging.getLogger("camera.worker")


def watch_onvif(pool, camera, stop, inspect=None):
    def on_event(kind, key, when, uri):
        fingerprint = sha256(repr((key, when.astimezone(UTC))).encode()).hexdigest()
        ingest(pool, camera, kind, fingerprint, when, lambda: capture(camera, snapshot_uri=uri))

    delay = 2
    while not stop.is_set():
        try:
            onvif_source.watch(camera, stop, lambda: mark_status(pool, camera, "connected"), on_event, inspect)
        except Exception as error:
            if not stop.is_set():
                LOG.warning("Camera %s: ONVIF lỗi (%s).", camera["id"], type(error).__name__)
                try:
                    mark_status(pool, camera, "error")
                except Exception:
                    LOG.warning("Không thể lưu trạng thái camera %s.", camera["id"])
        if stop.wait(delay):
            break
        delay = min(delay * 2, 30)


def event_time(value, fallback):
    try:
        if isinstance(value, (int, float)) and math.isfinite(value):
            candidate = datetime.fromtimestamp(value, UTC)
            if abs((fallback - candidate).total_seconds()) < 86400:
                return candidate
    except (ValueError, OverflowError, OSError):
        pass
    return fallback


def zones(value):
    return {zone for zone in value if isinstance(zone, str)} if isinstance(value, list) else set()


class Frigate:
    def __init__(self, pool):
        self.pool = pool
        self.prefix = env("FRIGATE_TOPIC", "frigate").strip("/")
        self.cameras = {}
        self.queue = Queue(maxsize=128)
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        if env("FRIGATE_MQTT_USER"):
            self.client.username_pw_set(env("FRIGATE_MQTT_USER"), env("FRIGATE_MQTT_PASSWORD"))
        if env("FRIGATE_MQTT_TLS").lower() == "true":
            self.client.tls_set()
        self.host = env("FRIGATE_MQTT_HOST")
        self.threads = ThreadPoolExecutor(max_workers=4) if self.host else None
        self.stop = Event()

    def start(self):
        if self.host:
            for _ in range(4):
                self.threads.submit(self.consume)
            self.client.connect_async(self.host, int(env("FRIGATE_MQTT_PORT", "1883")), 30)
            self.client.loop_start()

    def close(self):
        if self.host:
            self.client.disconnect()
            self.client.loop_stop()
            self.stop.set()
            self.threads.shutdown(wait=True, cancel_futures=True)

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            LOG.warning("Không thể kết nối MQTT Frigate.")
            return
        for suffix in ("available", "events", "stats", "+/motion"):
            client.subscribe(f"{self.prefix}/{suffix}")

    def on_disconnect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            self.offer(("offline", b"", False, datetime.now(UTC)))

    def offer(self, item):
        try:
            self.queue.put_nowait(item)
        except Full:
            LOG.warning("Hàng đợi MQTT đầy. Một sự kiện đã bị bỏ qua.")

    def on_message(self, client, userdata, message):
        if len(message.payload) <= 256_000:
            self.offer((message.topic.removeprefix(f"{self.prefix}/"), message.payload, message.retain, datetime.now(UTC)))

    def consume(self):
        while not self.stop.is_set():
            try:
                item = self.queue.get(timeout=0.5)
            except Empty:
                continue
            try:
                self.handle(*item)
            except Exception as error:
                LOG.warning("Không xử lý được bản tin Frigate (%s).", type(error).__name__)

    def handle(self, topic, payload, retained, now):
        if topic == "offline" or (topic == "available" and payload in {b"offline", b"stopped"}):
            for camera in self.cameras.values():
                mark_status(self.pool, camera, "error")
            return
        if topic == "stats":
            status = json.loads(payload).get("cameras", {})
            for name, camera in self.cameras.items():
                report = status.get(name, {})
                mark_status(self.pool, camera, "connected" if report.get("camera_fps", 0) > 0 else "error")
            return
        if retained:
            return
        if topic.endswith("/motion"):
            camera = self.cameras.get(topic.split("/")[0])
            if camera and payload == b"ON":
                mark_status(self.pool, camera, "connected")
                ingest(self.pool, camera, "motion", uuid4().hex, now, lambda: capture(camera))
            return
        if topic != "events":
            return
        event = json.loads(payload)
        after = event.get("after") or {}
        camera = self.cameras.get(after.get("camera"))
        event_id = after.get("id")
        if not camera or not isinstance(event_id, str) or not 0 < len(event_id) <= 100:
            return
        if after.get("label") != "person" or after.get("false_positive") is True:
            return
        mark_status(self.pool, camera, "connected")
        message_type = event.get("type")
        start = event_time(after.get("start_time"), now)
        if message_type in {"new", "end"} or after.get("has_snapshot"):
            ingest(self.pool, camera, "person", event_id, start, lambda: capture(camera, event_id))
        zone = camera["intrusion_zone"]
        current = zones(after.get("current_zones"))
        previous = zones((event.get("before") or {}).get("current_zones"))
        if zone and zone in current - previous:
            when = event_time(after.get("frame_time"), now)
            ingest(self.pool, camera, "intrusion", event_id, when, lambda: capture(camera, event_id))
        elif zone and (message_type == "end" or after.get("has_snapshot")) and zone in zones(after.get("entered_zones")):
            ingest(self.pool, camera, "intrusion", event_id, start, lambda: capture(camera, event_id),
                   existing_only=True)


def prune(pool):
    days = max(1, int(env("ALERT_RETENTION_DAYS", "30")))
    with pool.connection() as db:
        db.execute("DELETE FROM alerts WHERE occurred_at < now()-(%s * interval '1 day')", (days,))
        db.execute("DELETE FROM sessions WHERE expires_at<=now()")
        db.execute("DELETE FROM password_resets WHERE expires_at<=now()")
        db.execute("DELETE FROM auth_limits WHERE bucket<floor(extract(epoch FROM now())/900)-1")


def run(pool, lock):
    watchers = {}
    frigate = Frigate(pool)
    interval = Event()
    next_prune = 0
    frigate.start()
    try:
        while True:
            lock.execute("SELECT 1")
            with pool.connection() as db:
                cameras = db.execute("SELECT * FROM cameras WHERE active").fetchall()
            selected = {camera["id"]: camera for camera in cameras if camera["source"] == "onvif"}
            frigate.cameras = {camera["frigate_name"]: camera for camera in cameras if camera["source"] == "frigate"}
            for camera_id, (revision, stop, thread) in list(watchers.items()):
                current = selected.get(camera_id)
                if not current or current["revision"] != revision:
                    stop.set()
                if not thread.is_alive():
                    del watchers[camera_id]
            for camera_id, camera in selected.items():
                if camera_id not in watchers:
                    stop = Event()
                    thread = Thread(target=watch_onvif, args=(pool, camera, stop))
                    watchers[camera_id] = (camera["revision"], stop, thread)
                    thread.start()
            if monotonic() >= next_prune:
                prune(pool)
                next_prune = monotonic() + 3600
            interval.wait(3)
    finally:
        for _, stop, _ in watchers.values():
            stop.set()
        frigate.close()
        for _, _, thread in watchers.values():
            thread.join()


def diagnose(pool, camera_id):
    with pool.connection() as db:
        camera = db.execute("SELECT * FROM cameras WHERE id=%s AND source='onvif'", (camera_id,)).fetchone()
    if not camera:
        raise SystemExit("Không tìm thấy camera ONVIF.")
    stop = Event()
    try:
        onvif_source.watch(
            camera, stop, lambda: None,
            lambda kind, key, when, uri: print(
                f"{when.isoformat()} {kind}: {'JPEG OK' if capture(camera, snapshot_uri=uri) else 'chưa lấy được ảnh'}",
                flush=True,
            ),
            inspect=lambda topic, fields: print("ONVIF", topic, ", ".join(fields), flush=True),
        )
    except KeyboardInterrupt:
        stop.set()
    except Exception as error:
        raise SystemExit(f"Kiểm tra ONVIF thất bại ({type(error).__name__}).") from None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--diagnose", type=int, metavar="CAMERA_ID")
    args = parser.parse_args()
    with connect_pool() as pool:
        pool.wait(timeout=15)
        if args.diagnose is not None:
            diagnose(pool, args.diagnose)
        else:
            try:
                with psycopg.connect(database_url(), autocommit=True, connect_timeout=5) as lock:
                    if not lock.execute("SELECT pg_try_advisory_lock(840821)").fetchone()[0]:
                        raise SystemExit("Worker đang chạy ở một tiến trình khác.")
                    run(pool, lock)
            except KeyboardInterrupt:
                pass
