"""chat_history / profile_db のチャット履歴まわりの確認用スクリプト

サイトにはアクセスしない（ページは偽のオブジェクトで代用する）。DB は一時ディレクトリに作る。
プロジェクトルートから次のように実行する。

    PYTHONPATH=src python scripts/check_chat_history.py

期待値と違う項目があれば表示し、終了コード 1 で終わる。
"""

import sqlite3
import sys
import tempfile
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from with_auto_reply import profile_db
from with_auto_reply.chat_history import (
    ChatSummary,
    LastSender,
    check_chats,
    summarize_chat,
)
from with_auto_reply.chat_messages import ChatMessage, parse_chat_messages
from with_auto_reply.profile_collector import TooManyFailures
from with_auto_reply.user_profile import parse_user_profile

ROOT = Path(__file__).resolve().parent.parent
CHAT_SAMPLE = ROOT / "sample" / "user_chat_message_page.html"
USER_SAMPLE = ROOT / "sample" / "htiw_user_page.html"

failures: list[str] = []


def check(label: str, actual, expected) -> None:
    ok = actual == expected
    print(f"  [{'OK' if ok else 'NG'}] {label}")
    if not ok:
        failures.append(f"{label}: 期待値 {expected!r} / 実際 {actual!r}")


class FakeLocator:
    def __init__(self, ok: bool) -> None:
        self.ok = ok
        self.first = self

    def wait_for(self, **kwargs) -> None:
        if not self.ok:
            raise PlaywrightTimeoutError("timeout")


class FakePage:
    """user_id ごとに HTML を返す。None の相手はチャットページを読めない扱い"""

    def __init__(self, pages: dict[str, str | None]) -> None:
        self.pages = pages
        self.current: str | None = None
        self.visited: list[str] = []

    def goto(self, url: str) -> None:
        self.current = url.rsplit("/", 1)[-1]
        self.visited.append(url)

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self.pages.get(self.current) is not None)

    def content(self) -> str:
        return self.pages[self.current]


def check_summarize() -> None:
    print("1. summarize_chat()")
    me, other = ChatMessage("me", "a"), ChatMessage("other", "b")
    check("最後が me → 1", summarize_chat([other, me]).last_sender, LastSender.ME)
    check("最後が other → 2", summarize_chat([me, other]).last_sender, LastSender.OTHER)
    empty = summarize_chat([])
    check("空 → 0・件数 0", (empty.last_sender, empty.my_count, empty.other_count, empty.total_count),
          (LastSender.NONE, 0, 0, 0))
    sample = summarize_chat(parse_chat_messages(CHAT_SAMPLE.read_text(encoding="utf-8")))
    check("サンプル: 最後は自分・自分 8・相手 4・合計 12",
          (sample.last_sender, sample.my_count, sample.other_count, sample.total_count),
          (LastSender.ME, 8, 4, 12))


def build_db(path: Path) -> sqlite3.Connection:
    base = parse_user_profile(USER_SAMPLE.read_text(encoding="utf-8"))
    conn = profile_db.connect(str(path))
    start = datetime(2026, 11, 5, 10, 0, 0)
    for i, user_id in enumerate(["1", "2", "3", "4"]):
        profile = replace(base, user_id=user_id, nickname=f"user{user_id}")
        profile_db.upsert_profile(conn, profile, f"/messages/{user_id}", start + timedelta(minutes=i))
    return conn


def history(conn, user_id: str):
    return conn.execute(
        "SELECT id, last_sender, my_message_count, other_message_count, checked_at"
        " FROM chat_histories WHERE profile_id = ?",
        (user_id,),
    ).fetchall()


def check_db(tmp: Path) -> None:
    print("2. profile_db（chat_histories）")
    conn = build_db(tmp / "db.sqlite")
    columns = [row[1] for row in conn.execute("PRAGMA table_info(chat_histories)")]
    check("列（合計件数の列はない）", columns,
          ["id", "profile_id", "last_sender", "my_message_count", "other_message_count", "checked_at"])

    t1, t2 = datetime(2026, 11, 6, 9, 0, 0), datetime(2026, 11, 6, 10, 0, 0)
    profile_db.upsert_chat_history(conn, "1", ChatSummary(LastSender.OTHER, 1, 2), t1)
    first = history(conn, "1")
    profile_db.upsert_chat_history(conn, "1", ChatSummary(LastSender.ME, 3, 2), t2)
    second = history(conn, "1")
    check("2回保存しても1行", len(second), 1)
    check("id が変わらない", second[0][0], first[0][0])
    check("値・件数・確認日時が更新される", second[0][1:], (1, 3, 2, "2026-11-06T10:00:00"))

    try:
        profile_db.upsert_chat_history(conn, "999", ChatSummary(LastSender.NONE, 0, 0), t1)
        fk_error = False
    except sqlite3.IntegrityError:
        fk_error = True
    check("profiles にない相手は外部キー違反", fk_error, True)

    ids = lambda **kw: [u for u, _ in profile_db.list_profile_targets(conn, **kw)]  # noqa: E731
    check("対象: すべて・取得日時の新しい順", ids(), ["4", "3", "2", "1"])
    check("対象: 件数指定", ids(limit=2), ["4", "3"])
    check("対象: ユーザーID指定", ids(user_id="2"), ["2"])
    check("対象: 存在しないユーザーID", ids(user_id="999"), [])
    check("対象: ニックネームも返す", profile_db.list_profile_targets(conn, user_id="2"), [("2", "user2")])
    conn.close()


def check_flow(tmp: Path) -> None:
    print("3. check_chats()（偽のページ）")
    conn = build_db(tmp / "flow.sqlite")
    chat_html = CHAT_SAMPLE.read_text(encoding="utf-8")
    empty_html = '<div class="messages"></div>'
    page = FakePage({"1": chat_html, "2": empty_html, "3": None, "4": chat_html})
    targets = profile_db.list_profile_targets(conn)  # 4, 3, 2, 1
    results = list(check_chats(page, conn, "https://example.com", targets, 0, 0))
    check("全員分の結果", [(r.user_id, r.status) for r in results],
          [("4", "checked"), ("3", "failed"), ("2", "checked"), ("1", "checked")])
    check("チャットページの URL", page.visited[0], "https://example.com/messages/4")
    check("未送信は 0・件数 0", history(conn, "2")[0][1:4], (0, 0, 0))
    check("サンプルは 1・8・4", history(conn, "1")[0][1:4], (1, 8, 4))
    check("失敗した相手は記録しない", history(conn, "3"), [])
    check("結果に合計件数", results[0].summary.total_count, 12)

    fail_page = FakePage({})
    got, raised = [], False
    try:
        for result in check_chats(fail_page, conn, "https://example.com", targets, 0, 0):
            got.append(result.status)
    except TooManyFailures:
        raised = True
    check("3人連続の失敗で TooManyFailures", (got, raised), (["failed"] * 3, True))
    check("失敗しても既存の記録は変わらない", history(conn, "4")[0][1:4], (1, 8, 4))
    conn.close()


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        check_summarize()
        check_db(tmp)
        check_flow(tmp)
    if failures:
        print(f"\nNG {len(failures)} 件:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("\nすべて OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
