"""profile_db.search_profiles / profile_export の確認用スクリプト（profile-search, profile-search-chat-fields）

サイトにはアクセスしない。DB は一時ディレクトリに作る。プロジェクトルートから次のように実行する。

    PYTHONPATH=src python scripts/check_profile_search.py

期待値と違う項目があれば表示し、終了コード 1 で終わる。
"""

import csv
import io
import json
import sqlite3
import sys
import tempfile
import time
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from with_auto_reply import profile_db
from with_auto_reply.profile_db import DbNotFound, SearchCriteria, search_profiles
from with_auto_reply.chat_history import ChatSummary, LastSender
from with_auto_reply.profile_export import ALL_COLUMNS, parse_fields, write_results
from with_auto_reply.user_profile import parse_user_profile

SAMPLE_PATH = Path(__file__).resolve().parent.parent / "sample" / "htiw_user_page.html"
PERF_ROWS = 1_000
PERF_LIMIT_SECONDS = 3.0

failures: list[str] = []


def check(label: str, actual, expected) -> None:
    ok = actual == expected
    print(f"  [{'OK' if ok else 'NG'}] {label}")
    if not ok:
        failures.append(f"{label}: 期待値 {expected!r} / 実際 {actual!r}")


def build_db(path: Path) -> None:
    """サンプル + 年齢・居住地・好みカード・いいね数を変えた5人分のDBを作る"""
    base = parse_user_profile(SAMPLE_PATH.read_text(encoding="utf-8"))
    profiles = [
        base,  # 6251609526 rye 28歳 東京 215 / K-POP, バレエ
        replace(base, user_id="2", nickname="Hana", age="25歳", address="神奈川", likes_count=100,
                introduction="カフェ巡りが好き 100%満足", affinities=("土日休み",), groups=("カフェ",),
                basic_info={"タバコ": "吸う"}),
        replace(base, user_id="3", nickname="miki", age="31歳", address="東京 港区", likes_count=300,
                introduction="旅行", affinities=(), groups=("旅行好き",), basic_info={"お酒": "飲む"}),
        replace(base, user_id="4", nickname="nana", age="年齢非公開", address="大阪", likes_count=None,
                introduction=None, affinities=(), groups=(), group_tendencies=(), basic_info={}),
        replace(base, user_id="5", nickname="rina", age="30歳", address="千葉", likes_count=50,
                introduction="よろしく", affinities=(), groups=("k-pop",), basic_info={"休日": "平日"}),
    ]
    conn = profile_db.connect(str(path))
    start = datetime(2026, 11, 5, 10, 0, 0)
    for i, p in enumerate(profiles):
        profile_db.upsert_profile(conn, p, f"/messages/{p.user_id}", start + timedelta(minutes=i))
    conn.close()


def ids(conn, **kwargs) -> list[str]:
    return [row["user_id"] for row in search_profiles(conn, SearchCriteria(**kwargs))]


def check_search(db_path: Path) -> None:
    print("1. search_profiles()")
    conn = profile_db.connect_readonly(str(db_path))
    check("条件なし: 全件・取得日時の新しい順", ids(conn), ["5", "4", "3", "2", "6251609526"])
    check("user_id 完全一致", ids(conn, user_id="2"), ["2"])
    check("user_id 部分一致はしない", ids(conn, user_id="625"), [])
    check("name 部分一致・大文字小文字無視", ids(conn, name="HANA"), ["2"])
    check("min_age 28（境界を含む・非公開は除外）", ids(conn, min_age=28), ["5", "3", "6251609526"])
    check("max_age 28（境界を含む）", ids(conn, max_age=28), ["2", "6251609526"])
    check("min_age 28 + max_age 30", ids(conn, min_age=28, max_age=30), ["5", "6251609526"])
    check("address 部分一致", ids(conn, address="東京"), ["3", "6251609526"])
    check("keyword: 自己紹介文", ids(conn, keyword="カフェ巡り"), ["2"])
    check("keyword: 好みカード・大文字小文字無視", ids(conn, keyword="K-POP"), ["5", "6251609526"])
    check("keyword: 共通点", ids(conn, keyword="一人暮らし同士"), ["6251609526"])
    check("keyword: 基本情報の値", ids(conn, keyword="飲む"), ["3"])
    check("keyword: 基本情報の項目名には一致しない", ids(conn, keyword="お酒"), [])
    check("keyword: % をワイルドカードにしない", ids(conn, keyword="100%"), ["2"])
    check("keyword: _ をワイルドカードにしない", ids(conn, keyword="_"), [])
    check("min_likes 100（境界を含む・NULLは除外）", ids(conn, min_likes=100), ["3", "2", "6251609526"])
    check("max_likes 100（境界を含む）", ids(conn, max_likes=100), ["5", "2"])
    check("min_likes 100 + max_likes 250", ids(conn, min_likes=100, max_likes=250), ["2", "6251609526"])
    check("複数条件の AND", ids(conn, address="東京", min_likes=250), ["3"])
    check("limit", ids(conn, limit=2), ["5", "4"])

    row = search_profiles(conn, SearchCriteria(user_id="6251609526"))[0]
    check("出力のキー（age_years を含まない）", tuple(row.keys()), ALL_COLUMNS)
    check("groups が JSON から戻る", row["groups"][:2], ["散歩デートが好き", "スターバックス大好き集まれ"])
    check("basic_info が dict に戻る", row["basic_info"]["結婚歴"], "未婚")

    try:
        conn.execute("DELETE FROM profiles")
        writable = True
    except Exception:
        writable = False
    check("読み取り専用で開いている", writable, False)
    conn.close()


