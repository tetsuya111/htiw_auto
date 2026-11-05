# htiw_自動返信

Playwright を用いて出会い系サイトへの自動ログイン・アイテム一覧取得を行う CLI ツールです。

## 機能

- サイトを開き、ログインダイアログを表示
- LINE 連携によるログイン
  - メールアドレス（tid）とパスワード（tpasswd）を入力してログイン
  - QR コードを表示してのログイン（スクリーンショットを保存し、ログイン完了まで待機）
- ログイン後のアイテム一覧取得（ページネーション対応、ページ遷移時にランダム秒数 sleep、取得件数指定可）
- チャット履歴（JSON）から返信文の下書きを生成（Claude API を使用。**下書きの生成のみで自動送信はしません**。内容を確認したうえで手動で送信してください）
- メッセージ一覧の相手のプロフィールを取得して DB（SQLite の `db.sqlite`）に保存（保存済みの相手はスキップ、取得前にランダム秒数 sleep）
- 保存した相手ごとに、チャットで最後に送信したのがどちらか（自分 / 相手 / 未送信）と、自分・相手のメッセージ件数を DB に記録（チャットページを開いて読むだけで、送信はしません）
- 保存したプロフィールを条件で検索し、チャット履歴とあわせて JSON / CSV で出力（出力するキーを指定可）
- プログラム内に対話シェルを内蔵し、起動後にコマンド（`login` / `list` / `save_profiles` / `check_chats` / `search_profiles` / `chat` / `readme` / `help` / `exit`）を受け付ける
  - `login` でブラウザを起動しログインした後、同じセッション（同じブラウザ・ページ）のまま `list` を実行できる
- 実行ログを `./logs/` に出力

## セットアップ

### 1. 依存パッケージのインストール

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. 環境変数の設定

`.env.example` をコピーして `.env` を作成し、値を設定してください。環境変数はシェルから直接指定することもできます（例: `SITE_URL=... python -m with_auto_reply login`）。

```bash
cp .env.example .env
```

| 変数名 | 説明 | 必須 | デフォルト |
| --- | --- | --- | --- |
| `SITE_URL` | ログイン対象サイトの URL | ✅ | - |
| `LOGIN_METHOD` | ログイン方式。`email` または `qr` | - | `email` |
| `LOGIN_EMAIL` | ログイン用メールアドレス（シェルの `login` コマンドでは使用しません） | △ | - |
| `LOGIN_PASSWORD` | ログイン用パスワード（シェルの `login` コマンドでは使用しません） | △ | - |
| `HEADLESS` | ブラウザをヘッドレスで起動するか（`true`/`false`） | - | `false` |
| `QR_SCREENSHOT_PATH` | QR コードのスクリーンショット保存先パス | - | `qr_login.png` |
| `LIST_MIN_SLEEP_SECONDS` | 一覧取得時、ページ遷移前に sleep する最小秒数（`save_profiles` / `check_chats` でも使用） | - | `1.0` |
| `LIST_MAX_SLEEP_SECONDS` | 一覧取得時、ページ遷移前に sleep する最大秒数（`save_profiles` / `check_chats` でも使用） | - | `3.0` |
| `DB_PATH` | プロフィールを保存する SQLite ファイルのパス（`save_profiles` / `check_chats` / `search_profiles` で使用） | - | `db.sqlite` |
| `ANTHROPIC_API_KEY` | `chat` コマンド（返信文下書き生成）で使用する Claude API キー | △ | - |

`ANTHROPIC_API_KEY` は `chat` コマンドを使う場合のみ必要です。`ant auth login` 済みの環境では未設定でも動作します。

## 実行方法

`src` を PYTHONPATH に追加するか、パッケージとしてインストールしてから実行してください。起動すると対話シェルが立ち上がります。

```bash
PYTHONPATH=src python -m with_auto_reply
```

### シェル内コマンド

```
(with_auto_reply) login line email <email>  # LINE 連携（メールアドレス）でログインする（パスワードは実行後に非表示で入力）
(with_auto_reply) login email <email>       # メールアドレスでログインする（ログインボタン押下後、with.is に戻るまでブラウザ操作を任せる）
(with_auto_reply) list           # アイテム一覧を取得する（JSON Lines で標準出力に出力）
(with_auto_reply) list 50        # 取得件数を指定（先頭から50件）
(with_auto_reply) save_profiles            # 一覧の相手のプロフィールを DB に保存する（保存済みはスキップ）
(with_auto_reply) save_profiles 20         # 一覧の先頭20件を対象にする
(with_auto_reply) save_profiles --refresh  # 保存済みの相手も取得し直して上書きする
(with_auto_reply) check_chats              # 保存済みの相手ごとに最後の送信者とメッセージ件数を記録する
(with_auto_reply) check_chats 10           # 取得日時の新しい順に10人だけ確認する
(with_auto_reply) check_chats --user-id 5922955675  # 1人だけ確認する
(with_auto_reply) search_profiles                          # 保存したプロフィールをすべて JSON で出力する
(with_auto_reply) search_profiles --min-age 25 --max-age 30 --address 東京
(with_auto_reply) search_profiles --keyword バレエ --min-likes 100 --format csv --output out/result.csv
(with_auto_reply) search_profiles --fields user_id,nickname,last_sender,total_message_count
(with_auto_reply) chat chat.json # チャット履歴(JSON)から返信文の下書きを作成する（送信はしません）
(with_auto_reply) readme         # README を表示する
(with_auto_reply) help           # コマンド一覧・ヘルプを表示する
(with_auto_reply) exit           # シェルを終了する（quit でも可、Ctrl+D も可）
```

`login` を実行すると同じブラウザセッションが維持されるため、続けて `list` を実行すればログイン後の画面から一覧を取得できます。

