import cmd
import getpass
import json
import logging
import shlex
from pathlib import Path

from docopt import DocoptExit, docopt
from playwright.sync_api import Page, sync_playwright

from .chat_reply import generate_reply_draft
from .config import load_list_config, load_login_config
from .list_items import iter_items
from .login import LoginAborted, login_email, login_with_email
from .logging_config import setup_logging

logger = logging.getLogger(__name__)

README_PATH = Path(__file__).resolve().parents[2] / "README.md"

LOGIN_USAGE = """サイトにログインする（パスワードは実行後に入力を求めます）

Usage:
  login line email <email>
  login email <email>

  login line email <email>  LINE 連携（メールアドレス）でログインする
  login email <email>       メールアドレスでログインする
                            （ログインボタン押下後、with.is に戻るまでブラウザ操作を任せます）
"""


class WithAutoReplyShell(cmd.Cmd):
    intro = "with_auto_reply シェルです。'help' でコマンド一覧、'exit' で終了します。"
    prompt = "(with_auto_reply) "

    def __init__(self) -> None:
        super().__init__()
        self._playwright = None
        self._browser = None
        self._page: Page | None = None

    def _ensure_page(self) -> Page:
        if self._page is None:
            login_config = load_login_config(require_credentials=False)
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=login_config.headless)
            self._page = self._browser.new_page()
        return self._page

    def do_login(self, arg: str) -> None:
        try:
            args = docopt(LOGIN_USAGE, argv=shlex.split(arg), default_help=False)
        except (DocoptExit, ValueError):
            print(LOGIN_USAGE)
            return

        email = args["<email>"]
        try:
            password = getpass.getpass("パスワード: ")
        except (EOFError, KeyboardInterrupt):
            print()
            print("ログインを中止しました")
            return
        if not password:
            print("パスワードが入力されなかったため、ログインを中止しました")
            return

        try:
            config = load_login_config(require_credentials=False)
            page = self._ensure_page()
            if args["line"]:
                login_email(page, config.site_url, email, password)
            else:
                print("ログインボタン押下後は、with.is に戻るまでブラウザで操作してください")
                login_with_email(page, email, password)
            print("ログインしました")
        except LoginAborted as exc:
            logger.warning("ログイン処理を終了しました: %s", exc)
            print(f"ログイン処理を終了しました: {exc}")
        except Exception as exc:
            logger.exception("ログインに失敗しました")
            print(f"ログインに失敗しました: {exc}")

    def help_login(self) -> None:
        print(LOGIN_USAGE)

    def do_list(self, arg: str) -> None:
        "アイテム一覧を取得する\n使い方: list [件数]"
        try:
            count = int(arg.strip()) if arg.strip() else None
        except ValueError:
            print("件数には整数を指定してください")
            return

        try:
            login_config = load_login_config(require_credentials=False)
            list_config = load_list_config()
            page = self._ensure_page()
            for item in iter_items(
                page,
                login_config.site_url,
                limit=count,
                min_sleep_seconds=list_config.min_sleep_seconds,
                max_sleep_seconds=list_config.max_sleep_seconds,
            ):
                print(json.dumps(item, ensure_ascii=False))
        except Exception as exc:
            logger.exception("一覧取得に失敗しました")
            print(f"一覧取得に失敗しました: {exc}")

    def do_chat(self, arg: str) -> None:
        "チャット履歴(JSONファイル)から返信文の下書きを作成する（送信はしません）\n使い方: chat <チャット履歴のJSONファイルパス>"
        path_str = arg.strip()
        if not path_str:
            print("チャット履歴の JSON ファイルパスを指定してください")
            return

        try:
            chat = json.loads(Path(path_str).read_text(encoding="utf-8"))
        except FileNotFoundError:
            print(f"ファイルが見つかりません: {path_str}")
            return
        except json.JSONDecodeError as exc:
            print(f"JSON の読み込みに失敗しました: {exc}")
            return

        try:
            draft = generate_reply_draft(chat)
            print("--- 返信文の下書き（内容を確認のうえ、ご自身で送信してください） ---")
            print(draft)
        except Exception as exc:
            logger.exception("返信文の作成に失敗しました")
            print(f"返信文の作成に失敗しました: {exc}")

    def do_readme(self, arg: str) -> None:
        "README を表示する\n使い方: readme"
        print(README_PATH.read_text(encoding="utf-8"))

    def do_exit(self, arg: str) -> bool:
        "シェルを終了する\n使い方: exit"
        return self._close()

    def do_quit(self, arg: str) -> bool:
        "シェルを終了する\n使い方: quit"
        return self._close()

    def do_EOF(self, arg: str) -> bool:
        "Ctrl+D でシェルを終了する"
        print()
        return self._close()

    def _close(self) -> bool:
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        return True

    def emptyline(self) -> bool:
        return False


def main() -> None:
    setup_logging()
    shell = WithAutoReplyShell()
    try:
        shell.cmdloop()
    except KeyboardInterrupt:
        print()
        shell._close()


if __name__ == "__main__":
    main()
