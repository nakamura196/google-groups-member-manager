# google-groups-member-manager

Google Groups のメンバーを API で一括入れ替えするスクリプト。

**Google Workspace の管理者権限は不要。** グループのオーナーまたはマネージャーであれば、Cloud Identity Groups API を使ってメンバーを管理できる。

## 前提条件

- Python 3.9+
- 対象グループの **オーナーまたはマネージャー** 権限
- Google Cloud プロジェクト

## セットアップ

### 1. Google Cloud プロジェクトの準備

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作成（または既存のものを使用）
2. [Cloud Identity API](https://console.cloud.google.com/apis/library/cloudidentity.googleapis.com) を有効化
3. 「APIとサービス」→「OAuth 同意画面」を設定（ユーザーの種類: 内部）
4. 「APIとサービス」→「認証情報」→「OAuth クライアント ID」を作成（種類: デスクトップアプリ）
5. JSON ファイルをダウンロードし、`client_secret.json` としてプロジェクトルートに配置

### 2. ライブラリのインストール

```bash
pip install google-auth google-auth-oauthlib google-api-python-client
```

### 3. 環境変数の設定

```bash
cp .env.example .env
```

`.env` を編集して `GROUP_EMAIL` を設定する：

```
GROUP_EMAIL=your-group@example.com
```

| 環境変数 | 必須 | デフォルト | 説明 |
|---|---|---|---|
| `GROUP_EMAIL` | Yes | — | 対象 Google Groups のメールアドレス |
| `CLIENT_SECRET` | No | `./client_secret.json` | OAuth クライアントシークレットのパス |
| `TOKEN_FILE` | No | `./token.pickle` | OAuth トークンの保存先 |
| `LIST_FILE` | No | `./list.txt` | メンバーリストのパス |

### 4. メンバーリストの作成

```bash
cp list.txt.example list.txt
```

`list.txt` に登録したいメンバーを記載する。形式は `名前 <email>` で、メールアドレスが `<>` で囲まれていれば自動抽出される：

```
山田 太郎 <taro-yamada@example.com>,
鈴木 花子 <hanako-suzuki@example.com>,
```

## 使い方

```bash
# .env を読み込んで実行
export $(cat .env | grep -v '^#' | xargs) && python3 manage_members.py
```

初回実行時にブラウザが開き、Google アカウントでの認証を求められる。認証後はトークンが `token.pickle` に保存され、次回以降は自動で認証される。

### 実行の流れ

1. `list.txt` からメールアドレスを読み取り
2. 現在のグループメンバーを表示
3. 確認プロンプト（`y` で続行）
4. 既存の MEMBER を削除（**OWNER は保持**）
5. 新しいメンバーを MEMBER として追加
6. 最終メンバー一覧を表示

## 動作の詳細

- **OWNER ロール**のメンバーは削除されない（安全策）
- 追加しようとしたメンバーが既に存在する場合はスキップされる
- API レートリミット対策として、各操作間に 0.5 秒の待機を入れている

## ブログ記事

技術的な背景や Admin SDK との比較については [blog.md](blog.md) を参照。

## ライセンス

MIT
