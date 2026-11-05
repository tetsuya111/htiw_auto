"""プロフィールを保存する SQLite データベース（db.sqlite）の読み書き

DB には第三者の個人情報が入るため、本文をログに出さないこと。
SQL の値はすべてプレースホルダで渡し、文字列連結で組み立てない。
"""

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .user_profile import UserProfile

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    user_id          TEXT PRIMARY KEY,
    nickname         TEXT NOT NULL,
    age              TEXT,
    age_years        INTEGER,
    address          TEXT,
    last_online      TEXT,
    likes_count      INTEGER,
    introduction     TEXT,
    affinities       TEXT NOT NULL,
    group_cards      TEXT NOT NULL,
    group_tendencies TEXT NOT NULL,
    basic_info       TEXT NOT NULL,
    link             TEXT NOT NULL,
    fetched_at       TEXT NOT NULL
)
"""

UPSERT_SQL = """
INSERT INTO profiles (
    user_id, nickname, age, age_years, address, last_online, likes_count,
    introduction, affinities, group_cards, group_tendencies, basic_info, link, fetched_at
) VALUES (
    :user_id, :nickname, :age, :age_years, :address, :last_online, :likes_count,
    :introduction, :affinities, :group_cards, :group_tendencies, :basic_info, :link, :fetched_at
)
ON CONFLICT(user_id) DO UPDATE SET
    nickname = excluded.nickname,
    age = excluded.age,
    age_years = excluded.age_years,
    address = excluded.address,
    last_online = excluded.last_online,
    likes_count = excluded.likes_count,
    introduction = excluded.introduction,
    affinities = excluded.affinities,
    group_cards = excluded.group_cards,
    group_tendencies = excluded.group_tendencies,
    basic_info = excluded.basic_info,
    link = excluded.link,
    fetched_at = excluded.fetched_at
"""

SELECT_COLUMNS = (
    "user_id, nickname, age, address, last_online, likes_count, introduction, "
    "affinities, group_cards, group_tendencies, basic_info, link, fetched_at"
)
JSON_COLUMNS = ("affinities", "group_cards", "group_tendencies", "basic_info")
LIKE_ESCAPE = "\\"

DIGITS = re.compile(r"\d+")


class DbNotFound(RuntimeError):
    """DB ファイルがない"""


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _age_years(age: str | None) -> int | None:
    if age is None:
        return None
    match = DIGITS.search(age)
    return int(match.group()) if match else None


def connect(path: str) -> sqlite3.Connection:
    """DB に接続し、profiles テーブルがなければ作る"""
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(SCHEMA)
    conn.commit()
    return conn


def exists(conn: sqlite3.Connection, user_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
    return row is not None


def upsert_profile(
    conn: sqlite3.Connection, profile: UserProfile, link: str, fetched_at: datetime
) -> None:
    """1人分を保存（同じユーザーIDなら上書き）して commit する"""
    data = profile.to_dict()
    conn.execute(
        UPSERT_SQL,
        {
            "user_id": profile.user_id,
            "nickname": profile.nickname,
            "age": profile.age,
            "age_years": _age_years(profile.age),
            "address": profile.address,
            "last_online": profile.last_online,
            "likes_count": profile.likes_count,
            "introduction": profile.introduction,
            "affinities": _dumps(data["affinities"]),
            "group_cards": _dumps(data["groups"]),
            "group_tendencies": _dumps(data["group_tendencies"]),
            "basic_info": _dumps(data["basic_info"]),
            "link": link,
            "fetched_at": fetched_at.isoformat(timespec="seconds"),
        },
    )
    conn.commit()


# ---- 検索（docs/specs/profile-search） ----


@dataclass(frozen=True)
class SearchCriteria:
    user_id: str | None = None
    name: str | None = None
    min_age: int | None = None
    max_age: int | None = None
    address: str | None = None
    keyword: str | None = None
    min_likes: int | None = None
    max_likes: int | None = None
    limit: int | None = None

    def specified_names(self) -> list[str]:
        """指定された条件の項目名（ログ用。値は個人情報になりうるので出さない）"""
        return [name for name, value in self.__dict__.items() if value is not None]


def connect_readonly(path: str) -> sqlite3.Connection:
    """読み取り専用で開く。ファイルがなければ DbNotFound（空の DB を作らない）"""
    db_path = Path(path)
    if not db_path.is_file():
        raise DbNotFound(f"DBファイル {path} がありません")
    return sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)


def _like_pattern(value: str) -> str:
    escaped = (
        value.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2)
        .replace("%", LIKE_ESCAPE + "%")
        .replace("_", LIKE_ESCAPE + "_")
    )
    return f"%{escaped}%"


def _json_value_like(column: str) -> str:
    return f"EXISTS (SELECT 1 FROM json_each(profiles.{column}) WHERE value LIKE ? ESCAPE '\\')"


def _build_where(criteria: SearchCriteria) -> tuple[str, list]:
    clauses: list[str] = []
    params: list = []

    if criteria.user_id is not None:
        clauses.append("user_id = ?")
        params.append(criteria.user_id)
    if criteria.name is not None:
        clauses.append("nickname LIKE ? ESCAPE '\\'")
        params.append(_like_pattern(criteria.name))
    if criteria.min_age is not None:
        clauses.append("age_years >= ?")
        params.append(criteria.min_age)
    if criteria.max_age is not None:
        clauses.append("age_years <= ?")
        params.append(criteria.max_age)
    if criteria.address is not None:
        clauses.append("address LIKE ? ESCAPE '\\'")
        params.append(_like_pattern(criteria.address))
    if criteria.keyword is not None:
        # JSON 列は json_each() で値だけを照合する（基本情報の項目名や JSON の記号に一致させない）
        clauses.append(
            "(introduction LIKE ? ESCAPE '\\'"
            f" OR {_json_value_like('affinities')}"
            f" OR {_json_value_like('group_cards')}"
            f" OR {_json_value_like('basic_info')})"
        )
        params.extend([_like_pattern(criteria.keyword)] * 4)
    if criteria.min_likes is not None:
        clauses.append("likes_count >= ?")
        params.append(criteria.min_likes)
    if criteria.max_likes is not None:
        clauses.append("likes_count <= ?")
        params.append(criteria.max_likes)

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def _row_to_dict(row: sqlite3.Row) -> dict:
    data = dict(row)
    for column in JSON_COLUMNS:
        data[column] = json.loads(data[column])
    data["groups"] = data.pop("group_cards")
    # UserProfile.to_dict() と同じキー順にし、link / fetched_at を最後に置く
    order = (
        "user_id", "nickname", "age", "address", "last_online", "likes_count",
        "introduction", "affinities", "groups", "group_tendencies", "basic_info",
        "link", "fetched_at",
    )
    return {key: data[key] for key in order}


def search_profiles(conn: sqlite3.Connection, criteria: SearchCriteria) -> list[dict]:
    """条件（AND）に合うプロフィールを取得日時の新しい順に返す"""
    where, params = _build_where(criteria)
    sql = f"SELECT {SELECT_COLUMNS} FROM profiles{where} ORDER BY fetched_at DESC, user_id"
    if criteria.limit is not None:
        sql += " LIMIT ?"
        params.append(criteria.limit)

    conn.row_factory = sqlite3.Row
    return [_row_to_dict(row) for row in conn.execute(sql, params)]
