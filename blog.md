# Google Workspace 管理者権限なしで Google Groups のメンバーを API で一括管理する

Google Groups のメンバーを定期的に入れ替える運用をしている組織は多い。手作業での登録・削除は手間がかかるため、API で自動化したい。しかし、よく紹介される **Admin SDK (Directory API)** は Google Workspace の管理者権限が必要であり、一般ユーザーには使えない。

本記事では、**管理者権限なしで** Google Groups のメンバーを API から一括管理する方法を紹介する。

## よくある落とし穴：Admin SDK は管理者専用

Google Groups のメンバー管理を API で行う方法を検索すると、まず出てくるのが **Admin SDK Directory API** だ。

```python
# これは管理者権限がないと 403 Forbidden になる
service = build('admin', 'directory_v1', credentials=creds)
service.members().list(groupKey='group@example.com').execute()
```

Admin SDK を使うには以下のいずれかが必要になる：

- Google Workspace の管理者アカウント
- サービスアカウント ＋ **ドメイン全体の委任（Domain-Wide Delegation）**（管理コンソールでの設定が必要）

組織の IT 部門に依頼できない場合、この方法は使えない。

## 解決策：Cloud Identity Groups API

**Cloud Identity Groups API** は、グループのオーナーやマネージャーであれば、管理者権限なしでメンバーの操作が可能だ。

### 前提条件

- 対象グループの **オーナーまたはマネージャー** であること
- Google Cloud プロジェクトを持っていること

### 手順

#### 1. API の有効化

Google Cloud Console で以下の 2 つの API を有効にする：

- [Cloud Identity API](https://console.cloud.google.com/apis/library/cloudidentity.googleapis.com)

#### 2. OAuth クライアント ID の作成

1. Cloud Console → 「APIとサービス」→「認証情報」
2. 「認証情報を作成」→「OAuth クライアント ID」
3. アプリケーションの種類：「デスクトップアプリ」
4. JSON ファイルをダウンロード

※ 初回は「OAuth 同意画面」の設定も必要。ユーザーの種類は「内部」でよい。

#### 3. Python スクリプト

必要なライブラリをインストール：

```bash
pip install google-auth google-auth-oauthlib google-api-python-client
```

##### メンバー一覧の取得

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

初回実行時にブラウザが開き、Google アカウントでの認証を求められる。認証後はトークンがファイルに保存され、次回以降は自動で認証される。

##### メンバーの追加

```python
body = {
    'preferredMemberKey': {'id': 'new-user@example.com'},
    'roles': [{'name': 'MEMBER'}],
}
service.groups().memberships().create(parent=group_name, body=body).execute()
```

##### メンバーの削除

削除にはメンバーシップの `name`（内部ID）が必要なので、一覧取得で得た情報を使う。

```python
# membership_name は一覧取得時の m['name'] の値
service.groups().memberships().delete(name=membership_name).execute()
```

#### 4. 一括入れ替えの実装例

実運用では「既存メンバーを削除して新メンバーを登録する」一括入れ替えが必要になることが多い。以下はその実装例だ。

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

## Admin SDK vs Cloud Identity API 比較

| | Admin SDK (Directory API) | Cloud Identity Groups API |
|---|---|---|
| 管理者権限 | **必要** | 不要 |
| グループオーナー権限 | — | **必要** |
| ドメイン全体の委任 | サービスアカウント利用時に必要 | 不要 |
| OAuth ユーザー認証 | 管理者のみ | オーナー/マネージャーで可 |
| API エンドポイント | `admin.directory_v1` | `cloudidentity.v1` |
| メンバー操作 | `members()` | `groups().memberships()` |

## 注意点

- **レートリミット**: 短時間に大量のリクエストを送ると制限される。`time.sleep()` で間隔を空けるとよい
- **OAuth トークンの管理**: `token.pickle` にはアクセストークンが保存される。Git にコミットしないよう `.gitignore` に追加すること
- **クライアントシークレット**: `client_secret.json` も同様に管理に注意
- **スコープ**: `cloud-identity.groups` スコープは読み書き両方を含む。読み取り専用なら `cloud-identity.groups.readonly` を使う

## まとめ

Google Workspace の管理者権限がなくても、**Cloud Identity Groups API** を使えばグループのオーナー/マネージャー権限だけでメンバーの一括管理が可能だ。Admin SDK を前提とした記事が多い中、この方法は意外と知られていない。定期的なメンバー入れ替えの自動化に活用してほしい。
