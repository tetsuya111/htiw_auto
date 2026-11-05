"""profile_db / profile_collector の保存処理の確認用スクリプト

サイトにはアクセスしない（一覧取得・プロフィール取得・sleep は差し替える）。
DB は一時ディレクトリに作る。プロジェクトルートから次のように実行する。

    PYTHONPATH=src python scripts/check_profile_save.py

期待値と違う項目があれば表示し、終了コード 1 で終わる。
"""

import json
import logging
import sqlite3
import sys
import tempfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from with_auto_reply import profile_collector, profile_db
from with_auto_reply.profile_collector import TooManyFailures, extract_user_id, save_profiles
from with_auto_reply.user_profile import UserProfileNotFound, parse_user_profile

SAMPLE_PATH = Path(__file__).resolve().parent.parent / "sample" / "htiw_user_page.html"

failures: list[str] = []


def check(label: str, actual, expected) -> None:
    ok = actual == expected
    print(f"  [{'OK' if ok else 'NG'}] {label}")
    if not ok:
        failures.append(f"{label}: 期待値 {expected!r} / 実際 {actual!r}")


def check_extract_user_id() -> None:
    print("1. extract_user_id()")
    check("/messages/123", extract_user_id("/messages/123"), "123")
    check("/users/123", extract_user_id("/users/123"), "123")
    check("絶対URL・クエリ付き", extract_user_id("https://example.com/messages/123?x=1"), "123")
    check("/search", extract_user_id("/search"), None)
    check("None", extract_user_id(None), None)


def check_db(tmp: Path) -> None:
    print("2. profile_db（connect / upsert_profile / exists）")
    db_path = tmp / "sub" / "db.sqlite"
    conn = profile_db.connect(str(db_path))
    check("DBファイルとテーブルが作られる", db_path.is_file(), True)

    profile = parse_user_profile(SAMPLE_PATH.read_text(encoding="utf-8"))
    check("保存前は exists() が偽", profile_db.exists(conn, profile.user_id), False)
    profile_db.upsert_profile(conn, profile, "/messages/6251609526", datetime(2026, 11, 5, 10, 0, 0))
    check("保存後は exists() が真", profile_db.exists(conn, profile.user_id), True)

    conn.row_factory = sqlite3.Row
    row = dict(conn.execute("SELECT * FROM profiles").fetchone())
    check("nickname", row["nickname"], "rye")
    check("age / age_years", (row["age"], row["age_years"]), ("28歳", 28))
    check("address", row["address"], "東京")
    check("likes_count", row["likes_count"], 215)
    check("introduction", row["introduction"], profile.introduction)
    check("affinities（JSON）", json.loads(row["affinities"]), list(profile.affinities))
    check("group_cards（JSON）", json.loads(row["group_cards"]), list(profile.groups))
    check(
        "group_tendencies（JSON）",
        json.loads(row["group_tendencies"]),
        profile.to_dict()["group_tendencies"],
    )
    check("basic_info（JSON・順序込み）", list(json.loads(row["basic_info"]).items()), list(profile.basic_info.items()))
    check("日本語をエスケープせずに保存", "散歩デート" in row["affinities"], True)
    check("link", row["link"], "/messages/6251609526")
    check("fetched_at", row["fetched_at"], "2026-11-05T10:00:00")

    updated = replace(profile, likes_count=300)
    profile_db.upsert_profile(conn, updated, "/messages/6251609526", datetime(2026, 11, 6, 9, 30, 0))
    count, likes, fetched_at = conn.execute(
        "SELECT COUNT(*), MAX(likes_count), MAX(fetched_at) FROM profiles"
    ).fetchone()
    check("同じユーザーIDの upsert で行数が1のまま", count, 1)
    check("上書きで内容と取得日時が更新される", (likes, fetched_at), (300, "2026-11-06T09:30:00"))
    conn.close()


class FakeSite:
    """iter_items / fetch_user_profile / time.sleep の差し替え"""

    def __init__(self, items: list[dict], failing_ids: set[str] = frozenset()) -> None:
        self.items = items
        self.failing_ids = failing_ids
        self.fetched: list[str] = []
        self.sleeps = 0
        self.base = parse_user_profile(SAMPLE_PATH.read_text(encoding="utf-8"))

    def install(self) -> None:
        profile_collector.iter_items = lambda page, base_url, limit=None, **kw: iter(
            self.items[:limit] if limit else self.items
        )
        profile_collector.fetch_user_profile = self.fetch
        profile_collector.time.sleep = self.sleep

    def fetch(self, page, base_url, user_id):
        self.fetched.append(user_id)
        if user_id in self.failing_ids:
            raise UserProfileNotFound(f"ユーザーページを開けませんでした: /users/{user_id}")
        return replace(self.base, user_id=user_id, nickname=f"user{user_id}")

    def sleep(self, seconds: float) -> None:
        self.sleeps += 1


def run(conn, site: FakeSite, **kwargs) -> list[str]:
    site.install()
    return [r.status for r in save_profiles(None, conn, "https://example.com", **kwargs)]


def check_collector(tmp: Path) -> None:
    print("3. save_profiles()（一覧・取得を差し替え）")
    items = [{"link": f"/messages/{i}", "name": f"n{i}", "age": ""} for i in range(1, 6)]
    conn = profile_db.connect(str(tmp / "collector.sqlite"))

    site = FakeSite(items)
    check("初回: 5件とも保存", run(conn, site, limit=5), ["saved"] * 5)
    check("初回: 取得前に毎回 sleep", site.sleeps, 5)

    site = FakeSite(items)
    check("2回目: 5件ともスキップ", run(conn, site, limit=5), ["skipped"] * 5)
    check("2回目: ユーザーページへのアクセスが0回", site.fetched, [])

    site = FakeSite(items)
    check("--refresh: 5件とも保存し直す", run(conn, site, limit=5, refresh=True), ["saved"] * 5)
    check("--refresh: 行数は5のまま", conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0], 5)

    site = FakeSite(items)
    check("件数指定: 先頭2件だけ", run(conn, site, limit=2, refresh=True), ["saved"] * 2)

    bad_items = [{"link": "/search", "name": "x", "age": ""}] + items[:1]
    site = FakeSite(bad_items)
    check("IDを取り出せない link は失敗にして続ける", run(conn, site, refresh=True), ["failed", "saved"])

    items2 = [{"link": f"/messages/{i}", "name": "", "age": ""} for i in (10, 11, 12)]
    site = FakeSite(items2, failing_ids={"10"})
    check("取得失敗は失敗にして続ける", run(conn, site), ["failed", "saved", "saved"])

    items3 = [{"link": f"/messages/{i}", "name": "", "age": ""} for i in (20, 21, 22, 23)]
    site = FakeSite(items3, failing_ids={"20", "21", "22", "23"})
    statuses = []
    try:
        site.install()
        for r in save_profiles(None, conn, "https://example.com"):
            statuses.append(r.status)
        raised = False
    except TooManyFailures:
        raised = True
    check("3人連続失敗で TooManyFailures", (raised, statuses), (True, ["failed"] * 3))
    check("中止後は4人目にアクセスしない", site.fetched, ["20", "21", "22"])
    conn.close()


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        check_extract_user_id()
        check_db(tmp)
        check_collector(tmp)

    if failures:
        print("\n失敗:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("\nすべて成功しました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
