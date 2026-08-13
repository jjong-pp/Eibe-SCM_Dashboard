"""인증 · 권한 가드 · CSRF 동작 검증."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.models.auth import Role
from tests.conftest import login, make_user


class TestHealth:
    def test_health_is_public(self, client: TestClient) -> None:
        res = client.get("/api/system/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

    def test_health_does_not_leak_internals(self, client: TestClient) -> None:
        body = client.get("/api/system/health").json()
        assert "database_dialect" not in body


class TestLogin:
    def test_login_sets_httponly_session_cookie(
        self, client: TestClient, db: Session
    ) -> None:
        make_user(db, "alice", "correct-horse-battery")

        res = client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "correct-horse-battery"},
        )

        assert res.status_code == 200
        session_cookie = res.cookies.get(settings.COOKIE_NAME)
        assert session_cookie

        # 세션 쿠키는 httpOnly, CSRF 쿠키는 JS 가 읽어야 하므로 아니어야 한다.
        set_cookie_headers = res.headers.get_list("set-cookie")
        session_header = next(
            h for h in set_cookie_headers if h.startswith(settings.COOKIE_NAME)
        )
        csrf_header = next(
            h for h in set_cookie_headers if h.startswith(settings.CSRF_COOKIE_NAME)
        )
        assert "httponly" in session_header.lower()
        assert "httponly" not in csrf_header.lower()

    def test_token_is_not_in_response_body(
        self, client: TestClient, db: Session
    ) -> None:
        make_user(db, "alice", "correct-horse-battery")
        body = client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "correct-horse-battery"},
        ).json()

        assert "access_token" not in body
        assert "accessToken" not in body

    def test_wrong_password_rejected(self, client: TestClient, db: Session) -> None:
        make_user(db, "alice", "correct-horse-battery")
        res = client.post(
            "/api/auth/login", json={"username": "alice", "password": "wrong"}
        )
        assert res.status_code == 401

    def test_unknown_user_gives_same_message_as_wrong_password(
        self, client: TestClient, db: Session
    ) -> None:
        """계정 열거 방지 — 두 경우의 응답이 구분되면 안 된다."""
        make_user(db, "alice", "correct-horse-battery")

        wrong_pw = client.post(
            "/api/auth/login", json={"username": "alice", "password": "wrong"}
        )
        no_user = client.post(
            "/api/auth/login", json={"username": "ghost", "password": "wrong"}
        )

        assert wrong_pw.status_code == no_user.status_code == 401
        assert wrong_pw.json()["detail"] == no_user.json()["detail"]

    def test_inactive_user_cannot_login(self, client: TestClient, db: Session) -> None:
        user = make_user(db, "alice", "correct-horse-battery")
        user.is_active = False
        db.commit()

        res = client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "correct-horse-battery"},
        )
        assert res.status_code == 401


class TestAuthGuard:
    def test_me_requires_authentication(self, client: TestClient) -> None:
        assert client.get("/api/auth/me").status_code == 401

    def test_me_returns_current_user(self, client: TestClient, db: Session) -> None:
        make_user(db, "alice", "correct-horse-battery", role=Role.OPERATOR)
        login(client, "alice", "correct-horse-battery")

        body = client.get("/api/auth/me").json()
        assert body["username"] == "alice"
        assert body["role"] == "OPERATOR"
        assert "password_hash" not in body

    def test_garbage_token_is_rejected(self, client: TestClient) -> None:
        client.cookies.set(settings.COOKIE_NAME, "not-a-jwt")
        assert client.get("/api/auth/me").status_code == 401

    def test_deleted_user_token_is_rejected(
        self, client: TestClient, db: Session
    ) -> None:
        user = make_user(db, "alice", "correct-horse-battery")
        login(client, "alice", "correct-horse-battery")

        db.delete(user)
        db.commit()

        assert client.get("/api/auth/me").status_code == 401


class TestRoleGuard:
    def test_viewer_cannot_reach_admin_endpoint(
        self, client: TestClient, db: Session
    ) -> None:
        make_user(db, "viewer", "test-password-123", role=Role.VIEWER)
        login(client, "viewer", "test-password-123")

        assert client.get("/api/system/diagnostics").status_code == 403

    def test_admin_can_reach_admin_endpoint(
        self, client: TestClient, db: Session
    ) -> None:
        make_user(db, "root", "test-password-123", role=Role.ADMIN)
        login(client, "root", "test-password-123")

        res = client.get("/api/system/diagnostics")
        assert res.status_code == 200
        assert res.json()["is_sqlite"] is True

    def test_diagnostics_requires_authentication(self, client: TestClient) -> None:
        assert client.get("/api/system/diagnostics").status_code == 401


class TestCsrf:
    def test_state_changing_request_without_csrf_header_is_blocked(
        self, client: TestClient, db: Session
    ) -> None:
        make_user(db, "root", "test-password-123", role=Role.ADMIN)
        login(client, "root", "test-password-123")

        # 세션 쿠키는 있지만 CSRF 헤더가 없다 → 차단되어야 한다.
        res = client.post("/api/auth/logout-nonexistent")
        assert res.status_code == 403
        assert "CSRF" in res.json()["detail"]

    def test_safe_methods_do_not_require_csrf(
        self, client: TestClient, db: Session
    ) -> None:
        make_user(db, "root", "test-password-123", role=Role.ADMIN)
        login(client, "root", "test-password-123")

        assert client.get("/api/auth/me").status_code == 200

    def test_login_is_exempt_from_csrf(self, client: TestClient, db: Session) -> None:
        make_user(db, "alice", "correct-horse-battery")
        res = client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "correct-horse-battery"},
        )
        assert res.status_code == 200


class TestRoleHierarchy:
    def test_admin_outranks_operator_outranks_viewer(self) -> None:
        assert Role.ADMIN.can_act_as(Role.OPERATOR)
        assert Role.ADMIN.can_act_as(Role.VIEWER)
        assert Role.OPERATOR.can_act_as(Role.VIEWER)

    def test_lower_roles_do_not_escalate(self) -> None:
        assert not Role.VIEWER.can_act_as(Role.OPERATOR)
        assert not Role.OPERATOR.can_act_as(Role.ADMIN)
