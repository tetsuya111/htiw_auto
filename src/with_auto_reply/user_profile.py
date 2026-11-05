"""相手ユーザーのユーザーページ（/users/<ID>）からプロフィールを取得する

Playwright はページを開いて HTML を取得するところまでに使い、
HTML の解析は BeautifulSoup（bs4）で行う。
"""

import logging
import re
import unicodedata
from dataclasses import asdict, dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup, NavigableString, Tag
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger(__name__)

USER_PAGE_PATH = "/users/{user_id}"
HTML_PARSER = "html.parser"
NICKNAME_WAIT_TIMEOUT_MS = 10_000

USER_ID_SELECTOR = ".user_actions[data-user-id]"
NICKNAME_SELECTOR = ".profile_main-nickname"
AGE_ADDRESS_SELECTOR = ".profile_main-age-address"
LAST_ONLINE_SELECTOR = ".profile_last-online"
LIKES_COUNT_SELECTOR = ".user-likes-count"
INTRODUCTION_SELECTOR = ".profile-introduction_content"
AFFINITY_SELECTOR = ".profile-affinities_list .profile-affinity"
GROUP_TITLE_SELECTOR = ".profile-groups .group-card_title"
TENDENCY_ITEM_SELECTOR = ".profile-groups_tendency_item"
TENDENCY_NAME_SELECTOR = ".profile-groups_tendency_name"
TENDENCY_RATE_SELECTOR = ".profile-groups_tendency_rate"
BASIC_INFO_ROW_SELECTOR = ".profile-detail_lists tr"

AGE_ADDRESS_SEPARATOR = re.compile(r"\s+")
WHITESPACE = re.compile(r"\s+")
DIGITS = re.compile(r"\d+")


class UserProfileNotFound(RuntimeError):
    """ユーザーページを開けていない（ニックネームの要素がない）"""


@dataclass(frozen=True)
class GroupTendency:
    category: str
    percent: int | None


@dataclass(frozen=True)
class UserProfile:
    user_id: str
    nickname: str
    age: str | None
    address: str | None
    last_online: str | None
    likes_count: int | None
    introduction: str | None
    affinities: tuple[str, ...]
    groups: tuple[str, ...]
    group_tendencies: tuple[GroupTendency, ...]
    basic_info: dict[str, str]

    def to_dict(self) -> dict:
        """JSON に変換できる dict を返す（tuple は list になる）"""
        data = asdict(self)
        for key in ("affinities", "groups", "group_tendencies"):
            data[key] = list(data[key])
        return data


def _clean(text: str) -> str:
    """書式文字（U+200E など Unicode カテゴリ Cf）を除き、前後の空白を取り除く"""
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf").strip()


def _text_or_none(soup: BeautifulSoup, selector: str) -> str | None:
    element = soup.select_one(selector)
    if element is None:
        return None
    return _clean(element.get_text()) or None


def _texts(soup: BeautifulSoup, selector: str) -> tuple[str, ...]:
    texts = (_clean(element.get_text()) for element in soup.select(selector))
    return tuple(text for text in texts if text)


def _to_int_or_none(text: str | None) -> int | None:
    if text is None:
        return None
    match = DIGITS.search(text)
    return int(match.group()) if match else None


def _split_age_address(text: str | None) -> tuple[str | None, str | None]:
    if text is None:
        return None, None
    parts = AGE_ADDRESS_SEPARATOR.split(_clean(text), maxsplit=1)
    age = parts[0] or None
    address = parts[1] if len(parts) == 2 else None
    return age, address


def _block_text(element: Tag) -> str:
    """ブラウザの表示に合わせ、ソース上の改行・連続空白は空白1つに、<br> は改行にする"""
    chunks = []
    for node in element.descendants:
        if isinstance(node, NavigableString):
            chunks.append(WHITESPACE.sub(" ", str(node)))
        elif node.name == "br":
            chunks.append("\n")
    lines = (_clean(line) for line in "".join(chunks).split("\n"))
    return "\n".join(lines).strip("\n")


def _introduction_text(soup: BeautifulSoup) -> str | None:
    element = soup.select_one(INTRODUCTION_SELECTOR)
    if element is None:
        return None
    paragraphs = element.find_all("p")
    if paragraphs:
        texts = (_block_text(p) for p in paragraphs)
        text = "\n".join(t for t in texts if t)
    else:
        text = _block_text(element)
    return text or None


