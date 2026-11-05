"""user_profile.parse_user_profile() の確認用スクリプト

ブラウザもネットワークも使わない。プロジェクトルートから次のように実行する。

    PYTHONPATH=src python scripts/check_user_profile.py

期待値と違う項目があれば表示し、終了コード 1 で終わる。
"""

import json
import logging
import sys
import time
from pathlib import Path

from with_auto_reply.user_profile import (
    GroupTendency,
    UserProfileNotFound,
    parse_user_profile,
)

SAMPLE_PATH = Path(__file__).resolve().parent.parent / "sample" / "htiw_user_page.html"
MINIMAL_HTML = '<div class="profile_main-nickname">nick</div>'
NO_NICKNAME_HTML = "<html><body><p>トップページ</p></body></html>"
MINIMAL_TIME_LIMIT_SECONDS = 1.0

EXPECTED_BASIC_INFO = {
    "ニックネーム": "rye",
    "年齢": "28歳",
    "兄弟姉妹": "長女",
    "居住地": "東京",
    "勤務地": "東京",
    "出身地": "東京",
    "学歴": "大学卒",
    "職種": "事務",
    "身長": "160cm",
    "体型": "スリム",
    "結婚歴": "未婚",
    "子供の有無": "なし",
    "結婚に対する意思": "良い人がいればしたい",
    "子供が欲しいか": "いいえ",
    "家事・育児": "二人で協力したい",
    "出会うまでの希望": "会う前に通話したい",
    "同居人": "一人暮らし",
    "休日": "土日",
    "お酒": "飲まない",
    "タバコ": "吸わない",
}

failures: list[str] = []


def check(label: str, actual, expected) -> None:
    ok = actual == expected
    print(f"  [{'OK' if ok else 'NG'}] {label}")
    if not ok:
        failures.append(f"{label}: 期待値 {expected!r} / 実際 {actual!r}")


def check_sample() -> None:
    print("1. サンプルHTML")
    profile = parse_user_profile(SAMPLE_PATH.read_text(encoding="utf-8"))
    print(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2))

    intro = profile.introduction or ""
    check("ユーザーID", profile.user_id, "6251609526")
    check("ニックネーム", profile.nickname, "rye")
    check("年齢", profile.age, "28歳")
    check("居住地", profile.address, "東京")
    check("最終ログイン", profile.last_online, "24時間以内")
    check("いいね数", profile.likes_count, 215)
    check(
        "自己紹介文の始まりと終わり",
        (intro.startswith("はじめまして！"), intro.endswith("お気楽に声をかけてください。")),
        (True, True),
    )
    check(
        "共通点",
        profile.affinities,
        ("散歩デートが好き", "土日休み", "タバコ吸わない", "東京勤務", "一人暮らし同士"),
    )
    check(
        "好みカード",
        profile.groups,
        (
            "散歩デートが好き",
            "スターバックス大好き集まれ",
            "バレエ♥大好き！",
            "金沢21世紀美術館",
            "K-POP",
            "K-POP好き(^^)",
            "名探偵コナン",
            "建物好き",
        ),
    )
    check(
        "登録傾向",
        profile.group_tendencies,
        (
            GroupTendency("アート", 38),
            GroupTendency("音楽", 25),
            GroupTendency("旅行", 13),
            GroupTendency("グルメ", 13),
            GroupTendency("アニメ/マンガ", 13),
        ),
    )
    check("基本情報（20行・順序込み）", list(profile.basic_info.items()), list(EXPECTED_BASIC_INFO.items()))
    check("結婚歴に制御文字がない", profile.basic_info.get("結婚歴"), "未婚")
    check("JSONに変換できる", isinstance(json.dumps(profile.to_dict(), ensure_ascii=False), str), True)


def check_minimal() -> None:
    print("2. ニックネームだけのHTML")
    start = time.perf_counter()
    profile = parse_user_profile(MINIMAL_HTML)
    elapsed = time.perf_counter() - start
    check(f"{MINIMAL_TIME_LIMIT_SECONDS}秒以内に終わる（{elapsed:.3f}秒）", elapsed <= MINIMAL_TIME_LIMIT_SECONDS, True)
    check(
        "単一の値がすべて None",
        (profile.age, profile.address, profile.last_online, profile.likes_count, profile.introduction),
        (None,) * 5,
    )
    check(
        "リスト・表がすべて空",
        (profile.affinities, profile.groups, profile.group_tendencies, profile.basic_info),
        ((), (), (), {}),
    )


def check_no_nickname() -> None:
    print("3. ニックネームのないHTML")
    try:
        parse_user_profile(NO_NICKNAME_HTML)
    except UserProfileNotFound:
        check("UserProfileNotFound が送出される", True, True)
    else:
        check("UserProfileNotFound が送出される", False, True)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    check_sample()
    check_minimal()
    check_no_nickname()

    if failures:
        print("\n失敗:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("\nすべて成功しました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
