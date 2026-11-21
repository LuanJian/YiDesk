"""IM 免登服务：三平台授权 code 换平台身份 → 匹配/自动注册本地用户 → 返回 User。

- 钉钉：oapi /topapi/v2/user/getuserinfo（企业内 H5 免登码）
- 飞书：authen v2 oauth/token（授权码）→ authen v1/user_info（换 open_id/姓名）
- 企微：cgi-bin/auth/getuserinfo（OAuth code → userid）
"""
from __future__ import annotations

import logging

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_config
from app.models.user import User

logger = logging.getLogger("auth.platform")

OAPI = "https://oapi.dingtalk.com"          # 固定官方域名
LARK_API = "https://open.feishu.cn"         # 固定官方域名
QYAPI = "https://qyapi.weixin.qq.com"       # 固定官方域名


class PlatformAuthError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def login_by_dingtalk_code(db: Session, code: str) -> User:
    cfg = get_config().dingtalk
    if not cfg.enabled:
        raise PlatformAuthError("钉钉渠道未启用", 400)
    token_resp = httpx.get(
        f"{OAPI}/gettoken",
        params={"appkey": cfg.client_id, "appsecret": cfg.client_secret},
        timeout=10,
    ).json()
    access_token = token_resp.get("access_token")
    if not access_token:
        raise PlatformAuthError("钉钉 gettoken 失败，请检查应用凭据")
    resp = httpx.post(
        f"{OAPI}/topapi/v2/user/getuserinfo",
        params={"access_token": access_token},
        json={"code": code},
        timeout=10,
    ).json()
    result = resp.get("result") or {}
    userid = result.get("userid")
    if not userid:
        raise PlatformAuthError("钉钉免登失败：code 无效或已过期")
    return _find_or_register(db, "dingtalk", userid, result.get("name") or "")


def login_by_feishu_code(db: Session, code: str, redirect_uri: str) -> User:
    cfg = get_config().feishu
    if not cfg.enabled:
        raise PlatformAuthError("飞书渠道未启用", 400)
    token_resp = httpx.post(
        f"{LARK_API}/open-apis/authen/v2/oauth/token",
        json={
            "grant_type": "authorization_code",
            "client_id": cfg.app_id,
            "client_secret": cfg.app_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=10,
    ).json()
    data = token_resp.get("data") or {}
    user_access_token = data.get("access_token") or token_resp.get("access_token")
    if not user_access_token:
        raise PlatformAuthError("飞书授权失败：code 无效或 redirect_uri 不匹配")
    info = httpx.get(
        f"{LARK_API}/open-apis/authen/v1/user_info",
        headers={"Authorization": f"Bearer {user_access_token}"},
        timeout=10,
    ).json()
    info_data = info.get("data") or {}
    open_id = info_data.get("open_id")
    if not open_id:
        raise PlatformAuthError("飞书免登失败：未获取到用户身份")
    return _find_or_register(db, "feishu", open_id, info_data.get("name") or "")


def login_by_wecom_code(db: Session, code: str) -> User:
    cfg = get_config().wecom
    if not cfg.enabled:
        raise PlatformAuthError("企业微信渠道未启用", 400)
    token_resp = httpx.get(
        f"{QYAPI}/cgi-bin/gettoken",
        params={"corpid": cfg.corp_id, "corpsecret": cfg.corp_secret},
        timeout=10,
    ).json()
    access_token = token_resp.get("access_token")
    if not access_token:
        raise PlatformAuthError("企微 gettoken 失败，请检查应用凭据")
    resp = httpx.get(
        f"{QYAPI}/cgi-bin/auth/getuserinfo",
        params={"access_token": access_token, "code": code},
        timeout=10,
    ).json()
    userid = resp.get("userid")
    if not userid:
        raise PlatformAuthError("企微免登失败：code 无效或已过期")
    return _find_or_register(db, "wecom", userid, "")


def _find_or_register(db: Session, channel: str, platform_id: str, name: str) -> User:
    from app.core.deps import find_user_by_platform
    from app.services.intake_service import auto_register

    user = find_user_by_platform(
        db, channel, platform_id
    )
    if user:
        if name and not user.name:
            user.name = name[:64]
            db.commit()
        return user
    return auto_register(db, _SimpleDraft(channel, platform_id, name))


class _SimpleDraft:
    """auto_register 需要的最小接口。"""

    def __init__(self, channel: str, platform_id: str, sender_name: str):
        self.channel = channel
        self.platform_user_id = platform_id
        self.sender_name = sender_name
        self.text = ""
        self.chat_id = None
        self.extra: dict = {}
