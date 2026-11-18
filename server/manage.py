import argparse
import getpass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg

import imou_cloud
from pydantic import EmailStr, TypeAdapter

from config import database_url
from db import connect_pool
from security import PASSWORDS

parser = argparse.ArgumentParser()
commands = parser.add_subparsers(dest="command", required=True)
commands.add_parser("schema")
cloud = commands.add_parser("imou-authorize")
cloud.add_argument("--callback", required=True)
check = commands.add_parser("imou-check")
check.add_argument("camera_id", type=int)
check.add_argument("--minutes", type=int, choices=range(1, 1441), default=60, metavar="1–1440")
admin = commands.add_parser("create-admin")
admin.add_argument("--email", required=True)
admin.add_argument("--name", required=True)
args = parser.parse_args()

with psycopg.connect(database_url(), autocommit=True) as db:
    if args.command == "schema":
        db.execute(Path(__file__).with_name("schema.sql").read_text())
        print("Đã tạo schema PostgreSQL.")
    elif args.command == "imou-check":
        with connect_pool() as pool:
            with pool.connection() as camera_db:
                camera = camera_db.execute("SELECT * FROM cameras WHERE id=%s AND source='imou'",
                                           (args.camera_id,)).fetchone()
            if not camera:
                parser.error("Không tìm thấy camera Imou Cloud.")
            end = datetime.now(UTC).replace(microsecond=0)
            start = end - timedelta(minutes=args.minutes)
            try:
                events = imou_cloud.person_events(imou_cloud.access_token(pool), camera, start, end)
                for event, _, when in events:
                    has_image = "JPEG OK" if imou_cloud.event_image(event) else "chưa lấy được ảnh"
                    print(f"{when.astimezone(imou_cloud.ZONE).isoformat()} — phát hiện người — {has_image}")
                    break
                else:
                    print("Không tìm thấy sự kiện người trong khoảng giờ đã chọn.")
            except imou_cloud.ImouError as failure:
                raise SystemExit(str(failure)) from None
    elif args.command == "imou-authorize":
        code = getpass.getpass("Mã OAuth Imou: ").strip()
        if not code:
            parser.error("Thiếu mã OAuth.")
        try:
            imou_cloud.authorize(db, code, args.callback)
        except imou_cloud.ImouError as failure:
            raise SystemExit(str(failure)) from None
        print("Đã lưu quyền Imou Cloud.")
    else:
        email = TypeAdapter(EmailStr).validate_python(args.email).lower()
        name = args.name.strip()
        if not 1 <= len(name) <= 100:
            parser.error("Tên phải dài từ 1 đến 100 ký tự.")
        password = getpass.getpass("Mật khẩu quản trị: ")
        if not 10 <= len(password) <= 128:
            parser.error("Mật khẩu phải dài từ 10 đến 128 ký tự.")
        if getpass.getpass("Nhập lại mật khẩu: ") != password:
            parser.error("Mật khẩu nhập lại không khớp.")
        with db.transaction():
            result = db.execute(
                "INSERT INTO users(email,name,role,password_hash) VALUES (%s,%s,'admin',%s) "
                "ON CONFLICT(email) DO NOTHING RETURNING id",
                (email, name, PASSWORDS.hash(password)),
            ).fetchone()
            if result is None:
                parser.error("Email đã tồn tại.")
            db.execute("INSERT INTO schedules(user_id) VALUES (%s)", (result[0],))
        print("Đã tạo tài khoản quản trị.")
