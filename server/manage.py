import argparse
import getpass
from pathlib import Path

import psycopg
from pydantic import EmailStr, TypeAdapter

from config import database_url
from security import PASSWORDS

parser = argparse.ArgumentParser()
commands = parser.add_subparsers(dest="command", required=True)
commands.add_parser("schema")
admin = commands.add_parser("create-admin")
admin.add_argument("--email", required=True)
admin.add_argument("--name", required=True)
args = parser.parse_args()

with psycopg.connect(database_url(), autocommit=True) as db:
    if args.command == "schema":
        db.execute(Path(__file__).with_name("schema.sql").read_text())
        print("Đã tạo schema PostgreSQL.")
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
