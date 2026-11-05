# アーキテクチャ

Playwright（同期API）によるブラウザ操作と、Anthropic SDK による返信文下書き生成を、標準ライブラリ `cmd` の対話シェルから呼び出す構成。パッケージは `src/with_auto_reply/`。

## セットアップ

```bash
python -m venv venv
./venv/Scripts/activate      # PowerShellの場合: venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
cp .env.example .env         # 必要に応じて内容を調整
```

## 実行方法

```bash
PYTHONPATH=src python -m with_auto_reply   # 対話シェルを起動
```

Windows では `run.bat` を使う。プロジェクトルートへ移動し、`PYTHONPATH` と UTF-8 出力（`PYTHONUTF8` / `PYTHONIOENCODING`）を設定してから起動する。`.env` と `logs/` はカレントディレクトリ基準で解決されるため、**必ずプロジェクトルートから起動すること**（`src/` から起動すると `src/logs/` にログが出てしまう）。

自動テストは現状存在しない。動作確認は実際にシェルを起動して行う。`chat` コマンドは `data/test_chat.json` を入力にして確認できる。

## 設定

設定はすべて環境変数で、`config.py` が `python-dotenv` で `.env` を読み込む（シェルで指定した値が優先される）。変数一覧は [README.md](../README.md) の環境変数表を参照。

- 環境変数の読み込みと検証は `config.py` の `load_login_config()` / `load_list_config()` に集約し、各モジュールで `os.environ` を直接読まないこと。設定は `frozen=True` の dataclass として受け渡す。
- 設定はコマンド実行のたびに読み込み直す。ただし `HEADLESS` はブラウザ起動時（最初の `login` / `list`）にしか反映されない。
- `ANTHROPIC_API_KEY` は `config.py` を経由せず、`anthropic.Anthropic()` が環境変数から直接読む。

## モジュール構成

| モジュール | 役割 |
| --- | --- |
| `__main__.py` | エントリーポイント（`shell.main()` を呼ぶだけ） |
| `shell.py` | 対話シェル。ブラウザのライフサイクルとコマンドのエラーハンドリングを担う |
| `config.py` | 環境変数の読み込み・検証 |
| `login.py` | ログイン処理（メール / QR） |
| `list_items.py` | メッセージ一覧の取得（ページネーション） |
| `user_profile.py` | 相手ユーザーのユーザーページからプロフィールを取得 |
| `profile_collector.py` | 一覧の相手のプロフィールを取得して DB に保存（`save_profiles`） |
| `chat_messages.py` | チャットページの HTML からメッセージ（送信者・本文）を取り出す |
| `chat_history.py` | 最後の送信者・メッセージ件数の判定と記録（`check_chats`） |
| `profile_db.py` | プロフィール・チャット履歴 DB（SQLite）の接続・保存・検索 |
| `profile_export.py` | 検索結果の JSON / CSV 出力（`search_profiles`） |
| `chat_reply.py` | Claude API による返信文下書きの生成 |
| `logging_config.py` | `logs/YYYYMMDD_HHMMSS.log` と標準出力へのログ設定 |

## 設計上の注意点

