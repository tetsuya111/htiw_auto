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
- 保存したプロフィールを条件で検索し、JSON / CSV で出力
- プログラム内に対話シェルを内蔵し、起動後にコマンド（`login` / `list` / `save_profiles` / `search_profiles` / `chat` / `readme` / `help` / `exit`）を受け付ける
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
| `LIST_MIN_SLEEP_SECONDS` | 一覧取得時、ページ遷移前に sleep する最小秒数 | - | `1.0` |
| `LIST_MAX_SLEEP_SECONDS` | 一覧取得時、ページ遷移前に sleep する最大秒数 | - | `3.0` |
| `DB_PATH` | プロフィールを保存する SQLite ファイルのパス（`save_profiles` / `search_profiles` で使用） | - | `db.sqlite` |
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
(with_auto_reply) search_profiles                          # 保存したプロフィールをすべて JSON で出力する
(with_auto_reply) search_profiles --min-age 25 --max-age 30 --address 東京
(with_auto_reply) search_profiles --keyword バレエ --min-likes 100 --format csv --output out/result.csv
(with_auto_reply) chat chat.json # チャット履歴(JSON)から返信文の下書きを作成する（送信はしません）
(with_auto_reply) readme         # README を表示する
(with_auto_reply) help           # コマンド一覧・ヘルプを表示する
(with_auto_reply) exit           # シェルを終了する（quit でも可、Ctrl+D も可）
```

`login` を実行すると同じブラウザセッションが維持されるため、続けて `list` を実行すればログイン後の画面から一覧を取得できます。

### `save_profiles` / `search_profiles` コマンド

- `save_profiles [<件数>] [--refresh]` は、ログイン後に実行します。`list` と同じ方法で一覧を取得したあと、相手ごとにユーザーページを開いてプロフィールを DB に保存します。
  - 保存済みの相手は、`--refresh` を付けない限りアクセスせずにスキップします。
  - ユーザーページを開く前には、毎回 `LIST_MIN_SLEEP_SECONDS`〜`LIST_MAX_SLEEP_SECONDS` 秒待ちます。
  - 3人続けて取得に失敗すると、ログインが切れている可能性があるとして中止します。
  - 途中で Ctrl+C を押すと中断してシェルに戻ります。中断までに保存した分は残ります。
- `search_profiles` は、ブラウザを使わずに DB だけを検索します。条件はすべて AND で組み合わせます。オプションの一覧は `help search_profiles` で確認できます。
  - 条件: `--user-id` / `--name` / `--min-age` / `--max-age` / `--address` / `--keyword` / `--min-likes` / `--max-likes`
  - その他: `--limit`（件数の上限）/ `--format json|csv`（出力形式）/ `--output`（出力先ファイル）
  - `--keyword` は、自己紹介文・共通点・好みカード・基本情報の値のいずれかに含まれる文字列で検索します。
  - CSV をファイルに書き出す場合は、Excel で文字化けしないよう BOM 付き UTF-8 で書き出します。

> **注意**: `db.sqlite` と `search_profiles` の出力ファイルには、相手の第三者の個人情報（自己紹介文・基本情報など）が含まれます。共有・公開しないでください。

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
├── db.sqlite                  # 保存したプロフィール（save_profiles 実行時に作成。個人情報を含む）
├── logs/                       # 実行ログの出力先
├── prompts/
│   └── init.md                  # 実装時の設計プロンプト
├── scripts/                     # 確認用スクリプト（サイトにアクセスしない）
│   ├── check_user_profile.py
│   ├── check_profile_save.py
│   └── check_profile_search.py
└── src/with_auto_reply/
    ├── __init__.py
    ├── __main__.py             # エントリーポイント
    ├── shell.py                # 対話シェル（login / list / save_profiles / search_profiles / chat / readme / help / exit）
    ├── config.py               # 環境変数の読み込み・検証
    ├── login.py                # ログイン処理（Playwright）
    ├── list_items.py           # アイテム一覧取得処理（Playwright）
    ├── user_profile.py         # ユーザーページからのプロフィール取得（Playwright + BeautifulSoup）
    ├── profile_collector.py    # 一覧の相手のプロフィールを取得して DB に保存
    ├── profile_db.py           # プロフィール DB（SQLite）の保存・検索
    ├── profile_export.py       # 検索結果の JSON / CSV 出力
    ├── chat_reply.py           # 返信文の下書き生成（Claude API）
    └── logging_config.py       # ログ設定
```
