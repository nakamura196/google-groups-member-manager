#!/usr/bin/env python3
"""
Google Groups メンバー一括入れ替えスクリプト

使い方:
  1. client_secret.json を同じディレクトリに配置
  2. list.txt にメンバーリストを記載（list.txt.example を参照）
  3. python3 manage_members.py

初回実行時にブラウザが開き、Google アカウントでの認証を求められる。
"""

import os
import re
import sys
import time
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# === 設定（環境変数で上書き可能） ===
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CLIENT_SECRET = os.environ.get('CLIENT_SECRET', os.path.join(SCRIPT_DIR, 'client_secret.json'))
TOKEN_FILE = os.environ.get('TOKEN_FILE', os.path.join(SCRIPT_DIR, 'token.pickle'))
LIST_FILE = os.environ.get('LIST_FILE', os.path.join(SCRIPT_DIR, 'list.txt'))
GROUP_EMAIL = os.environ.get('GROUP_EMAIL', '')
SCOPES = ['https://www.googleapis.com/auth/cloud-identity.groups']


def get_credentials():
    """OAuth 認証を行い、クレデンシャルを返す。"""
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'rb') as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CLIENT_SECRET):
                print(f"エラー: {CLIENT_SECRET} が見つかりません。")
                print("OAuth クライアントシークレットの JSON ファイルを配置してください。")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'wb') as f:
            pickle.dump(creds, f)
    return creds


def parse_member_list(filepath):
    """list.txt からメールアドレスを抽出する。"""
    if not os.path.exists(filepath):
        print(f"エラー: {filepath} が見つかりません。")
        print("list.txt.example を参考に list.txt を作成してください。")
        sys.exit(1)
    emails = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            match = re.search(r'<([^>]+@[^>]+)>', line)
            if match:
                emails.append(match.group(1).strip())
    return emails


def main():
    if not GROUP_EMAIL:
        print("エラー: 環境変数 GROUP_EMAIL を設定してください。")
        print("  例: GROUP_EMAIL=your-group@example.com python3 manage_members.py")
        sys.exit(1)

    new_members = parse_member_list(LIST_FILE)
    if not new_members:
        print("エラー: list.txt にメールアドレスが見つかりません。")
        sys.exit(1)

    print(f"対象グループ: {GROUP_EMAIL}")
    print(f"新メンバー数: {len(new_members)}")
    for email in new_members:
        print(f"  {email}")

    print("\n認証中...")
    creds = get_credentials()
    service = build('cloudidentity', 'v1', credentials=creds)

    # グループを検索
    result = service.groups().lookup(groupKey_id=GROUP_EMAIL).execute()
    group_name = result['name']

    # 現在のメンバー一覧を取得
    print("\n=== 現在のメンバー取得中 ===")
    all_memberships = []
    page_token = None
    while True:
        kwargs = {'parent': group_name}
        if page_token:
            kwargs['pageToken'] = page_token
        resp = service.groups().memberships().list(**kwargs).execute()
        all_memberships.extend(resp.get('memberships', []))
        page_token = resp.get('nextPageToken')
        if not page_token:
            break

    for m in all_memberships:
        email = m.get('preferredMemberKey', {}).get('id', '?')
        roles = [r.get('name', '') for r in m.get('roles', [])]
        print(f"  {email} - {', '.join(roles)}")

    # 確認プロンプト
    answer = input("\nMEMBER を入れ替えます（OWNER は保持）。続行しますか？ [y/N]: ")
    if answer.lower() != 'y':
        print("中止しました。")
        sys.exit(0)

    # MEMBER のみ削除（OWNER は残す）
    print("\n=== MEMBER の削除 ===")
    deleted = 0
    for m in all_memberships:
        email = m.get('preferredMemberKey', {}).get('id', '')
        roles = [r.get('name', '') for r in m.get('roles', [])]
        if 'OWNER' in roles:
            print(f"  スキップ (OWNER): {email}")
            continue
        try:
            service.groups().memberships().delete(name=m['name']).execute()
            print(f"  削除: {email}")
            deleted += 1
            time.sleep(0.5)
        except HttpError as e:
            print(f"  削除失敗: {email} - {e.resp.status}: {e._get_reason()}")
    print(f"削除完了: {deleted}名")

    # 新しいメンバーを追加
    print("\n=== 新しいメンバーの追加 ===")
    added = 0
    for email in new_members:
        body = {
            'preferredMemberKey': {'id': email},
            'roles': [{'name': 'MEMBER'}],
        }
        try:
            service.groups().memberships().create(parent=group_name, body=body).execute()
            print(f"  追加: {email}")
            added += 1
            time.sleep(0.5)
        except HttpError as e:
            if e.resp.status == 409:
                print(f"  既に存在: {email}")
            else:
                print(f"  追加失敗: {email} - {e.resp.status}: {e._get_reason()}")
    print(f"追加完了: {added}名")

    # 最終確認
    print("\n=== 最終メンバー一覧 ===")
    page_token = None
    count = 0
    while True:
        kwargs = {'parent': group_name}
        if page_token:
            kwargs['pageToken'] = page_token
        resp = service.groups().memberships().list(**kwargs).execute()
        for m in resp.get('memberships', []):
            email = m.get('preferredMemberKey', {}).get('id', '')
            roles = [r.get('name', '') for r in m.get('roles', [])]
            print(f"  {email} - {', '.join(roles)}")
            count += 1
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    print(f"\n合計: {count}名")


if __name__ == '__main__':
    main()