def capture_stdout(rows, fmt) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        write_results(rows, fmt)
    return buffer.getvalue()


def check_export(db_path: Path, tmp: Path) -> None:
    print("2. write_results()")
    conn = profile_db.connect_readonly(str(db_path))
    rows = search_profiles(conn, SearchCriteria())
    empty = search_profiles(conn, SearchCriteria(user_id="none"))
    conn.close()

    text = capture_stdout(rows, "json")
    check("JSON: json.loads() で読める・5件", len(json.loads(text)), 5)
    check("JSON: 日本語をエスケープしない", "\\u" not in text and "東京" in text, True)
    check("JSON: 0件は []", json.loads(capture_stdout(empty, "json")), [])

    text = capture_stdout(rows, "csv")
    parsed = list(csv.reader(io.StringIO(text)))
    check("CSV: 見出し行", tuple(parsed[0]), ALL_COLUMNS)
    check("CSV: 見出し + 5行", len(parsed), 6)
    sample = next(r for r in parsed[1:] if r[0] == "6251609526")
    col = {name: i for i, name in enumerate(ALL_COLUMNS)}
    check("CSV: 共通点はセル内改行", sample[col["affinities"]].split("\n")[:2], ["散歩デートが好き", "土日休み"])
    check("CSV: 登録傾向の形式", sample[col["group_tendencies"]].split("\n")[0], "アート: 38%")
    check("CSV: 基本情報の形式", sample[col["basic_info"]].split("\n")[0], "ニックネーム: rye")
    nana = next(r for r in parsed[1:] if r[0] == "4")
    check("CSV: None は空のセル", (nana[col["likes_count"]], nana[col["introduction"]]), ("", ""))
    check("CSV: 0件は見出し行だけ", list(csv.reader(io.StringIO(capture_stdout(empty, "csv")))), [list(ALL_COLUMNS)])
    check("CSV（標準出力）: 行末が \\r\\n にならない", "\r" in text, False)

    csv_path = tmp / "out" / "result.csv"
    write_results(rows, "csv", str(csv_path))
    raw = csv_path.read_bytes()
    check("CSVファイル: 先頭が BOM", raw[:3], b"\xef\xbb\xbf")
    check("CSVファイル: 行末は \\r\\n で \\r\\r\\n にならない", (b"\r\n" in raw, b"\r\r\n" in raw), (True, False))

    json_path = tmp / "out" / "result.json"
    write_results(rows, "json", str(json_path))
    raw = json_path.read_bytes()
    check("JSONファイル: BOM なしで読める", (raw[:3] != b"\xef\xbb\xbf", len(json.loads(raw.decode("utf-8")))), (True, 5))
    write_results(empty, "json", str(json_path))
    check("JSONファイル: 上書きされる", json.loads(json_path.read_text(encoding="utf-8")), [])


def check_not_found(tmp: Path) -> None:
    print("3. DBファイルがない場合")
    missing = tmp / "missing.sqlite"
    try:
        profile_db.connect_readonly(str(missing))
        raised = False
    except DbNotFound:
        raised = True
    check("DbNotFound が送出される", raised, True)
    check("DBファイルは作られない", missing.exists(), False)


def check_performance(tmp: Path) -> None:
    print(f"4. 性能（{PERF_ROWS}件）")
    path = tmp / "perf.sqlite"
    base = parse_user_profile(SAMPLE_PATH.read_text(encoding="utf-8"))
    conn = profile_db.connect(str(path))
    now = datetime(2026, 11, 5)
    for i in range(PERF_ROWS):
        profile_db.upsert_profile(conn, replace(base, user_id=str(i)), f"/messages/{i}", now)
        profile_db.upsert_chat_history(conn, str(i), ChatSummary(LastSender.ME, i % 7, i % 5), now)
    conn.close()

    start = time.perf_counter()
    conn = profile_db.connect_readonly(str(path))
    rows = search_profiles(conn, SearchCriteria())
    conn.close()
    capture_stdout(rows, "json")
    capture_stdout(rows, "csv")
    elapsed = time.perf_counter() - start
    check(f"条件なしの検索と出力が{PERF_LIMIT_SECONDS}秒以内（{elapsed:.2f}秒）", elapsed <= PERF_LIMIT_SECONDS, True)
    check("件数", len(rows), PERF_ROWS)


CHAT_KEYS = ("last_sender", "chat_checked_at", "my_message_count", "other_message_count", "total_message_count")


