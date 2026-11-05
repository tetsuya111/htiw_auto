import logging

import anthropic

logger = logging.getLogger(__name__)

MODEL = "claude-opus-5"

SYSTEM_PROMPT = """あなたはマッチングアプリのチャット返信文の下書きを作成するアシスタントです。
これまでのチャット履歴を踏まえて、次の返信メッセージ案を1つ作成してください。
作成した文章はユーザーが内容を確認したうえで手動で送信するための「下書き」です。

# 目的
- 仲良くなること
- 食事の提案をすること
- 電話の提案をすること

# 仲良くなる方法
- 相手の雰囲気をほめる
- 共通点をみつける

# 雰囲気
- 男
- 以前のチャットと重複した内容を送らない
- 短く簡潔に
- 1、2行でいい
- 最初は仲良くなることを意識する
- 要件を伝える
- 親しい感じ
- 半分ため口
- 相手の気持ちを思いやる
- 相手に寛容である
- 相手を肯定する

# 提案の交渉テクニック
- foot in the door（小さな依頼から始めて徐々に本命の依頼に近づける）
- door in the face（大きめの依頼を提示したうえで、本命の依頼を譲歩案として提示する）
- ハーバード式交渉術（提案の内容と相手の人格を切り離し、相手を否定せずに提案する）

返信メッセージ本文のみを出力してください。説明や前置きは不要です。
"""


def _format_chat_history(chat: list[dict]) -> str:
    lines = []
    for message in chat:
        sender = message.get("sender", "unknown")
        text = message.get("text", "")
        lines.append(f"{sender}: {text}")
    return "\n".join(lines)


def generate_reply_draft(chat: list[dict]) -> str:
    if not chat:
        raise ValueError("チャット履歴が空です")

    client = anthropic.Anthropic()
    history_text = _format_chat_history(chat)

    logger.info("チャット履歴から返信文の下書きを作成します（%d件）", len(chat))

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"# これまでのチャット履歴\n{history_text}\n\n次の返信メッセージを1つ作成してください。",
            }
        ],
    )

    return "".join(block.text for block in response.content if block.type == "text")
