"""
관리자 계정 생성 CLI.

구 버전처럼 admin/admin 을 자동 생성하지 않으므로, 최초 계정은 이 스크립트나
EIBE_BOOTSTRAP_ADMIN_PASSWORD 설정으로 만든다.

    python -m scripts.create_admin
    python -m scripts.create_admin --username ops --role OPERATOR
"""

from __future__ import annotations

import argparse
import getpass
import sys

from app.core.security import hash_password
from app.database import SessionLocal
from app.models.auth import Role, User

MIN_PASSWORD_LENGTH = 10


def main() -> int:
    parser = argparse.ArgumentParser(description="사용자 계정 생성")
    parser.add_argument("--username", help="로그인 아이디")
    parser.add_argument("--name", help="표시 이름")
    parser.add_argument("--email", default=None, help="이메일 (선택)")
    parser.add_argument(
        "--role",
        default=Role.ADMIN.value,
        choices=[r.value for r in Role],
        help="권한 (기본: ADMIN)",
    )
    args = parser.parse_args()

    username = args.username or input("아이디: ").strip()
    if not username:
        print("아이디는 필수입니다.", file=sys.stderr)
        return 1

    name = args.name or input("표시 이름: ").strip() or username

    password = getpass.getpass("비밀번호: ")
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"비밀번호는 {MIN_PASSWORD_LENGTH}자 이상이어야 합니다.", file=sys.stderr)
        return 1
    if password != getpass.getpass("비밀번호 확인: "):
        print("비밀번호가 일치하지 않습니다.", file=sys.stderr)
        return 1

    with SessionLocal() as db:
        if db.query(User).filter(User.username == username).first():
            print(f"이미 존재하는 아이디입니다: {username}", file=sys.stderr)
            return 1

        db.add(
            User(
                username=username,
                password_hash=hash_password(password),
                name=name,
                email=args.email,
                role=Role(args.role),
            )
        )
        db.commit()

    print(f"생성 완료: {username} ({args.role})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
