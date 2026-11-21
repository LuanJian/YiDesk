"""pytest 配置：独立测试库 + 测试配置文件（必须在导入 app 之前设置）。"""
from __future__ import annotations

import os
import pathlib
import tempfile

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="itops-helpdesk-test-"))
_CFG = _TMP / "config.yaml"
_CFG.write_text(
    "app_name: IT运维工单台(测试)\n"
    f"database_url: sqlite:///{_TMP / 'test.db'}\n"
    "jwt_secret: test-secret\n"
    "admin_username: admin\n"
    "admin_password: admin123\n"
    "public_base_url: http://test.local:8300\n",
    encoding="utf-8",
)
os.environ["ITOPS_CONFIG"] = str(_CFG)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session")
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


def _login(client: TestClient, username: str, password: str) -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def admin_headers(client) -> dict:
    return _login(client, "admin", "admin123")


@pytest.fixture(scope="session")
def engineer_headers(client, admin_headers) -> dict:
    r = client.post(
        "/api/users",
        json={"username": "eng1", "name": "工程师一号", "role": "engineer", "password": "eng12345", "department": "IT部"},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    return _login(client, "eng1", "eng12345")


@pytest.fixture(scope="session")
def employee_headers(client, admin_headers) -> dict:
    r = client.post(
        "/api/users",
        json={"username": "emp1", "name": "员工一号", "role": "employee", "password": "emp12345", "department": "业务部"},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    return _login(client, "emp1", "emp12345")
