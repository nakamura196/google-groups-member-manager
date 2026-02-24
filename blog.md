# Google Workspace 管理者権限なしで Google Groups のメンバーを API で一括管理する

Google Groups のメンバーを定期的に入れ替える運用をしている組織は多いと思います。手作業での登録・削除は手間がかかるため、API で自動化したいところです。

Google Groups のメンバーを API で管理する方法としては、**Admin SDK (Directory API)** がよく紹介されています。一方で、Admin SDK は Google Workspace の管理者権限が必要であり、利用できる場面が限られます。

本記事では、管理者権限がない環境でも利用できる **Cloud Identity Groups API** を使って、Google Groups のメンバーを一括管理する方法を紹介します。

## API の選択肢

Google Groups のメンバーを API で管理するには、主に以下の 2 つの方法があります。

### Admin SDK (Directory API)

もっとも広く紹介されている方法です。

```python
service = build('admin', 'directory_v1', credentials=creds)
service.members().list(groupKey='group@example.com').execute()
```

利用するには、以下のいずれかが必要です：

- Google Workspace の管理者アカウント
- サービスアカウント ＋ **ドメイン全体の委任（Domain-Wide Delegation）**（管理コンソールでの設定が必要）

管理者権限がない場合は `403 Forbidden` が返されます。

### Cloud Identity Groups API

**Cloud Identity Groups API** は、グループのオーナーやマネージャーであれば、管理者権限なしでメンバーの操作が可能です。本記事ではこちらの方法を使います。

両者の違いを以下にまとめます。

| | Admin SDK (Directory API) | Cloud Identity Groups API |
|---|---|---|
| 管理者権限 | **必要** | 不要 |
| グループオーナー権限 | — | **必要** |
| ドメイン全体の委任 | サービスアカウント利用時に必要 | 不要 |
| OAuth ユーザー認証 | 管理者のみ | オーナー/マネージャーで可 |
| API エンドポイント | `admin.directory_v1` | `cloudidentity.v1` |
| メンバー操作 | `members()` | `groups().memberships()` |

## 前提条件

- 対象グループの **オーナーまたはマネージャー** であること
- Google Cloud プロジェクトを持っていること

## 手順

### 1. API の有効化

Google Cloud Console で以下の API を有効にします：

