import logging
from urllib.parse import urlparse

from playwright.sync_api import Page, sync_playwright

from .config import LoginConfig, load_login_config

logger = logging.getLogger(__name__)

OPEN_DIALOG_BUTTON = ".welcome-lp_main_card_btn.open-dialog"
SIGN_IN_DIALOG_BUTTON = 'button[data-dialog-id="sign-in-dialog"]'
LINE_LOGIN_BUTTON = ".line-button"
LINE_QR_LOGIN_LINK = "a.MdBtn02"
TID_INPUT = 'input[name="tid"]'
TPASSWD_INPUT = 'input[name="tpasswd"]'
SUBMIT_BUTTON = 'button[type="submit"]'

WITH_DOMAIN = "with.is"
EMAIL_LOGIN_URL = f"https://{WITH_DOMAIN}/apple_session/new?action_type=sign_in"
EMAIL_INPUT = "#account_name_text_field"
PASSWORD_INPUT = "#password_text_field"
EMAIL_SIGN_IN_BUTTON = "#sign-in"
EMAIL_INPUT_WAIT_MS = 3000
EMAIL_LOGIN_GOTO_TIMEOUT_MS = 90_000


class LoginAborted(Exception):
    """ログイン処理がトップページへの遷移により中断されたことを表す"""


def _normalize_url(url: str) -> str:
    return url.rstrip("/")


def open_sign_in_dialog(page: Page) -> None:
    page.click(OPEN_DIALOG_BUTTON)
    page.click(SIGN_IN_DIALOG_BUTTON)


def click_line_login(page: Page) -> None:
    page.click(LINE_LOGIN_BUTTON)


def login_with_line_email(page: Page, email: str, password: str) -> None:
    logger.info("メールアドレスでログインします")
    click_line_login(page)
    page.fill(TID_INPUT, email)
    page.fill(TPASSWD_INPUT, password)
    page.locator(SUBMIT_BUTTON).first.click()


# with.is ドメイン上でも、認証処理の途中で経由するページ（例: /__/auth/handler）
AUTH_INTERMEDIATE_PATH_PREFIX = "/__/"


def _is_with_domain(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return host == WITH_DOMAIN or host.endswith("." + WITH_DOMAIN)


def _is_login_finished(url: str) -> bool:
    """with.is に戻り、かつ認証処理の中継ページを抜けたか"""
    return _is_with_domain(url) and not urlparse(url).path.startswith(
        AUTH_INTERMEDIATE_PATH_PREFIX
    )


def login_with_email(page: Page, email: str, password: str) -> None:
    """メールアドレス・パスワードでログインする。

    ログインボタン押下後は、with.is ドメインに戻ってくるまで
    （2 段階認証などの）操作をユーザーに任せて待機する。
    """
    logger.info("メールアドレスでログインします")
    page.goto(EMAIL_LOGIN_URL, timeout=EMAIL_LOGIN_GOTO_TIMEOUT_MS)

    page.fill(EMAIL_INPUT, email)
    page.wait_for_timeout(EMAIL_INPUT_WAIT_MS)
    page.fill(PASSWORD_INPUT, password)
    page.wait_for_timeout(EMAIL_INPUT_WAIT_MS)
    page.click(EMAIL_SIGN_IN_BUTTON)

    logger.info("%s に戻るまで、ブラウザでの操作をお任せします", WITH_DOMAIN)
    page.wait_for_url(_is_login_finished, timeout=0)
    page.wait_for_load_state()
    logger.info("ログインが完了しました: %s", page.url)


def login_with_line_qr(page: Page, screenshot_path: str, home_url: str) -> None:
    logger.info("QRコードでログインします")
    click_line_login(page)
    with page.expect_navigation():
        page.click(LINE_QR_LOGIN_LINK)
    page.screenshot(path=screenshot_path)
    logger.info("QRコードを保存しました: %s", screenshot_path)

    page.wait_for_url(lambda url: "sign-in-dialog" not in url, timeout=0)

    if _normalize_url(page.url) == _normalize_url(home_url):
        logger.warning("トップページ(%s)に戻ったため、ログイン処理を終了します", home_url)
        raise LoginAborted(f"トップページ({home_url})に戻ったためログイン処理を終了しました")

    logger.info("ログインが完了しました")


def login_email(page: Page, site_url: str, email: str, password: str) -> None:
    """サイトを開き、LINE 連携のメールアドレス・パスワードでログインする"""
    page.goto(site_url)
    open_sign_in_dialog(page)
    login_with_line_email(page, email, password)


def login(page: Page, config: LoginConfig) -> None:
    page.goto(config.site_url)
    open_sign_in_dialog(page)

    if config.method == "email":
        login_with_line_email(page, config.email, config.password)
    else:
        login_with_line_qr(page, config.qr_screenshot_path, config.site_url)


def run() -> None:
    config = load_login_config()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=config.headless)
        page = browser.new_page()
        login(page, config)
        browser.close()


if __name__ == "__main__":
    run()
