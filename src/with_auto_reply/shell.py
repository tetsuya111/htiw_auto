import cmd
import getpass
import json
import logging
import shlex
from pathlib import Path

from docopt import DocoptExit, docopt
from playwright.sync_api import Page, sync_playwright

from . import profile_db
from .chat_history import LAST_SENDER_LABELS, LastSender, check_chats
from .chat_reply import generate_reply_draft
from .config import load_db_config, load_list_config, load_login_config
from .list_items import iter_items
from .login import LoginAborted, login_email, login_with_email
from .logging_config import setup_logging
from .profile_collector import TooManyFailures, save_profiles
from .profile_export import ALL_COLUMNS, FORMATS, parse_fields, write_results

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

SAVE_PROFILES_USAGE = """メッセージ一覧の相手のプロフィールを取得して DB に保存する

Usage:
  save_profiles [<count>] [--refresh]

  <count>    一覧の先頭から対象にする件数（省略時はすべて）
  --refresh  保存済みの相手も取得し直して上書きする
"""

SEARCH_PROFILES_USAGE = """DB に保存したプロフィールを検索して JSON / CSV で出力する（条件はすべて AND）

Usage:
  search_profiles [options]

Options:
  --user-id=<id>     ユーザーIDが完全一致
  --name=<text>      ニックネームに含む
  --min-age=<n>      年齢の下限（この値を含む）
  --max-age=<n>      年齢の上限（この値を含む）
  --address=<text>   居住地に含む
  --keyword=<text>   自己紹介文・共通点・好みカード・基本情報の値のいずれかに含む
  --min-likes=<n>    いいね数の下限（この値を含む）
  --max-likes=<n>    いいね数の上限（この値を含む）
  --limit=<n>        出力する最大件数
  --format=<fmt>     json または csv [default: json]
  --output=<path>    書き出すファイル（省略時は標準出力）
  --fields=<keys>    出力するキーをカンマ区切りで指定（省略時はすべて。例: user_id,nickname,last_sender）
"""

CHECK_CHATS_USAGE = """チャットで最後に送信したのがどちらかと、メッセージ件数を確認して DB に記録する
（チャットページを開いて読むだけで、送信はしません）

Usage:
  check_chats [<count>] [--user-id=<id>]

  <count>          保存済みの相手のうち、取得日時の新しい順に確認する件数（省略時はすべて）
  --user-id=<id>   このユーザーIDの相手だけを確認する（<count> より優先）
"""

SAVE_STATUS_LABELS = {"saved": "保存", "skipped": "スキップ（保存済み）", "failed": "失敗"}
CHECK_COUNT_KEYS = {LastSender.NONE: "none", LastSender.ME: "me", LastSender.OTHER: "other"}


class UsageError(ValueError):
    """コマンドの引数が不正"""


def _parse_non_negative_int(value: str | None, name: str) -> int | None:
    if value is None:
        return None
    try:
        number = int(value)
    except ValueError:
        raise UsageError(f"{name} には0以上の整数を指定してください") from None
    if number < 0:
        raise UsageError(f"{name} には0以上の整数を指定してください")
    return number


