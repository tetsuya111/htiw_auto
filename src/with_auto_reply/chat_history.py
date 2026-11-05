"""保存済みの相手ごとに、チャットの最後の送信者とメッセージ件数を記録する（docs/specs/chat-history-check）

チャットページは開いて読むだけで、入力・送信などの操作はしない。
メッセージ本文は DB にもログにも書かないこと。
"""

import logging
import random
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import Iterator, Literal
from urllib.parse import urljoin

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from . import profile_db
from .chat_messages import ChatMessage, parse_chat_messages
from .profile_collector import MAX_CONSECUTIVE_FAILURES, TooManyFailures

logger = logging.getLogger(__name__)

CHAT_PAGE_PATH = "/messages/{user_id}"
# メッセージの枠。メッセージが0件でもこの要素はある前提で、「0件」と「ページを読めない」を区別する
MESSAGES_CONTAINER_SELECTOR = ".messages"
MESSAGES_WAIT_TIMEOUT_MS = 10_000


class ChatPageNotFound(RuntimeError):
    """チャットページを開けない、またはチャットページとして読めない"""


class LastSender(IntEnum):
    NONE = 0  # 未送信
    ME = 1  # 自分
    OTHER = 2  # 相手


LAST_SENDER_LABELS = {LastSender.NONE: "未送信", LastSender.ME: "自分", LastSender.OTHER: "相手"}


@dataclass(frozen=True)
class ChatSummary:
    last_sender: LastSender
    my_count: int
    other_count: int

    @property
    def total_count(self) -> int:
        """合計件数。保存せず、返すときに計算する"""
        return self.my_count + self.other_count


@dataclass(frozen=True)
class CheckResult:
    status: Literal["checked", "failed"]
    user_id: str
    nickname: str | None
    summary: ChatSummary | None = None
    reason: str | None = None


def summarize_chat(messages: list[ChatMessage]) -> ChatSummary:
    """最後の要素の送信者で最後の送信者を判定し（空なら未送信）、送信者ごとの件数を数える"""
    my_count = sum(1 for m in messages if m.sender == "me")
    other_count = len(messages) - my_count
    if not messages:
        last_sender = LastSender.NONE
    elif messages[-1].sender == "me":
        last_sender = LastSender.ME
    else:
        last_sender = LastSender.OTHER
    return ChatSummary(last_sender=last_sender, my_count=my_count, other_count=other_count)


def fetch_chat_messages(page: Page, base_url: str, user_id: str) -> list[ChatMessage]:
    """チャットページを1回だけ開いてメッセージを返す。sleep は呼び出し側で行うこと"""
    url = urljoin(base_url, CHAT_PAGE_PATH.format(user_id=user_id))
    page.goto(url)
    try:
        page.locator(MESSAGES_CONTAINER_SELECTOR).first.wait_for(
            state="attached", timeout=MESSAGES_WAIT_TIMEOUT_MS
        )
    except PlaywrightTimeoutError as e:
        raise ChatPageNotFound("チャットページを読めません") from e
    return parse_chat_messages(page.content())


def check_chats(
    page: Page,
    conn: sqlite3.Connection,
    base_url: str,
    targets: list[tuple[str, str]],
    min_sleep_seconds: float = 1.0,
    max_sleep_seconds: float = 3.0,
) -> Iterator[CheckResult]:
    """targets の (user_id, nickname) を1人ずつ確認し、結果を yield する"""
    consecutive_failures = 0
    for user_id, nickname in targets:
        # 対象サイトへの負荷・アクセス検知を避けるため、ページを開く前に毎回待つ
        time.sleep(random.uniform(min_sleep_seconds, max_sleep_seconds))
        try:
            summary = summarize_chat(fetch_chat_messages(page, base_url, user_id))
            profile_db.upsert_chat_history(conn, user_id, summary, datetime.now())
        except Exception as exc:
            consecutive_failures += 1
            logger.warning("ユーザー %s のチャット確認に失敗しました: %s", user_id, exc)
            yield CheckResult("failed", user_id, nickname, reason=str(exc))
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                raise TooManyFailures(
                    f"{MAX_CONSECUTIVE_FAILURES} 人連続でチャットの確認に失敗しました"
                ) from exc
            continue

        consecutive_failures = 0
        logger.info(
            "ユーザー %s のチャットを記録しました（最後の送信者=%d、自分 %d 件、相手 %d 件）",
            user_id,
            summary.last_sender,
            summary.my_count,
            summary.other_count,
        )
        yield CheckResult("checked", user_id, nickname, summary=summary)
