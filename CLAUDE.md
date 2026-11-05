# CLAUDE.md

このファイルは、このリポジトリで作業する Claude Code (claude.ai/code) 向けのガイドです。

**このファイルおよび今後の追記・更新はすべて日本語で記述すること。**

## プロジェクト概要

Playwright（同期API）でサイトへのログイン・メッセージ一覧取得を行い、Claude API でチャット返信文の**下書き**を生成する Python 製の CLI ツール。`python -m with_auto_reply`（Windows では `run.bat`）で対話シェルが起動し、`login` / `list` / `chat` などのコマンドを受け付ける。利用者向けの説明は [README.md](README.md) にある。

## ドキュメント一覧

詳細は各ドキュメントに一本化しており、このファイルはそこへの索引を兼ねる。新しい詳細情報を追記する際は、このファイルに直接書かず該当ドキュメントを更新すること。

- [docs/architecture.md](docs/architecture.md) — セットアップ、実行方法、設定、モジュール構成と設計上の注意点
- [docs/prompt-guidelines.md](docs/prompt-guidelines.md) — プロンプト（`prompts/`、`chat_reply.py` のシステムプロンプト）・Markdownファイル作成の指針
- [docs/requirements-best-practices.md](docs/requirements-best-practices.md) — 要件定義（`docs/specs/<feature-slug>/requirements.md`）を書く際のベストプラクティス
- [docs/design-doc-best-practices.md](docs/design-doc-best-practices.md) — 設計ドキュメント（`docs/specs/<feature-slug>/design.md`）を書く際のベストプラクティス

## 仕様の書き方（`docs/specs/`）

新機能や大きな変更に着手する際は、実装より先に `docs/specs/<feature-slug>/` に `requirements.md` → `design.md` → `tasks.md` の順で仕様を書き、各段階で合意してから次に進む。1機能・1要件 = 1スペックの粒度とし、複数の要件を1つのスペックにまとめない。なお [prompts/init.md](prompts/init.md) は初期実装時の指示プロンプトであり、スペックではない。

## 作業ログ

- 以下のいずれかを行った場合は、`worklogs/` 以下に「何を・なぜ行ったか」を簡潔に記録すること。
  - 要件定義・設計ドキュメント（`docs/specs/` 配下の `requirements.md` / `design.md` / `tasks.md` など）の新規作成・修正
  - プロジェクトのコード・設定・プロンプトへの修正（`src/` / `prompts/` 配下、`requirements.txt`、`run.bat`、`.env.example` などの変更全般）
- `logs/` はプログラムの実行ログ（`logging_config.py` が出力）の置き場なので、作業ログを置かないこと。
- ログは修正内容ごとに1ファイルを作成する。1つのファイルに複数の修正内容を混在させないこと。
- ファイル名は `worklogs/<yyyymmdd_hhMMss>_<種別>_<内容がわかる名前>.md` とし、ファイル名だけで実施日時・修正の種類・内容が判別できるようにする（先頭に日時を置くことで、ディレクトリの一覧表示が時系列順になる）（例: 仕様関連なら `20261105_143012_spec_auto-send-requirements.md`、コード修正なら `20261105_150000_code_list-pagination-fix.md`、CLAUDE.md自体の修正なら `20261105_090015_claude-md_token-saving-practices.md` など）。日時は記録作成時点のローカル時刻とする。
- ログファイルは必ずMarkdown形式（`.md`）で作成する。

## トークン使用量の節約

Claude Codeとのやり取りではコンテキスト消費（トークン使用量）を最小限に抑えることを常に意識する。

- ファイルを読み込む際は必要最小限のファイル・範囲のみ読み込むこと（無関係なファイルは開かない、大きなファイルは該当箇所のみ`offset`/`limit`で読む）。
- `venv/` / `.venv/` / `__pycache__/` / `logs/` / `sample/` 配下は、明示的に必要な場合を除き検索・読み込みの対象にしないこと（`sample/` のHTMLは大きいため、セレクタ確認時もGrepで該当箇所のみ見る）。
- 直前の操作結果や会話内で既に把握できている内容を、確認目的で再度読み込まないこと（例: Edit/Write直後に同じファイルを読み直さない）。
- コードベース全体を対象とした調査では、いきなり多数のファイルを開かず、Grep/Globで対象を絞り込んでから必要なファイルだけを読むこと。
- 実行ログなど出力が長大になりうるものは、フィルタリングして必要な部分のみを確認すること。
- ファイルの一部を変更する場合はWriteによる全文書き換えではなく、Editによる差分編集を優先すること。
- 同じ内容を複数のドキュメントに重複して書かない（[docs/prompt-guidelines.md](docs/prompt-guidelines.md)の単一情報源の原則に従う）。

## 横断的な注意点

- `.env`（ログイン情報・APIキー）と `qr_login.png`（ログイン用QRコード）は秘密情報として扱い、内容を読み出したり出力・共有したりしないこと。`db.sqlite`（`DB_PATH`）と `search_profiles` の出力ファイルは第三者のプロフィール（個人情報）を含むため、同様に内容を読み出したり出力・共有したりしないこと（動作確認は一時ディレクトリのDBで行う）。新しい環境変数を追加した場合は `.env.example` と [README.md](README.md) の環境変数表の両方を更新すること。
- `chat` コマンドは**下書きの生成のみ**を行い、サイトへの自動送信はしない設計である。送信機能を追加する変更は、必ずスペック（要件定義）から合意を取ってから行うこと。
- `list` のページ遷移ごとのランダムsleepは、対象サイトへの負荷・アクセス検知を避けるためのもの。削除したり極端に短くしたりしないこと。
- `README.md` は日本語で記載すること。シェルの `readme` コマンドがそのまま表示するため、コマンドを追加・変更した場合は README も更新すること。
