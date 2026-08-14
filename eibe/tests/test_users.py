"""
사용자 계정 API 테스트.

구 버전은 `GET /api/users` 가 무인증으로 전 계정을 노출했다. 그 재발을 막는
것이 이 파일의 첫 번째 목적이고, 두 번째는 **관리자가 0명이 되는 상태를
만들 수 없다**는 것을 고정하는 것이다.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.auth import Role, User
from tests.conftest import make_user, sign_in


class TestAuthorization:
    def test_anonymous_cannot_list_accounts(self, client: TestClient) -> None:
        assert client.get("/api/users").status_code == 401

    def test_viewer_cannot_list_accounts(
        self, client: TestClient, db: Session
    ) -> None:
        sign_in(client, db, Role.VIEWER)
        assert client.get("/api/users").status_code == 403

    def test_operator_cannot_list_accounts(
        self, client: TestClient, db: Session
    ) -> None:
        sign_in(client, db, Role.OPERATOR)
        assert client.get("/api/users").status_code == 403

    def test_admin_can_list_accounts(self, client: TestClient, db: Session) -> None:
        sign_in(client, db, Role.ADMIN)
        assert client.get("/api/users").status_code == 200


class TestResponseShape:
    def test_password_hash_is_never_returned(
        self, client: TestClient, db: Session
    ) -> None:
        sign_in(client, db, Role.ADMIN)
        body = client.get("/api/users").json()
        assert body
        for account in body:
            assert "password_hash" not in account
            assert "password" not in account


class TestCreate:
    def test_create_account(self, client: TestClient, db: Session) -> None:
        headers = sign_in(client, db, Role.ADMIN)
        res = client.post(
            "/api/users",
            json={
                "username": "newbie",
                "password": "long-enough-password",
                "name": "새 사용자",
                "role": "OPERATOR",
            },
            headers=headers,
        )
        assert res.status_code == 201
        assert res.json()["role"] == "OPERATOR"

    def test_password_is_stored_hashed(self, client: TestClient, db: Session) -> None:
        headers = sign_in(client, db, Role.ADMIN)
        client.post(
            "/api/users",
            json={
                "username": "newbie",
                "password": "long-enough-password",
                "name": "새 사용자",
            },
            headers=headers,
        )
        created = db.query(User).filter(User.username == "newbie").one()
        assert created.password_hash != "long-enough-password"
        assert created.password_hash.startswith("$2")  # bcrypt

    def test_short_password_is_rejected(
        self, client: TestClient, db: Session
    ) -> None:
        headers = sign_in(client, db, Role.ADMIN)
        res = client.post(
            "/api/users",
            json={"username": "newbie", "password": "short", "name": "새 사용자"},
            headers=headers,
        )
        assert res.status_code == 422

    def test_duplicate_username_is_a_conflict(
        self, client: TestClient, db: Session
    ) -> None:
        headers = sign_in(client, db, Role.ADMIN, username="boss")
        res = client.post(
            "/api/users",
            json={"username": "boss", "password": "long-enough-password", "name": "중복"},
            headers=headers,
        )
        assert res.status_code == 409

    def test_default_role_is_viewer(self, client: TestClient, db: Session) -> None:
        """권한은 명시적으로 올린다. 빠뜨리면 가장 낮은 권한이어야 한다."""
        headers = sign_in(client, db, Role.ADMIN)
        res = client.post(
            "/api/users",
            json={"username": "newbie", "password": "long-enough-password", "name": "새"},
            headers=headers,
        )
        assert res.json()["role"] == "VIEWER"


class TestUpdate:
    def test_change_role(self, client: TestClient, db: Session) -> None:
        target = make_user(db, "helper", role=Role.VIEWER)
        headers = sign_in(client, db, Role.ADMIN, username="boss")

        res = client.put(
            f"/api/users/{target.id}", json={"role": "OPERATOR"}, headers=headers
        )
        assert res.status_code == 200
        assert res.json()["role"] == "OPERATOR"

    def test_password_change_is_hashed(self, client: TestClient, db: Session) -> None:
        target = make_user(db, "helper")
        original = target.password_hash
        headers = sign_in(client, db, Role.ADMIN, username="boss")

        client.put(
            f"/api/users/{target.id}",
            json={"password": "brand-new-password"},
            headers=headers,
        )

        db.refresh(target)
        assert target.password_hash != original
        assert target.password_hash != "brand-new-password"

    def test_missing_user_is_404(self, client: TestClient, db: Session) -> None:
        headers = sign_in(client, db, Role.ADMIN)
        res = client.put("/api/users/9999", json={"name": "없음"}, headers=headers)
        assert res.status_code == 404


class TestLastAdminProtection:
    def test_cannot_demote_the_last_admin(
        self, client: TestClient, db: Session
    ) -> None:
        """아무도 들어갈 수 없는 시스템이 되면 DB 를 직접 고치는 수밖에 없다."""
        headers = sign_in(client, db, Role.ADMIN, username="only-admin")
        admin = db.query(User).filter(User.username == "only-admin").one()

        res = client.put(
            f"/api/users/{admin.id}", json={"role": "VIEWER"}, headers=headers
        )
        assert res.status_code == 409
        assert "마지막 관리자" in res.json()["detail"]

    def test_cannot_deactivate_the_last_admin(
        self, client: TestClient, db: Session
    ) -> None:
        headers = sign_in(client, db, Role.ADMIN, username="only-admin")
        admin = db.query(User).filter(User.username == "only-admin").one()

        res = client.put(
            f"/api/users/{admin.id}", json={"is_active": False}, headers=headers
        )
        assert res.status_code == 409

    def test_can_demote_an_admin_when_another_remains(
        self, client: TestClient, db: Session
    ) -> None:
        spare = make_user(db, "spare-admin", role=Role.ADMIN)
        headers = sign_in(client, db, Role.ADMIN, username="boss")

        res = client.put(
            f"/api/users/{spare.id}", json={"role": "VIEWER"}, headers=headers
        )
        assert res.status_code == 200

    def test_inactive_admin_does_not_count_as_a_remaining_admin(
        self, client: TestClient, db: Session
    ) -> None:
        """비활성 관리자는 로그인할 수 없으므로 대체자가 되지 못한다."""
        make_user(db, "retired-admin", role=Role.ADMIN)
        db.query(User).filter(User.username == "retired-admin").update(
            {"is_active": False}
        )
        db.commit()

        headers = sign_in(client, db, Role.ADMIN, username="only-admin")
        admin = db.query(User).filter(User.username == "only-admin").one()

        res = client.put(
            f"/api/users/{admin.id}", json={"role": "VIEWER"}, headers=headers
        )
        assert res.status_code == 409


class TestDeactivate:
    def test_delete_deactivates_instead_of_removing(
        self, client: TestClient, db: Session
    ) -> None:
        """'누가 등록했는가'가 남아야 하고, 아이디 재사용으로 주체가 바뀌면 안 된다."""
        target = make_user(db, "helper")
        headers = sign_in(client, db, Role.ADMIN, username="boss")

        res = client.delete(f"/api/users/{target.id}", headers=headers)
        assert res.status_code == 200

        db.expire_all()
        stored = db.get(User, target.id)
        assert stored is not None
        assert stored.is_active is False

    def test_cannot_deactivate_yourself(
        self, client: TestClient, db: Session
    ) -> None:
        """실수로 자기를 잠그는 것을 막는다."""
        headers = sign_in(client, db, Role.ADMIN, username="boss")
        me = db.query(User).filter(User.username == "boss").one()

        res = client.delete(f"/api/users/{me.id}", headers=headers)
        assert res.status_code == 400

    def test_deactivated_user_cannot_log_in(
        self, client: TestClient, db: Session
    ) -> None:
        target = make_user(db, "helper", "test-password-123")
        headers = sign_in(client, db, Role.ADMIN, username="boss")
        client.delete(f"/api/users/{target.id}", headers=headers)

        res = client.post(
            "/api/auth/login",
            json={"username": "helper", "password": "test-password-123"},
        )
        assert res.status_code == 401