- **ブラウザセッションの共有**: `WithAutoReplyShell` が Playwright・Browser・Page を1つずつ保持し、`_ensure_page()` で遅延起動する。`login` 後に `list` が同じページ（ログイン済みセッション）を使えるのはこのため。ブラウザ操作を伴うコマンドを追加する場合も `_ensure_page()` からページを取得し、独自にブラウザを起動しないこと。終了処理は `_close()` に集約している。
- **コマンドの例外処理**: 各 `do_*` は例外を捕捉してメッセージを表示し、シェル自体は落とさない。新しいコマンドも同じ方針にし、想定外の例外は `logger.exception` で記録する。
- **セレクタはモジュール先頭の定数**: 対象サイトの DOM 構造に依存するセレクタ・パス（`login.py` の `*_BUTTON` 等、`list_items.py` の `ITEM_SELECTOR` 等）はモジュール先頭に定数としてまとめている。サイト側の変更に追従する際はここだけを直す。確認用のHTMLが `sample/htiw_user_page.html` にある。
- **QRログイン**: QRコード画面のスクリーンショットを保存した後、URL から `sign-in-dialog` が消えるまで無期限（`timeout=0`）に待つ。トップページに戻った場合はログイン失敗とみなし `LoginAborted` を送出する（シェルは警告として扱う）。
- **一覧取得はジェネレータ**: `iter_items()` は `/messages?page=N` を順に開き、1件ずつ `{"link", "name", "age"}` の dict を yield する。アイテムが0件のページに達するか、`limit` 件に達したら終了する。シェルは各件を JSON Lines で標準出力に書き出す。ページ遷移前に `LIST_MIN_SLEEP_SECONDS`〜`LIST_MAX_SLEEP_SECONDS` 秒のランダムsleepを入れる。
- **プロフィール取得は bs4 で解析**: `user_profile.py` では、Playwright はページを開いて `page.content()` で HTML を受け取るところまでにとどめ、HTML の解析は BeautifulSoup（`html.parser`）で行う。ページを開く `fetch_user_profile()` と HTML を解析する `parse_user_profile()` を分けているので、解析処理はブラウザなしで確認できる。`fetch_user_profile()` が開くのは1回の呼び出しにつき1ページだけで、sleep は持たない。複数ユーザーを続けて取得するときの待機は呼び出し側で行うこと。プロフィール本文は第三者の個人情報なので、ログには件数と欠けた項目名だけを出す。仕様は [docs/specs/user-profile-scrape/](specs/user-profile-scrape/)。
- **プロフィールの保存（`save_profiles`）**: `profile_collector.save_profiles()` は、`iter_items()` の結果を**先にすべて list にしてから**ユーザーページを開く。`iter_items()` は同じページの locator を読みながら yield するため、途中でページを遷移すると一覧の残りが読めなくなるからである。
  - 保存済みのユーザーIDはアクセスせずにスキップする。
  - ユーザーページを開く前には、毎回 `LIST_*_SLEEP_SECONDS` の待機を入れる。
  - 3人連続で失敗したら `TooManyFailures` で中止する。
  - 1人ごとに commit する。
  - `do_save_profiles` は `KeyboardInterrupt` を自分で捕捉して、シェルに戻る。
  - 一覧の `link` からユーザーIDを取り出す正規表現は `USER_ID_PATTERN`（`/messages/<ID>` を想定）。仕様は [docs/specs/profile-save/](specs/profile-save/)。
- **プロフィール DB**: `profile_db.py` の `profiles` テーブル（1人1行）。共通点・好みカード（列名 `group_cards`）・登録傾向・基本情報は JSON 文字列の列で持つ。年齢の範囲検索用に `age_years` 列を持つ。
  - SQL の値は必ずプレースホルダで渡す。
  - 検索のキーワードは `json_each()` で JSON の値だけを照合する。基本情報の項目名に一致させないためである。
  - 検索は `connect_readonly()`（`mode=ro`）で開き、DBファイルがなければ作らずに `DbNotFound` を送出する。
  - 仕様は [docs/specs/profile-search/](specs/profile-search/)。
