# 目的
対象の一覧データからprofile情報を抽出し、DBに保存できる

# 要件
- 対象の一覧データからprofile情報を抽出し、DBに保存するコマンド
- DBに保存したデータを検索し、表示できるコマンド

# 用語
- profile link : listコマンドで取得できるデータのlink
- DB : db.sqlite

# 保存の流れ
- linkコマンドと同様に一覧データを取得する
- 一覧データからprofile linkを取得する
- profile linkから`src/with_auto_reply/user_profile.py`を使用し情報を抽出する
- 抽出した情報をDBに保存する

# 抽出の流れ
- パラメータの検索情報からDBの情報を検索する
- 取得した情報を指定した形式(json/csv)で出力する