def _parse_search_args(
    args: dict,
) -> tuple[profile_db.SearchCriteria, str, str | None, tuple[str, ...] | None]:
    fmt = args["--format"]
    if fmt not in FORMATS:
        raise UsageError(f"--format には {' / '.join(FORMATS)} を指定してください")

    criteria = profile_db.SearchCriteria(
        user_id=args["--user-id"],
        name=args["--name"],
        min_age=_parse_non_negative_int(args["--min-age"], "--min-age"),
        max_age=_parse_non_negative_int(args["--max-age"], "--max-age"),
        address=args["--address"],
        keyword=args["--keyword"],
        min_likes=_parse_non_negative_int(args["--min-likes"], "--min-likes"),
        max_likes=_parse_non_negative_int(args["--max-likes"], "--max-likes"),
        limit=_parse_non_negative_int(args["--limit"], "--limit"),
    )
    for low, high, label in (
        (criteria.min_age, criteria.max_age, "--min-age は --max-age"),
        (criteria.min_likes, criteria.max_likes, "--min-likes は --max-likes"),
    ):
        if low is not None and high is not None and low > high:
            raise UsageError(f"{label} 以下にしてください")
    fields = None
    if args["--fields"] is not None:
        try:
            fields = parse_fields(args["--fields"])
        except ValueError as exc:
            raise UsageError(f"{exc}\n指定できるキー: {', '.join(ALL_COLUMNS)}") from None
    return criteria, fmt, args["--output"], fields


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

    def do_save_profiles(self, arg: str) -> None:
        try:
            args = docopt(SAVE_PROFILES_USAGE, argv=shlex.split(arg), default_help=False)
            count = _parse_non_negative_int(args["<count>"], "<count>")
            if count == 0:
                raise UsageError("<count> には1以上の整数を指定してください")
        except UsageError as exc:
            print(exc)
            print(SAVE_PROFILES_USAGE)
            return
        except (DocoptExit, ValueError):
            print(SAVE_PROFILES_USAGE)
            return

        counts = {"saved": 0, "skipped": 0, "failed": 0}
        conn = None
        db_path = None

        def print_summary(prefix: str) -> None:
            print(
                f"{prefix}: 保存 {counts['saved']} 件、スキップ {counts['skipped']} 件、"
                f"失敗 {counts['failed']} 件（DB: {db_path}）"
            )
            logger.info("save_profiles %s: %s", prefix, counts)

        try:
            login_config = load_login_config(require_credentials=False)
            list_config = load_list_config()
            db_path = load_db_config().path
            page = self._ensure_page()
            conn = profile_db.connect(db_path)
            logger.info("save_profiles を開始します（件数=%s, refresh=%s）", count, args["--refresh"])
            print("一覧を取得しています...")
            for i, result in enumerate(
                save_profiles(
                    page,
                    conn,
                    login_config.site_url,
                    limit=count,
                    refresh=args["--refresh"],
                    min_sleep_seconds=list_config.min_sleep_seconds,
                    max_sleep_seconds=list_config.max_sleep_seconds,
                ),
                start=1,
            ):
                counts[result.status] += 1
                label = SAVE_STATUS_LABELS[result.status]
                target = f"{result.user_id} {result.nickname or ''}" if result.user_id else result.link
                reason = f"（{result.reason}）" if result.reason else ""
                print(f"[{i}] {label}: {target}{reason}")
            print_summary("完了")
        except TooManyFailures as exc:
            logger.exception("プロフィールの保存を中止しました")
            print(f"{exc}。ログインが切れている可能性があるため中止しました")
            print_summary("中止")
        except KeyboardInterrupt:
            # ここで捕捉しないと main() まで伝わりシェルが終了する
            logger.warning("save_profiles が中断されました")
            print()
            print_summary("中断")
        except Exception as exc:
            logger.exception("プロフィールの保存に失敗しました")
            print(f"プロフィールの保存に失敗しました: {exc}")
            print_summary("失敗で終了")
        finally:
            if conn is not None:
                conn.close()

    def help_save_profiles(self) -> None:
        print(SAVE_PROFILES_USAGE)

    def do_search_profiles(self, arg: str) -> None:
        try:
            args = docopt(SEARCH_PROFILES_USAGE, argv=shlex.split(arg), default_help=False)
            criteria, fmt, output, fields = _parse_search_args(args)
        except UsageError as exc:
            print(exc)
            print(SEARCH_PROFILES_USAGE)
            return
        except (DocoptExit, ValueError):
            print(SEARCH_PROFILES_USAGE)
            return

        conn = None
        try:
            db_path = load_db_config().path
            conn = profile_db.connect_readonly(db_path)
            rows = profile_db.search_profiles(conn, criteria)
            # 条件の値・結果の本文は個人情報になりうるのでログに出さない
            logger.info(
                "search_profiles: 条件=%s, 形式=%s, ファイル出力=%s, 出力項目=%s, チャット履歴テーブル=%s, 件数=%d",
                criteria.specified_names(),
                fmt,
                output is not None,
                list(fields) if fields else "すべて",
                profile_db.has_chat_histories(conn),
                len(rows),
            )
            write_results(rows, fmt, output, fields or ALL_COLUMNS)
            if output is not None:
                print(f"{len(rows)} 件を {output} に書き出しました")
        except profile_db.DbNotFound as exc:
            logger.warning("DBファイルがありません")
            print(f"{exc}。先に save_profiles を実行してください")
        except OSError as exc:
            logger.exception("検索結果の書き出しに失敗しました")
            print(f"検索結果の書き出しに失敗しました: {exc}")
        except Exception as exc:
            logger.exception("プロフィールの検索に失敗しました")
            print(f"プロフィールの検索に失敗しました: {exc}")
        finally:
            if conn is not None:
                conn.close()

    def help_search_profiles(self) -> None:
        print(SEARCH_PROFILES_USAGE)

    def do_check_chats(self, arg: str) -> None:
        try:
            args = docopt(CHECK_CHATS_USAGE, argv=shlex.split(arg), default_help=False)
            count = _parse_non_negative_int(args["<count>"], "<count>")
            if count == 0:
                raise UsageError("<count> には1以上の整数を指定してください")
        except UsageError as exc:
            print(exc)
            print(CHECK_CHATS_USAGE)
            return
        except (DocoptExit, ValueError):
            print(CHECK_CHATS_USAGE)
            return

        user_id = args["--user-id"]
        if user_id is not None:
            count = None  # 対象が1人になるので件数は意味を持たない
        counts = {"me": 0, "other": 0, "none": 0, "failed": 0}
        conn = None
        db_path = None

        def print_summary(prefix: str) -> None:
            print(
                f"{prefix}: 自分 {counts['me']} 件、相手 {counts['other']} 件、"
                f"未送信 {counts['none']} 件、失敗 {counts['failed']} 件（DB: {db_path}）"
            )
            logger.info("check_chats %s: %s", prefix, counts)

        try:
            login_config = load_login_config(require_credentials=False)
            list_config = load_list_config()
            db_path = load_db_config().path
            # connect() は空の DB を作ってしまうので、先に存在を確かめる
            if not Path(db_path).is_file():
                logger.warning("DBファイルがありません")
                print(f"DBファイル {db_path} がありません。先に save_profiles を実行してください")
                return
            conn = profile_db.connect(db_path)
            targets = profile_db.list_profile_targets(conn, limit=count, user_id=user_id)
            if not targets:
                if user_id is not None:
                    print(f"ユーザーID {user_id} のプロフィールは保存されていません。先に save_profiles を実行してください")
                else:
                    print("保存済みのプロフィールがありません。先に save_profiles を実行してください")
                return

            logger.info("check_chats を開始します（対象 %d 人、user_id 指定=%s）", len(targets), user_id is not None)
            page = self._ensure_page()
            for i, result in enumerate(
                check_chats(
                    page,
                    conn,
                    login_config.site_url,
                    targets,
                    min_sleep_seconds=list_config.min_sleep_seconds,
                    max_sleep_seconds=list_config.max_sleep_seconds,
                ),
                start=1,
            ):
                target = f"{result.user_id} {result.nickname or ''}".rstrip()
                if result.summary is None:
                    counts["failed"] += 1
                    print(f"[{i}] 失敗: {target}（{result.reason}）")
                    continue
                summary = result.summary
                counts[CHECK_COUNT_KEYS[summary.last_sender]] += 1
                print(
                    f"[{i}] {LAST_SENDER_LABELS[summary.last_sender]}: {target}"
                    f"（自分 {summary.my_count} / 相手 {summary.other_count} / 合計 {summary.total_count}）"
                )
            print_summary("完了")
        except TooManyFailures as exc:
            logger.exception("チャットの確認を中止しました")
            print(f"{exc}。ログインが切れている可能性があるため中止しました")
            print_summary("中止")
        except KeyboardInterrupt:
            # ここで捕捉しないと main() まで伝わりシェルが終了する
            logger.warning("check_chats が中断されました")
            print()
            print_summary("中断")
        except Exception as exc:
            logger.exception("チャットの確認に失敗しました")
            print(f"チャットの確認に失敗しました: {exc}")
            print_summary("失敗で終了")
        finally:
            if conn is not None:
                conn.close()

    def help_check_chats(self) -> None:
        print(CHECK_CHATS_USAGE)

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