def _group_tendencies(soup: BeautifulSoup) -> tuple[GroupTendency, ...]:
    tendencies = []
    for item in soup.select(TENDENCY_ITEM_SELECTOR):
        category = _text_or_none(item, TENDENCY_NAME_SELECTOR)
        if category is None:
            continue
        percent = _to_int_or_none(_text_or_none(item, TENDENCY_RATE_SELECTOR))
        tendencies.append(GroupTendency(category=category, percent=percent))
    return tuple(tendencies)


def _basic_info(soup: BeautifulSoup) -> dict[str, str]:
    info = {}
    for row in soup.select(BASIC_INFO_ROW_SELECTOR):
        header = row.find("th")
        value = row.find("td")
        if header is None or value is None:
            continue
        key = _clean(header.get_text())
        if key:
            info[key] = _clean(value.get_text())
    return info


def _user_id_from_html(soup: BeautifulSoup) -> str:
    element = soup.select_one(USER_ID_SELECTOR)
    if element is None:
        return ""
    return _clean(str(element.get("data-user-id", "")))


def parse_user_profile(html: str, user_id: str | None = None) -> UserProfile:
    """ユーザーページの HTML を解析してプロフィールを返す（ブラウザ・ネットワークを使わない）"""
    soup = BeautifulSoup(html, HTML_PARSER)

    nickname = _text_or_none(soup, NICKNAME_SELECTOR)
    if nickname is None:
        raise UserProfileNotFound("ニックネームが見つかりません（ユーザーページではない可能性があります）")

    age, address = _split_age_address(_text_or_none(soup, AGE_ADDRESS_SELECTOR))
    profile = UserProfile(
        user_id=user_id or _user_id_from_html(soup),
        nickname=nickname,
        age=age,
        address=address,
        last_online=_text_or_none(soup, LAST_ONLINE_SELECTOR),
        likes_count=_to_int_or_none(_text_or_none(soup, LIKES_COUNT_SELECTOR)),
        introduction=_introduction_text(soup),
        affinities=_texts(soup, AFFINITY_SELECTOR),
        groups=_texts(soup, GROUP_TITLE_SELECTOR),
        group_tendencies=_group_tendencies(soup),
        basic_info=_basic_info(soup),
    )
    _log_result(profile)
    return profile


def _log_result(profile: UserProfile) -> None:
    """件数と欠けた項目名だけを記録する（プロフィール本文は個人情報なので出さない）"""
    logger.info(
        "ユーザー %s のプロフィールを解析しました（共通点 %d 件、好みカード %d 件、登録傾向 %d 件、基本情報 %d 件）",
        profile.user_id or "(ID不明)",
        len(profile.affinities),
        len(profile.groups),
        len(profile.group_tendencies),
        len(profile.basic_info),
    )
    missing = [
        name
        for name, value in (
            ("年齢", profile.age),
            ("居住地", profile.address),
            ("最終ログイン", profile.last_online),
            ("いいね数", profile.likes_count),
            ("自己紹介文", profile.introduction),
            ("共通点", profile.affinities),
            ("好みカード", profile.groups),
            ("登録傾向", profile.group_tendencies),
            ("基本情報", profile.basic_info),
        )
        if value is None or value == () or value == {}
    ]
    if missing:
        logger.warning("取得できなかった項目があります: %s", "、".join(missing))


def fetch_user_profile(page: Page, base_url: str, user_id: str) -> UserProfile:
    """ユーザーページを1回だけ開き、HTML を取得して parse_user_profile() に渡す

    sleep は入れない。複数ユーザーを続けて取得する場合の待機は呼び出し側で行うこと。
    """
    url = urljoin(base_url, USER_PAGE_PATH.format(user_id=user_id))
    logger.info("ユーザー %s のプロフィールを取得します", user_id)
    page.goto(url)

    try:
        page.locator(NICKNAME_SELECTOR).first.wait_for(timeout=NICKNAME_WAIT_TIMEOUT_MS)
    except PlaywrightTimeoutError as e:
        raise UserProfileNotFound(f"ユーザーページを開けませんでした: {page.url}") from e

    return parse_user_profile(page.content(), user_id)
