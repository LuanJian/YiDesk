"""企业微信回调接收（需公网 HTTPS 地址，配置 callback_enabled 后启用）。

GET  ：URL 验证（echostr 解密回显）

POST ：消息解密 → 自动建单（复用 IM 入站流程）

纯内网部署时：配合 frp/花生壳等内网穿透，或在企微后台暂不配置回调。

"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from fastapi.responses import PlainTextResponse

from app.channels import wecom_crypto

from app.core.config import get_config

from app.services.intake_service import InboundDraft, handle_inbound_threadsafe

router = APIRouter()

def _wecom_cfg():

    cfg = get_config().wecom

    if not cfg.enabled or not cfg.callback_enabled:

        raise HTTPException(status_code=404, detail="企业微信回调未启用")

    if not cfg.callback_token or not cfg.callback_encoding_aes_key:

        raise HTTPException(status_code=500, detail="企微回调 Token/EncodingAESKey 未配置")

    return cfg

@router.get("/wecom")

def verify_url(

    msg_signature: str = Query(...),

    timestamp: str = Query(...),

    nonce: str = Query(...),

    echostr: str = Query(...),

):

    cfg = _wecom_cfg()

    if not wecom_crypto.verify_callback_signature(cfg.callback_token, timestamp, nonce, echostr, msg_signature):

        raise HTTPException(status_code=403, detail="签名校验失败")

    try:

        plain = wecom_crypto.decrypt(cfg.callback_encoding_aes_key, echostr, cfg.corp_id)

    except Exception as exc:  # noqa: BLE001

        raise HTTPException(status_code=400, detail=f"解密失败: {exc}") from exc

    return PlainTextResponse(plain)

@router.post("/wecom")

async def receive_message(

    request: Request,

    msg_signature: str = Query(...),

    timestamp: str = Query(...),

    nonce: str = Query(...),

):

    cfg = _wecom_cfg()

    body = await request.body()

    try:

        encrypt = wecom_crypto.parse_encrypted_post(body)

        if not wecom_crypto.verify_callback_signature(cfg.callback_token, timestamp, nonce, encrypt, msg_signature):

            raise HTTPException(status_code=403, detail="签名校验失败")

        plain_xml = wecom_crypto.decrypt(cfg.callback_encoding_aes_key, encrypt, cfg.corp_id)

        from_user, content = wecom_crypto.parse_text_message(plain_xml)

    except HTTPException:

        raise

    except Exception as exc:  # noqa: BLE001

        raise HTTPException(status_code=400, detail=f"消息处理失败: {exc}") from exc

    if from_user and content:

        draft = InboundDraft(

            channel="wecom",

            platform_user_id=from_user,

            sender_name="",  # 企微回调不含姓名，建单后可在管理台改名

            text=content,

            chat_id=from_user,

        )

        import anyio

        await anyio.to_thread.run_sync(handle_inbound_threadsafe, draft)

    # 企微要求回包；异步通知由 outbox 通道发送

    return PlainTextResponse("success")
