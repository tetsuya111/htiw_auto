"""メッセージ一覧の相手のプロフィールを取得して DB に保存する（docs/specs/profile-save）"""

import logging
import random
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator, Literal

from playwright.sync_api import Page

from . import profile_db
from .list_items import iter_items
from .user_profile import fetch_user_profile

logger = logging.getLogger(__name__)

# 一覧の link（例: /messages/6251609526）からユーザーIDを取り出す
USER_ID_PATTERN = re.compile(r"/(?:messages|users)/(\d+)")
MAX_CONSECUTIVE_FAILURES = 3


class TooManyFailures(RuntimeError):
    """プロフィール取得が連続で失敗した（ログイン切れなどの可能性）"""


@dataclass(frozen=True)
class SaveResult:
    status: Literal["saved", "skipped", "failed"]
    link: str | None
    user_id: str | None
    nickname: str | None
    reason: str | None = None


def extract_user_id(link: str | None) -> str | None:
    if not link:
        return None
    match = USER_ID_PATTERN.search(link)
    return match.group(1) if match else None


def save_profiles(
    page: Page,
    conn: sqlite3.Connection,
    base_url: str,
    limit: int | None = None,
    refresh: bool = False,
    min_sleep_seconds: float = 1.0,
    max_sleep_seconds: float = 3.0,
) -> Iterator[SaveResult]:
    """一覧の各相手について、保存・スキップ・失敗の結果を1件ずつ yield する"""
    # iter_items() は同じ page を読みながら yield するため、ユーザーページへ遷移する前に全件取得しておく
    items = list(
        iter_items(
            page,
            base_url,
            limit=limit,
            min_sleep_seconds=min_sleep_seconds,
            max_sleep_seconds=max_sleep_seconds,
        )
    )
    logger.info("一覧から %d 件を取得しました（refresh=%s）", len(items), refresh)

    consecutive_failures = 0
    for item in items:
        link = item.get("link")
        name = item.get("name")
        user_id = extract_user_id(link)
        if user_id is None:
            logger.warning("link からユーザーIDを取り出せません: %s", link)
            yield SaveResult("failed", link, None, name, "ユーザーIDを取り出せません")
            continue

        if not refresh and profile_db.exists(conn, user_id):
            logger.info("ユーザー %s は保存済みのためスキップします", user_id)
            yield SaveResult("skipped", link, user_id, name)
            continue

        time.sleep(random.uniform(min_sleep_seconds, max_sleep_seconds))
        try:
            profile = fetch_user_profile(page, base_url, user_id)
            profile_db.upsert_profile(conn, profile, link, datetime.now())
        except Exception as exc:
            consecutive_failures += 1
            logger.warning("ユーザー %s のプロフィール取得に失敗しました: %s", user_id, exc)
            yield SaveResult("failed", link, user_id, name, str(exc))
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                raise TooManyFailures(
                    f"{MAX_CONSECUTIVE_FAILURES} 人連続でプロフィール取得に失敗しました"
                ) from exc
            continue

        consecutive_failures = 0
        logger.info("ユーザー %s のプロフィールを保存しました", user_id)
        yield SaveResult("saved", link, user_id, profile.nickname)