### `save_profiles` / `check_chats` / `search_profiles` コマンド

- `save_profiles [<件数>] [--refresh]` は、ログイン後に実行します。`list` と同じ方法で一覧を取得したあと、相手ごとにユーザーページを開いてプロフィールを DB に保存します。
  - 保存済みの相手は、`--refresh` を付けない限りアクセスせずにスキップします。
  - ユーザーページを開く前には、毎回 `LIST_MIN_SLEEP_SECONDS`〜`LIST_MAX_SLEEP_SECONDS` 秒待ちます。
  - 3人続けて取得に失敗すると、ログインが切れている可能性があるとして中止します。
  - 途中で Ctrl+C を押すと中断してシェルに戻ります。中断までに保存した分は残ります。
- `check_chats [<件数>] [--user-id=<ID>]` は、ログイン後に実行します。DB に保存済みの相手ごとにチャットページ（`/messages/<ユーザーID>`）を開き、最後に送信したのがどちらかと、自分・相手のメッセージ件数を DB（テーブル `chat_histories`、1人1行で上書き）に記録します。
  - チャットページは開いて読むだけで、入力・送信はしません。メッセージ本文は保存しません。
  - 最後の送信者は数値で記録します: `0` = 未送信（どちらも送っていない）/ `1` = 自分 / `2` = 相手。
  - メッセージ件数は、チャットページを開いた時点で表示されている分だけを数えます。やり取りが長く、古いメッセージが最初に表示されない場合は実際より少なくなることがあります。
  - 対象は先に `save_profiles` で保存した相手だけです。チャットページを開く前には、毎回 `LIST_MIN_SLEEP_SECONDS`〜`LIST_MAX_SLEEP_SECONDS` 秒待ちます。
  - 3人続けて失敗すると中止します。Ctrl+C で中断でき、それまでの記録は残ります。
  - チャットページを開くことで、相手側に既読が付く可能性があります。
- `search_profiles` は、ブラウザを使わずに DB だけを検索します。条件はすべて AND で組み合わせます。オプションの一覧は `help search_profiles` で確認できます。
  - 条件: `--user-id` / `--name` / `--min-age` / `--max-age` / `--address` / `--keyword` / `--min-likes` / `--max-likes`
  - その他: `--limit`（件数の上限）/ `--format json|csv`（出力形式）/ `--output`（出力先ファイル）/ `--fields`（出力するキーをカンマ区切りで指定。省略時はすべて）
  - 出力には `check_chats` で記録したチャット履歴のキーが含まれます。記録がない相手は `null`（CSV では空）になります。
    - `last_sender`（最後の送信者 0/1/2）/ `chat_checked_at`（確認日時）/ `my_message_count`（自分の件数）/ `other_message_count`（相手の件数）/ `total_message_count`（合計件数。2つの件数の和を検索時に計算）
  - `--fields` に存在しないキーを指定すると、指定できるキーの一覧を表示して何も出力しません。
  - `--keyword` は、自己紹介文・共通点・好みカード・基本情報の値のいずれかに含まれる文字列で検索します。
  - CSV をファイルに書き出す場合は、Excel で文字化けしないよう BOM 付き UTF-8 で書き出します。

> **注意**: `db.sqlite` と `search_profiles` の出力ファイルには、相手の第三者の個人情報（自己紹介文・基本情報・やり取りの状況など）が含まれます。共有・公開しないでください。

### `chat` コマンドの入力形式

チャット履歴は次の形式の JSON 配列ファイルとして用意してください。

```json
[
  {"sender": "them", "text": "こんにちは！"},
  {"sender": "me", "text": "こんにちは、よろしくお願いします！"}
]
```

`chat` コマンドはこの履歴を踏まえた返信文の下書きを1件出力するだけです。**内容を必ず確認し、送信するかどうかはご自身で判断してください。**

## ログ

実行ごとに `./logs/YYYYMMDD_HHMMSS.log` にログが出力されます（標準出力にも同時出力）。

## ディレクトリ構成

```
.
├── .env.example              # 環境変数のサンプル
├── requirements.txt           # 依存パッケージ
├── db.sqlite                  # 保存したプロフィールとチャット履歴（save_profiles 実行時に作成。個人情報を含む）
├── logs/                       # 実行ログの出力先
├── prompts/
│   └── init.md                  # 実装時の設計プロンプト
├── scripts/                     # 確認用スクリプト（サイトにアクセスしない）
│   ├── check_user_profile.py
│   ├── check_profile_save.py
│   ├── check_profile_search.py
│   ├── check_chat_messages.py
│   └── check_chat_history.py
└── src/with_auto_reply/
    ├── __init__.py
    ├── __main__.py             # エントリーポイント
    ├── shell.py                # 対話シェル（login / list / save_profiles / check_chats / search_profiles / chat / readme / help / exit）
    ├── config.py               # 環境変数の読み込み・検証
    ├── login.py                # ログイン処理（Playwright）
    ├── list_items.py           # アイテム一覧取得処理（Playwright）
    ├── user_profile.py         # ユーザーページからのプロフィール取得（Playwright + BeautifulSoup）
    ├── profile_collector.py    # 一覧の相手のプロフィールを取得して DB に保存
    ├── chat_messages.py        # チャットページの HTML からメッセージを取り出す（BeautifulSoup）
    ├── chat_history.py         # 最後の送信者・メッセージ件数の判定と記録（check_chats）
    ├── profile_db.py           # プロフィール・チャット履歴 DB（SQLite）の保存・検索
    ├── profile_export.py       # 検索結果の JSON / CSV 出力
    ├── chat_reply.py           # 返信文の下書き生成（Claude API）
    └── logging_config.py       # ログ設定
```
