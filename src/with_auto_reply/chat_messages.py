"""チャットページの HTML からメッセージ（送信者と本文）を取り出す（docs/specs/chat-message-parse）

サイトにはアクセスしない。メッセージ本文は第三者とのやり取りなので、ログには件数だけを出すこと。
"""

import logging
from dataclasses import asdict, dataclass
from typing import Literal

from bs4 import BeautifulSoup

from .user_profile import HTML_PARSER, _block_text

logger = logging.getLogger(__name__)

# セレクタ・属性値はここにまとめる（サイトの DOM が変わったらここを直す）
BALLOON_SELECTOR = ".message_balloon[data-sender]"
PARAGRAPH_TAG = "p"
SENDER_ATTRIBUTE = "data-sender"
SENDER_MAP = {"me": "me", "partner": "other"}

Sender = Literal["me", "other"]


@dataclass(frozen=True)
class ChatMessage:
    sender: Sender
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


def _balloon_text(balloon) -> str:
    """吹き出し直下の <p> だけを本文にする（送信時刻・サムネイルは <p> の外にある）"""
    texts = (_block_text(p) for p in balloon.find_all(PARAGRAPH_TAG, recursive=False))
    return "\n".join(text for text in texts if text)


def parse_chat_messages(html: str) -> list[ChatMessage]:
    """チャットページの HTML から、表示順（上が古い）のメッセージを返す"""
    soup = BeautifulSoup(html, HTML_PARSER)
    messages: list[ChatMessage] = []
    for balloon in soup.select(BALLOON_SELECTOR):
        raw_sender = balloon.get(SENDER_ATTRIBUTE)
        sender = SENDER_MAP.get(raw_sender)
        if sender is None:
            logger.warning("未知の送信者の値のため吹き出しを除外します: %s", raw_sender)
            continue
        messages.append(ChatMessage(sender=sender, text=_balloon_text(balloon)))

    logger.debug(
        "チャットメッセージを %d 件取り出しました（自分 %d 件、相手 %d 件）",
        len(messages),
        sum(1 for m in messages if m.sender == "me"),
        sum(1 for m in messages if m.sender == "other"),
    )
    return messages
