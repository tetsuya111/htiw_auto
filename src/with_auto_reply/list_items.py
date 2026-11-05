import logging
import random
import time
from typing import Iterator
from urllib.parse import urljoin

from playwright.sync_api import Page

logger = logging.getLogger(__name__)

ITEM_PAGE_PATH = "/messages"
ITEM_SELECTOR = ".topic-list"
LINK_SELECTOR = "a.topic_contents"
NAME_SELECTOR = ".topic_nickname"
AGE_SELECTOR = ".topic_age-address"


def _build_page_url(base_url: str, page_number: int) -> str:
    items_url = urljoin(base_url, ITEM_PAGE_PATH)
    return f"{items_url}?page={page_number}"


def iter_items(
    page: Page,
    base_url: str,
    limit: int | None = None,
    start_page: int = 1,
    min_sleep_seconds: float = 1.0,
    max_sleep_seconds: float = 3.0,
) -> Iterator[dict]:
    count = 0
    page_number = start_page

    while limit is None or count < limit:
        if page_number > start_page:
            time.sleep(random.uniform(min_sleep_seconds, max_sleep_seconds))

        logger.info("ページ %d を取得します", page_number)
        page.goto(_build_page_url(base_url, page_number))

        items = page.locator(ITEM_SELECTOR)
        item_count = items.count()
        if item_count == 0:
            logger.info("ページ %d にアイテムがないため終了します", page_number)
            return

        for i in range(item_count):
            if limit is not None and count >= limit:
                return

            item = items.nth(i)
            yield {
                "link": item.locator(LINK_SELECTOR).get_attribute("href"),
                "name": item.locator(NAME_SELECTOR).inner_text(),
                "age": item.locator(AGE_SELECTOR).inner_text(),
            }
            count += 1

        page_number += 1