- [Cloud Identity API](https://console.cloud.google.com/apis/library/cloudidentity.googleapis.com)

### 2. OAuth クライアント ID の作成

1. Cloud Console →「APIとサービス」→「認証情報」を開きます
2. 「認証情報を作成」→「OAuth クライアント ID」を選択します
3. アプリケーションの種類は「デスクトップアプリ」を選択します
4. 作成後、JSON ファイルをダウンロードします

※ 初回は「OAuth 同意画面」の設定も必要です。ユーザーの種類は「内部」で問題ありません。

### 3. Python スクリプト

必要なライブラリをインストールします：

```bash
pip install google-auth google-auth-oauthlib google-api-python-client
```

#### メンバー一覧の取得

```python
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import pickle, os

CLIENT_SECRET = 'client_secret.json'
TOKEN_FILE = 'token.pickle'
GROUP_EMAIL = 'your-group@example.com'
SCOPES = ['https://www.googleapis.com/auth/cloud-identity.groups']

def get_credentials():
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'rb') as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'wb') as f:
            pickle.dump(creds, f)
    return creds

creds = get_credentials()
service = build('cloudidentity', 'v1', credentials=creds)

# グループを検索
group = service.groups().lookup(groupKey_id=GROUP_EMAIL).execute()
group_name = group['name']

# メンバー一覧
result = service.groups().memberships().list(parent=group_name).execute()
for m in result.get('memberships', []):
    email = m['preferredMemberKey']['id']
    roles = [r['name'] for r in m.get('roles', [])]
    print(f"{email} - {', '.join(roles)}")
```

初回実行時にブラウザが開き、Google アカウントでの認証を求められます。認証後はトークンがファイルに保存され、次回以降は自動で認証されます。

#### メンバーの追加

```python
body = {
    'preferredMemberKey': {'id': 'new-user@example.com'},
    'roles': [{'name': 'MEMBER'}],
}
service.groups().memberships().create(parent=group_name, body=body).execute()
```

#### メンバーの削除

削除にはメンバーシップの `name`（内部ID）が必要なので、一覧取得で得た情報を使います。

```python
# membership_name は一覧取得時の m['name'] の値
service.groups().memberships().delete(name=membership_name).execute()
```

### 4. 一括入れ替えの実装例

実運用では「既存メンバーを削除して新メンバーを登録する」一括入れ替えが必要になることが多いと思います。以下はその実装例です。

```python
import time

NEW_MEMBERS = [
    'user1@example.com',
    'user2@example.com',
    'user3@example.com',
]

# 現在のメンバー一覧を取得
memberships = service.groups().memberships().list(parent=group_name).execute()

# OWNER 以外の MEMBER を削除
for m in memberships.get('memberships', []):
    roles = [r['name'] for r in m.get('roles', [])]
    if 'OWNER' in roles:
        continue  # オーナーは残す
    service.groups().memberships().delete(name=m['name']).execute()
    time.sleep(0.5)  # レートリミット対策

# 新メンバーを追加
for email in NEW_MEMBERS:
    body = {
        'preferredMemberKey': {'id': email},
        'roles': [{'name': 'MEMBER'}],
    }
    try:
        service.groups().memberships().create(parent=group_name, body=body).execute()
        time.sleep(0.5)
    except Exception as e:
        if '409' in str(e):
            print(f"既に存在: {email}")
        else:
            raise
```

## 注意点

- **レートリミット**: 短時間に大量のリクエストを送ると制限されることがあります。`time.sleep()` で間隔を空けることをお勧めします
- **OAuth トークンの管理**: `token.pickle` にはアクセストークンが保存されます。Git にコミットしないよう `.gitignore` に追加してください
- **クライアントシークレット**: `client_secret.json` も同様に管理にご注意ください
- **スコープ**: `cloud-identity.groups` スコープは読み書き両方を含みます。読み取り専用であれば `cloud-identity.groups.readonly` が使えます

## 関連記事・参考資料

Cloud Identity Groups API を使った Google Groups の管理については、以下の記事も参考になります。

| 記事 | 認証方式 | 内容 |
|---|---|---|
| [Cloud Identity APIでGoogle Workspaceのグループを操作する（Qiita）](https://qiita.com/nobrin/items/e5594150ee99a705c553) | サービスアカウント＋ドメイン委任 | グループの CRUD 操作全般 |
| [自作PythonラッパーでGoogleグループのメンバーシップを管理する](https://www.kinjo.tech/posts/20221002) | サービスアカウント＋ドメイン委任 | Python ラッパーの実装、有効期限付きメンバー追加 |
| [Cloud IdentityでGoogleグループからメンバーを追加・削除するGAS](https://zenn.dev/ohsawa0515/articles/cloud-identity-gas) | OAuth（GAS） | Google Apps Script での実装 |
| [Use the Google Cloud Identity API for Google Groups（Medium）](https://medium.com/@stephane.giron/use-the-google-cloud-identity-api-for-google-groups-5e91c6a53c01) | サービスアカウント＋ドメイン委任 | 英語での包括的な解説 |
| [Google 公式ドキュメント](https://docs.cloud.google.com/identity/docs/how-to/memberships-google-groups) | — | API リファレンス |

本記事では、上記の記事とは異なり、**サービスアカウントやドメイン全体の委任を使わず、OAuth ユーザー認証のみで完結する方法**を紹介しました。管理者権限がない環境で Google Groups のメンバー管理を自動化したい場合の選択肢として、参考になれば幸いです。

## まとめ

Google Workspace の管理者権限がない環境でも、**Cloud Identity Groups API** を使えば、グループのオーナー/マネージャー権限でメンバーの一括管理が可能です。OAuth ユーザー認証のみで完結するため、サービスアカウントの準備やドメイン全体の委任の設定が不要です。

ソースコードは [GitHub リポジトリ](https://github.com/nakamura196/google-groups-member-manager) で公開しています。
