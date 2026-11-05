import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class LoginConfig:
    site_url: str
    method: str
    email: str | None
    password: str | None
    headless: bool
    qr_screenshot_path: str


def load_login_config(require_credentials: bool = True) -> LoginConfig:
    site_url = os.environ.get("SITE_URL")
    if not site_url:
        raise RuntimeError("環境変数 SITE_URL が設定されていません")

    method = os.environ.get("LOGIN_METHOD", "email").lower()
    if method not in ("email", "qr"):
        raise RuntimeError(f"LOGIN_METHOD は 'email' か 'qr' を指定してください (got: {method!r})")

    email = os.environ.get("LOGIN_EMAIL")
    password = os.environ.get("LOGIN_PASSWORD")
    if require_credentials and method == "email" and not (email and password):
        raise RuntimeError("LOGIN_METHOD=email の場合は LOGIN_EMAIL / LOGIN_PASSWORD が必要です")

    return LoginConfig(
        site_url=site_url,
        method=method,
        email=email,
        password=password,
        headless=os.environ.get("HEADLESS", "false").lower() == "true",
        qr_screenshot_path=os.environ.get("QR_SCREENSHOT_PATH", "qr_login.png"),
    )


@dataclass(frozen=True)
class ListConfig:
    min_sleep_seconds: float
    max_sleep_seconds: float


def load_list_config() -> ListConfig:
    min_sleep_seconds = float(os.environ.get("LIST_MIN_SLEEP_SECONDS", "1.0"))
    max_sleep_seconds = float(os.environ.get("LIST_MAX_SLEEP_SECONDS", "3.0"))
    if min_sleep_seconds > max_sleep_seconds:
        raise RuntimeError(
            "LIST_MIN_SLEEP_SECONDS は LIST_MAX_SLEEP_SECONDS 以下にしてください"
        )

    return ListConfig(
        min_sleep_seconds=min_sleep_seconds,
        max_sleep_seconds=max_sleep_seconds,
    )
