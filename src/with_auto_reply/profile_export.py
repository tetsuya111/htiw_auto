"""検索結果のプロフィールを JSON / CSV で書き出す（docs/specs/profile-search, profile-search-chat-fields）"""

import csv
import json
import sys
from pathlib import Path
from typing import TextIO

FORMATS = ("json", "csv")

# 出力できるすべてのキー（JSON のキー・CSV の見出し）。--fields の検証にも使う
ALL_COLUMNS = (
    "user_id",
    "nickname",
    "age",
    "address",
    "last_online",
    "likes_count",
    "introduction",
    "affinities",
    "groups",
    "group_tendencies",
    "basic_info",
    "link",
    "fetched_at",
    # チャット履歴（記録がなければ None）。total_message_count は保存せず検索時に計算した和
    "last_sender",
    "chat_checked_at",
    "my_message_count",
    "other_message_count",
    "total_message_count",
)

# 出力先ごとの文字コード。CSV は Excel で文字化けしないよう BOM 付きにする
FILE_ENCODINGS = {"json": "utf-8", "csv": "utf-8-sig"}


def parse_fields(text: str) -> tuple[str, ...]:
    """カンマ区切りのキーを分割する。前後の空白を除き、重複は最初の位置に1回だけ残す。
    空の指定や ALL_COLUMNS にないキーがあれば ValueError"""
    fields = tuple(dict.fromkeys(key.strip() for key in text.split(",") if key.strip()))
    if not fields:
        raise ValueError("--fields には出力するキーを1つ以上指定してください")
    unknown = [key for key in fields if key not in ALL_COLUMNS]
    if unknown:
        raise ValueError(f"未知のキーです: {', '.join(unknown)}")
    return fields


def write_json(rows: list[dict], stream: TextIO, fields: tuple[str, ...] = ALL_COLUMNS) -> None:
    # dict はキーの挿入順を保つので、fields の順に並ぶ
    selected = [{key: row.get(key) for key in fields} for row in rows]
    json.dump(selected, stream, ensure_ascii=False, indent=2)
    stream.write("\n")


def _tendency_text(tendency: dict) -> str:
    percent = tendency.get("percent")
    return f"{tendency['category']}: {'-' if percent is None else f'{percent}%'}"


def _csv_cell(column: str, value) -> str:
    """リスト・表の項目はセル内改行でまとめる（区切りに / を使うとカテゴリ名と衝突するため）"""
    if value is None:
        return ""
    if column in ("affinities", "groups"):
        return "\n".join(value)
    if column == "group_tendencies":
        return "\n".join(_tendency_text(t) for t in value)
    if column == "basic_info":
        return "\n".join(f"{key}: {val}" for key, val in value.items())
    return str(value)


def write_csv(
    rows: list[dict],
    stream: TextIO,
    lineterminator: str = "\r\n",
    fields: tuple[str, ...] = ALL_COLUMNS,
) -> None:
    writer = csv.writer(stream, lineterminator=lineterminator)
    writer.writerow(fields)
    for row in rows:
        writer.writerow(_csv_cell(column, row.get(column)) for column in fields)


def write_results(
    rows: list[dict], fmt: str, output: str | None = None, fields: tuple[str, ...] = ALL_COLUMNS
) -> None:
    """output が None なら標準出力、指定があればそのファイルに（上書きで）書き出す"""
    if fmt not in FORMATS:
        raise ValueError(f"未対応の出力形式です: {fmt}")

    if output is None:
        if fmt == "json":
            write_json(rows, sys.stdout, fields)
        else:
            # Windows のテキストモードの標準出力は \n を \r\n に変換するため、\n で書く
            write_csv(rows, sys.stdout, lineterminator="\n", fields=fields)
        sys.stdout.flush()
        return

    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=FILE_ENCODINGS[fmt], newline="" if fmt == "csv" else None) as f:
        if fmt == "json":
            write_json(rows, f, fields)
        else:
            write_csv(rows, f, fields=fields)
