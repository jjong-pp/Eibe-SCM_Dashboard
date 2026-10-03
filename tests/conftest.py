"""테스트 공통 설정: 임시 SQLite DB에 고정 시드 데이터를 넣고 TestClient를 띄운다.

운영 DB(data/local_erp.db)는 건드리지 않는다. app 모듈 import 전에 SCM_DB_PATH를 지정해야 한다.
"""

import os
import random
import tempfile

_TMP_DIR = tempfile.mkdtemp(prefix="scm_test_")
os.environ["SCM_DB_PATH"] = os.path.join(_TMP_DIR, "test.db")
os.environ["SCM_BACKUP_DIR"] = os.path.join(_TMP_DIR, "backups")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
import seed_data  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:  # lifespan: 테이블 생성 + admin 계정
        random.seed(42)
        seed_data.seed()
        yield c


@pytest.fixture(scope="session")
def auth_headers(client):
    res = client.post("/api/auth/login", data={"username": "admin", "password": "admin"})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}
