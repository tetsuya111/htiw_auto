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
| `user_profile.py` | 相手ユーザーのユーザーページからプロフィールを取得（シェルのコマンドからはまだ呼ばれない） |
| `chat_reply.py` | Claude API による返信文下書きの生成 |
| `logging_config.py` | `logs/YYYYMMDD_HHMMSS.log` と標準出力へのログ設定 |

## 設計上の注意点

- **ブラウザセッションの共有**: `WithAutoReplyShell` が Playwright・Browser・Page を1つずつ保持し、`_ensure_page()` で遅延起動する。`login` 後に `list` が同じページ（ログイン済みセッション）を使えるのはこのため。ブラウザ操作を伴うコマンドを追加する場合も `_ensure_page()` からページを取得し、独自にブラウザを起動しないこと。終了処理は `_close()` に集約している。
- **コマンドの例外処理**: 各 `do_*` は例外を捕捉してメッセージを表示し、シェル自体は落とさない。新しいコマンドも同じ方針にし、想定外の例外は `logger.exception` で記録する。
- **セレクタはモジュール先頭の定数**: 対象サイトの DOM 構造に依存するセレクタ・パス（`login.py` の `*_BUTTON` 等、`list_items.py` の `ITEM_SELECTOR` 等）はモジュール先頭に定数としてまとめている。サイト側の変更に追従する際はここだけを直す。確認用のHTMLが `sample/htiw_user_page.html` にある。
- **QRログイン**: QRコード画面のスクリーンショットを保存した後、URL から `sign-in-dialog` が消えるまで無期限（`timeout=0`）に待つ。トップページに戻った場合はログイン失敗とみなし `LoginAborted` を送出する（シェルは警告として扱う）。
- **一覧取得はジェネレータ**: `iter_items()` は `/messages?page=N` を順に開き、1件ずつ `{"link", "name", "age"}` の dict を yield する。アイテムが0件のページに達するか、`limit` 件に達したら終了する。シェルは各件を JSON Lines で標準出力に書き出す。ページ遷移前に `LIST_MIN_SLEEP_SECONDS`〜`LIST_MAX_SLEEP_SECONDS` 秒のランダムsleepを入れる。
- **プロフィール取得は bs4 で解析**: `user_profile.py` では、Playwright はページを開いて `page.content()` で HTML を受け取るところまでにとどめ、HTML の解析は BeautifulSoup（`html.parser`）で行う。ページを開く `fetch_user_profile()` と HTML を解析する `parse_user_profile()` を分けているので、解析処理はブラウザなしで確認できる。`fetch_user_profile()` が開くのは1回の呼び出しにつき1ページだけで、sleep は持たない。複数ユーザーを続けて取得するときの待機は呼び出し側で行うこと。プロフィール本文は第三者の個人情報なので、ログには件数と欠けた項目名だけを出す。仕様は [docs/specs/user-profile-scrape/](specs/user-profile-scrape/)。
- **確認用スクリプト**: `PYTHONPATH=src python scripts/check_user_profile.py` で、`sample/htiw_user_page.html` などを使って `parse_user_profile()` の結果を期待値と比べる。期待値と違う項目があれば、終了コード1で終わる。セレクタを直した後に実行すること。
- **返信文の下書き**: `chat_reply.py` は入力 JSON（`[{"sender", "text"}]`）を `sender: text` 形式のテキストに変換し、`SYSTEM_PROMPT` とともに Messages API へ1回だけ送って本文を返す。送信処理は持たない。モデル名は `MODEL` 定数で指定する。プロンプトを変える際は [docs/prompt-guidelines.md](prompt-guidelines.md) に従う（元になった方針は `prompts/chat.md`）。
- **README の表示**: `readme` コマンドは `shell.py` から2階層上（プロジェクトルート）の `README.md` を読む。`shell.py` を別の階層へ移す場合は `README_PATH` も直すこと。
