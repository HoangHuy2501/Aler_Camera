import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def database_url() -> str:
    url = env("DATABASE_URL")
    if not url:
        raise RuntimeError("Cần cấu hình DATABASE_URL.")
    return url