def chat_values(rows: list[dict]) -> dict:
    return {row["user_id"]: tuple(row[key] for key in CHAT_KEYS) for row in rows}


def check_chat_fields(db_path: Path, tmp: Path) -> None:
    """profile-search-chat-fields のテスト戦略1〜6"""
    print("5. チャット履歴のキーと --fields")
    # 1. chat_histories がない DB（chat-history-check の実装前に作った DB を再現する）
    old_db = tmp / "old.sqlite"
    old_db.write_bytes(db_path.read_bytes())
    conn = sqlite3.connect(old_db)
    conn.execute("DROP TABLE chat_histories")
    conn.commit()
    conn.close()
    conn = profile_db.connect_readonly(str(old_db))
    rows = search_profiles(conn, SearchCriteria())
    conn.close()
    check("テーブルなし: 例外にならず全件", len(rows), 5)
    check("テーブルなし: チャット履歴のキーは全件 None",
          set(chat_values(rows).values()), {(None,) * len(CHAT_KEYS)})

    # 2. 一部の相手だけ記録した DB
    conn = profile_db.connect_readonly(str(db_path))
    before_ids = ids(conn)
    conn.close()
    conn = profile_db.connect(str(db_path))
    checked = datetime(2026, 11, 6, 9, 0, 0)
    profile_db.upsert_chat_history(conn, "2", ChatSummary(LastSender.OTHER, 3, 5), checked)
    profile_db.upsert_chat_history(conn, "6251609526", ChatSummary(LastSender.NONE, 0, 0), checked)
    conn.close()
    conn = profile_db.connect_readonly(str(db_path))
    rows = search_profiles(conn, SearchCriteria())
    values = chat_values(rows)
    check("記録あり: 値と合計（和）", values["2"], (2, "2026-11-06T09:00:00", 3, 5, 8))
    check("記録あり: 未送信は 0", values["6251609526"], (0, "2026-11-06T09:00:00", 0, 0, 0))
    check("記録なし: None", values["3"], (None,) * len(CHAT_KEYS))
    check("JOIN しても件数・並び順は同じ", [r["user_id"] for r in rows], before_ids)
    # 3. 既存の条件との組み合わせ（p. 付きの列名）
    check("JOIN + keyword", ids(conn, keyword="K-POP"), ["5", "6251609526"])
    check("JOIN + user_id", ids(conn, user_id="2"), ["2"])
    check("JOIN + min_age + address", ids(conn, min_age=28, address="東京"), ["3", "6251609526"])
    conn.close()

    # 4. parse_fields()
    check("parse_fields: 空白を除く", parse_fields("user_id, nickname"), ("user_id", "nickname"))
    check("parse_fields: 重複は最初の位置", parse_fields("user_id,nickname,user_id"), ("user_id", "nickname"))
    for label, text in (("未知のキー", "user_id,foo"), ("空", ""), ("カンマだけ", " , ")):
        try:
            parse_fields(text)
            raised = False
        except ValueError:
            raised = True
        check(f"parse_fields: {label}は ValueError", raised, True)

    # 5. fields を指定した出力
    fields = ("last_sender", "user_id", "total_message_count")
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        write_results(rows, "json", fields=fields)
    parsed = json.loads(buffer.getvalue())
    check("JSON: 指定したキーだけ・指定順", list(parsed[0].keys()), list(fields))
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        write_results(rows, "csv", fields=fields)
    table = list(csv.reader(io.StringIO(buffer.getvalue())))
    check("CSV: 見出しは指定順", table[0], list(fields))
    row2 = next(r for r in table[1:] if r[1] == "2")
    check("CSV: 数値は文字列・None は空", (row2, next(r for r in table[1:] if r[1] == "3")),
          (["2", "2", "8"], ["", "3", ""]))
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        write_results([], "csv", fields=("user_id", "last_sender"))
    check("CSV: 0件は指定した見出しだけ", buffer.getvalue(), "user_id,last_sender\n")
    out = tmp / "out" / "fields.csv"
    write_results(rows, "csv", str(out), fields=("user_id",))
    check("CSVファイルにも適用", out.read_text(encoding="utf-8-sig").splitlines()[0], "user_id")

    # 6. fields なしは既存のキー順 + 末尾にチャット履歴の5キー
    check("既定のキー: 既存の順序 + 末尾に5キー", tuple(rows[0].keys())[-5:], CHAT_KEYS)
    check("既定のキー: 先頭は既存どおり", tuple(rows[0].keys())[:13],
          ("user_id", "nickname", "age", "address", "last_online", "likes_count", "introduction",
           "affinities", "groups", "group_tendencies", "basic_info", "link", "fetched_at"))


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        db_path = tmp / "db.sqlite"
        build_db(db_path)
        check_search(db_path)
        check_export(db_path, tmp)
        check_not_found(tmp)
        check_performance(tmp)
        check_chat_fields(db_path, tmp)

    if failures:
        print("\n失敗:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("\nすべて成功しました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