- **チャットメッセージの解析**: `chat_messages.parse_chat_messages()` は `.message_balloon[data-sender]` を文書順に取り出し、`data-sender` の `me` / `partner` を `me` / `other` に読み替える。本文は吹き出し直下の `<p>` だけから取る（送信時刻・サムネイルを含めないため）。本文の整形は `user_profile._block_text()` を使い回す。HTML に含まれている分だけを対象にし、古いメッセージを遡って読み込むことはしない。仕様は [docs/specs/chat-message-parse/](specs/chat-message-parse/)。
- **チャット履歴（`check_chats`）**: `chat_history.check_chats()` は `save_profiles()` と同じ構造（相手ごとにランダムsleep → `/messages/<user_id>` を開く → 1人ごとに commit、3人連続失敗で `TooManyFailures`）。`.messages` が現れなければ `ChatPageNotFound` とし、メッセージ0件（未送信）と区別する。ページ上でクリック・入力はしない。
  - テーブル `chat_histories` は `profile_id`（UNIQUE、`profiles.user_id` への外部キー）で1人1行。`last_sender`（0 未送信 / 1 自分 / 2 相手）と `my_message_count` / `other_message_count`、`checked_at` を持つ。合計件数は保存せず、読み出すときに和で求める。
  - `profile_db.connect()` は `PRAGMA foreign_keys = ON` を実行し、`profiles` と `chat_histories` を `CREATE TABLE IF NOT EXISTS` する（既存のDBにもテーブルが追加される）。
  - `profile_db` から `chat_history` は型注釈（`TYPE_CHECKING`）でだけ参照する。`chat_history` が `profile_db` を import するため、循環 import を避ける。
  - 仕様は [docs/specs/chat-history-check/](specs/chat-history-check/)。
- **検索結果のチャット履歴と `--fields`**: `search_profiles()` は `profiles AS p` に `chat_histories AS c` を LEFT JOIN し、末尾に `last_sender` / `chat_checked_at` / `my_message_count` / `other_message_count` / `total_message_count` を加える。`chat_histories` がない古いDB（読み取り専用なので作れない）では `sqlite_master` で確かめ、JOIN せずに `NULL AS ...` を返す。WHERE 句の列名は `p.` 付きにする。出力するキーは `profile_export.ALL_COLUMNS` が正で、`--fields` は `parse_fields()` でこれと照合し、書き出しの直前だけで絞る。仕様は [docs/specs/profile-search-chat-fields/](specs/profile-search-chat-fields/)。
- **検索結果の出力**: ログは標準エラーに出る（`logging_config.py` の `StreamHandler()`）。そのため、`search_profiles` が標準出力に出すのは結果だけにし、他のツールにそのまま渡せるようにする。CSV は、ファイルなら BOM 付き UTF-8 と `\r\n`、標準出力なら `\n` で書く。Windows では標準出力の `\n` が `\r\n` に変換されるためである。
- **確認用スクリプト**: `scripts/` 配下のスクリプトは、サイトにアクセスせずに期待値と比べ、違う項目があれば終了コード1で終わる。プロジェクトルートから `PYTHONPATH=src python scripts/<名前>.py` で実行する。
  - `check_user_profile.py`: `sample/htiw_user_page.html` を `parse_user_profile()` で解析した結果を確かめる。セレクタを直した後に実行すること。
  - `check_profile_save.py`: DB への保存と `save_profiles()` の流れを確かめる。一覧・プロフィール取得・sleep は差し替える。
  - `check_profile_search.py`: 検索条件・JSON / CSV 出力・性能（1,000件）・チャット履歴のキーと `--fields` を確かめる。
  - `check_chat_messages.py`: `sample/user_chat_message_page.html` を `parse_chat_messages()` で解析した結果を確かめる。
  - `check_chat_history.py`: 最後の送信者・件数の判定、`chat_histories` の保存、`check_chats()` の流れを確かめる。ページは偽のオブジェクトで差し替える。
- **返信文の下書き**: `chat_reply.py` は入力 JSON（`[{"sender", "text"}]`）を `sender: text` 形式のテキストに変換し、`SYSTEM_PROMPT` とともに Messages API へ1回だけ送って本文を返す。送信処理は持たない。モデル名は `MODEL` 定数で指定する。プロンプトを変える際は [docs/prompt-guidelines.md](prompt-guidelines.md) に従う（元になった方針は `prompts/chat.md`）。
- **README の表示**: `readme` コマンドは `shell.py` から2階層上（プロジェクトルート）の `README.md` を読む。`shell.py` を別の階層へ移す場合は `README_PATH` も直すこと。
