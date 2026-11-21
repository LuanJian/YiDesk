"""后台访问安全密钥（第二十一批+）：每账号一枚。

管理员/工程师账号生成密钥后登录必须持密钥（准入 Cookie 或请求携带）；
未生成密钥的账号与普通员工不受影响；重置后旧密钥立即失效。
模块结束清理临时用户（软删除），内存与 yaml 无全局状态。
"""
from __future__ import annotations

import hashlib

import pytest


@pytest.fixture(scope="module")
def gate_client(client):
    yield client


def _admin_h(client) -> dict:
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _login(client, username, password, gate_key=None, cookies=None):
    payload = {"username": username, "password": password}
    if gate_key:
        payload["gate_key"] = gate_key
    return client.post("/api/auth/login", json=payload, cookies=cookies or {})


def test_per_user_gate_flow(gate_client):
    c = gate_client
    admin_h = _admin_h(c)

    # 临时工程师账号：未生成密钥时可直接登录（渐进启用）
    r = c.post("/api/users", json={"username": "gkeng", "name": "门禁工程师", "role": "engineer", "password": "gkeng12345"}, headers=admin_h)
    assert r.status_code in (200, 201), r.text
    eng_id = r.json()["id"]
    assert _login(c, "gkeng", "gkeng12345").status_code == 200

    # 生成密钥：随机、不可指定；无密钥登录 403；带密钥 200
    r = c.post(f"/api/users/{eng_id}/gate-key/reset", headers=admin_h)
    assert r.status_code == 200 and r.json()["enabled"] is True
    key1 = r.json()["key"]
    assert len(key1) >= 24 and r.json()["gate_url"].endswith(key1)
    assert _login(c, "gkeng", "gkeng12345").status_code == 403
    assert _login(c, "gkeng", "gkeng12345", gate_key=key1).status_code == 200

    # 准入链接：/gate/{key} 302 + HttpOnly Cookie（哈希值）；错误密钥 404
    r = c.get(f"/gate/{key1}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].endswith("/login")
    cookie_header = r.headers.get("set-cookie", "")
    assert "itops_gate=" in cookie_header and "httponly" in cookie_header.lower()
    assert hashlib.sha256(key1.encode()).hexdigest() in cookie_header
    assert c.get("/gate/wrong-key", follow_redirects=False).status_code == 404
    assert c.get(f"/gate/{key1}x", follow_redirects=False).status_code == 404

    # Cookie 准入：不带 body 密钥也可登录
    assert _login(c, "gkeng", "gkeng12345", cookies={"itops_gate": hashlib.sha256(key1.encode()).hexdigest()}).status_code == 200

    # 重置：旧密钥与旧 Cookie 立即失效，新密钥可用；仅管理员可操作
    r = c.post(f"/api/users/{eng_id}/gate-key/reset", headers=admin_h)
    key2 = r.json()["key"]
    assert key2 != key1
    assert _login(c, "gkeng", "gkeng12345", gate_key=key1).status_code == 403
    assert _login(c, "gkeng", "gkeng12345", cookies={"itops_gate": hashlib.sha256(key1.encode()).hexdigest()}).status_code == 403
    assert _login(c, "gkeng", "gkeng12345", gate_key=key2).status_code == 200

    # 查看接口返回当前密钥与准入链接
    r = c.get(f"/api/users/{eng_id}/gate-key", headers=admin_h)
    assert r.json()["enabled"] is True and r.json()["key"] == key2
    assert r.json()["gate_url"].endswith(key2)

    # 员工账号不允许使用密钥（400），员工登录始终无需密钥
    r = c.post("/api/users", json={"username": "gkemp", "name": "门禁员工", "role": "employee", "password": "gkemp12345"}, headers=admin_h)
    emp_id = r.json()["id"]
    assert c.post(f"/api/users/{emp_id}/gate-key/reset", headers=admin_h).status_code == 400
    assert _login(c, "gkemp", "gkemp12345").status_code == 200

    # 清理：软删除临时账号
    c.delete(f"/api/users/{eng_id}", headers=admin_h)
    c.delete(f"/api/users/{emp_id}", headers=admin_h)
