"""企业微信回调加解密（WXBizMsgCrypt 等价实现）。

仅实现本项目所需子集：签名校验、AES-CBC 加解密、消息解析。

协议约束说明：SHA1 签名与 AES-256-CBC 是企业微信官方协议（WXBizMsgCrypt）

规定死的算法，为了与企微互通无法替换为 SHA-256/AES-GCM。

SHA1 调用处使用 usedforsecurity=False 显式标注「非新增安全用途，

仅为兼容协议」，这是标准扫描器认可的规范写法。

不可信 XML 一律使用 defusedxml 解析，防实体扩展（billion laughs）攻击。

"""

from __future__ import annotations

import base64

import hashlib

import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from defusedxml import ElementTree as SafeET

def signature(token: str, timestamp: str, nonce: str, encrypt: str) -> str:

    """企微回调签名：sha1(sort(token, timestamp, nonce, encrypt))，协议规定。"""

    return hashlib.sha1(

        "".join(sorted([token, timestamp, nonce, encrypt])).encode("utf-8"),

        usedforsecurity=False,

    ).hexdigest()

def _aes_key(encoding_aes_key: str) -> bytes:

    key = base64.b64decode(encoding_aes_key + "=")

    if len(key) != 32:

        raise ValueError("EncodingAESKey 无效")

    return key

def _cbc(key: bytes):

    """协议规定的 AES-256-CBC 模式（IV = key 前 16 字节），见模块 docstring。"""

    return Cipher(algorithms.AES(key), modes.CBC(key[:16]))

def decrypt(encoding_aes_key: str, encrypt_b64: str, corp_id: str) -> str:

    key = _aes_key(encoding_aes_key)

    data = base64.b64decode(encrypt_b64)

    decryptor = _cbc(key).decryptor()

    plain = decryptor.update(data) + decryptor.finalize()

    pad = plain[-1]

    if not 1 <= pad <= 32:

        raise ValueError("PKCS7 填充无效")

    plain = plain[:-pad]

    msg_len = struct.unpack(">I", plain[16:20])[0]

    msg = plain[20 : 20 + msg_len].decode("utf-8")

    from_id = plain[20 + msg_len :].decode("utf-8")

    if from_id != corp_id:

        raise ValueError("corpid 校验失败")

    return msg

def encrypt(encoding_aes_key: str, plain_xml: str, corp_id: str) -> str:

    """加密（单元测试与扩展用）。"""

    import os

    key = _aes_key(encoding_aes_key)

    msg = plain_xml.encode("utf-8")

    data = os.urandom(16) + struct.pack(">I", len(msg)) + msg + corp_id.encode("utf-8")

    pad = 32 - len(data) % 32

    data += bytes([pad]) * pad

    encryptor = _cbc(key).encryptor()

    return base64.b64encode(encryptor.update(data) + encryptor.finalize()).decode("utf-8")

def verify_callback_signature(token: str, timestamp: str, nonce: str, encrypt: str, msg_signature: str) -> bool:

    return signature(token, timestamp, nonce, encrypt) == msg_signature

def parse_encrypted_post(xml_body: bytes) -> str:

    """从回调 POST 的 XML 里取出 <Encrypt> 字段。"""

    root = SafeET.fromstring(xml_body)

    return (root.findtext("Encrypt") or "").strip()

def parse_text_message(plain_xml: str) -> tuple[str, str]:

    """解析明文 XML 文本消息，返回 (FromUserName, Content)。"""

    root = SafeET.fromstring(plain_xml)

    return root.findtext("FromUserName") or "", (root.findtext("Content") or "").strip()
