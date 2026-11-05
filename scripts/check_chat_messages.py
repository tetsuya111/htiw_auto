"""chat_messages.parse_chat_messages の確認用スクリプト

サイトにはアクセスしない。プロジェクトルートから次のように実行する。

    PYTHONPATH=src python scripts/check_chat_messages.py

期待値と違う項目があれば表示し、終了コード 1 で終わる。本文は個人情報を含むため、表示するのは合否だけにする。
"""

import re
import sys
from pathlib import Path

from with_auto_reply.chat_messages import ChatMessage, parse_chat_messages

SAMPLE_PATH = Path(__file__).resolve().parent.parent / "sample" / "user_chat_message_page.html"
TIME_PATTERN = re.compile(r"\b\d{1,2}:\d{2}\b")

failures: list[str] = []


def check(label: str, actual, expected) -> None:
    ok = actual == expected
    print(f"  [{'OK' if ok else 'NG'}] {label}")
    if not ok:
        failures.append(f"{label}: 期待値 {expected!r} / 実際 {actual!r}")


def check_sample() -> None:
    print("1. サンプルHTML")
    messages = parse_chat_messages(SAMPLE_PATH.read_text(encoding="utf-8"))
    check("件数が12件", len(messages), 12)
    check("me が8件", sum(1 for m in messages if m.sender == "me"), 8)
    check("other が4件", sum(1 for m in messages if m.sender == "other"), 4)
    first = messages[0]
    check("先頭は相手", first.sender, "other")
    check("先頭の本文の書き出し", first.text.startswith("初めまして、ほたるです"), True)
    check("先頭の本文に改行が残る", first.text.split("\n")[1], "いいねありがとうございます！")
    check("本文に空行がない", any("" in m.text.split("\n") for m in messages if m.text), False)
    check("本文の前後に空白がない", all(m.text == m.text.strip() for m in messages), True)
    check("本文に送信時刻を含まない", any(TIME_PATTERN.search(m.text) for m in messages), False)
    second = messages[1]
    check("複数段落を改行でつなぐ", len(second.text.split("\n")), 3)
    check("最後は自分", messages[-1].sender, "me")
    check("to_dict() の形", set(first.to_dict()), {"sender", "text"})


def check_edge_cases() -> None:
    print("2. 境界条件")
    html = """
    <div class="messages">
      <div class="message_balloon secret-questions_link-space"><p>メッセージではない</p></div>
      <div class="message_balloon has-message" data-sender="me"><img src="x.png">
        <div class="message_sent-at is-left">01:28</div></div>
      <div class="message_balloon" data-sender="unknown"><p>未知</p></div>
      <div class="message_balloon" data-sender="partner"><div><p>入れ子の p は本文にしない</p></div><p>本文</p></div>
    </div>
    """
    messages = parse_chat_messages(html)
    check("data-sender のない吹き出し・未知の値は除外",
          messages, [ChatMessage("me", ""), ChatMessage("other", "本文")])
    check("吹き出しがなければ空配列", parse_chat_messages("<html><body></body></html>"), [])


def main() -> int:
    check_sample()
    check_edge_cases()
    if failures:
        print(f"\nNG {len(failures)} 件:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("\nすべて OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
