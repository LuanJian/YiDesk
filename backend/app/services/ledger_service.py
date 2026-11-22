"""台账服务：许可到期预警、设备连通性探活、合规巡检汇总与上报。"""

from __future__ import annotations

import logging

import socket

from datetime import timedelta

from sqlalchemy import select

from sqlalchemy.orm import Session

from app.core.config import get_config

from app.models.knowledge import Asset

from app.models.ledger import ComplianceItem, ComplianceRecord, NetworkDevice, SoftwareLicense

from app.models.user import utcnow

logger = logging.getLogger("services.ledger")

DEFAULT_PROBE_PORTS = [22, 443, 80, 8443, 8080]

# ---------- 软件许可 ----------

def scan_license_alerts(db: Session) -> list[str]:

    """到期/超席位预警 → 通知全体在职 IT 人员（每日一次，幂等靠通知内容自然去重意义不大，

    仅在发生变化的边界日提醒：到期日当天提前 N 天、到期当天、已过期）。"""

    from app.services import notify_service

    cfg = get_config().licenses

    logs: list[str] = []

    staff = notify_service.staff_users(db)

    if not staff:

        return logs

    today = utcnow().date()

    licenses = list(db.scalars(select(SoftwareLicense).where(SoftwareLicense.enabled.is_(True))))

    for lic in licenses:

        days = lic.days_to_expiry

        if days is None:

            continue

        title, content = None, ""

        if days == cfg.alert_days:

            title = f"许可即将到期 {lic.name}"

            content = f"「{lic.name}」将于 {lic.expiry_date} 到期（剩 {days} 天），请及时续订。"

        elif days == 0:

            title = f"许可今日到期 {lic.name}"

            content = f"「{lic.name}」今日到期，请确认续订或停用。"

        elif days < 0 and -days in (1, 7, 30):

            title = f"许可已过期 {lic.name}"

            content = f"「{lic.name}」已过期 {-days} 天，请尽快处理。"

        if title:

            notify_service.enqueue_for_users(db, staff, ticket_id=None, title=title, content=content, url="")

            logs.append(f"license:{lic.name}:{days}d")

        if lic.seats_used >= lic.seats_total:

            notify_service.enqueue_for_users(

                db, staff, ticket_id=None,

                title=f"许可席位已满 {lic.name}",

                content=f"「{lic.name}」席位 {lic.seats_used}/{lic.seats_total} 已用满，新装需扩容。",

                url="",

            )

            logs.append(f"license-seats:{lic.name}")

    db.commit()

    return logs

def license_summary(db: Session) -> dict:

    licenses = list(db.scalars(select(SoftwareLicense).where(SoftwareLicense.enabled.is_(True))))

    total_cost = sum(l.cost for l in licenses)

    return {

        "total": len(licenses),

        "expiring_30": sum(1 for l in licenses if l.days_to_expiry is not None and 0 <= l.days_to_expiry <= 30),

        "expired": sum(1 for l in licenses if l.days_to_expiry is not None and l.days_to_expiry < 0),

        "seats_full": sum(1 for l in licenses if l.seats_used >= l.seats_total),

        "total_cost": total_cost,

    }

# ---------- 网络设备探活 ----------

def probe_device(device: NetworkDevice, timeout: float) -> bool:

    """TCP 探测管理端口；未指定端口则尝试常见管理端口，任一通即在线。"""

    ports = [device.mgmt_port] if device.mgmt_port else DEFAULT_PROBE_PORTS

    for port in ports:

        if not port:

            continue

        try:

            with socket.create_connection((device.ip, port), timeout=timeout):

                return True

        except OSError:

            continue

    return False

def probe_all_devices(db: Session) -> dict:

    """定时任务：探活所有启用的设备并更新状态。"""

    cfg = get_config().network

    timeout = float(cfg.probe_timeout_seconds)

    devices = list(

        db.scalars(select(NetworkDevice).where(NetworkDevice.status != "停用", NetworkDevice.probe_enabled.is_(True)))

    )

    online = offline = 0

    for d in devices:

        ok = probe_device(d, timeout)

        d.last_checked_at = utcnow()

        if ok:

            d.status = "在线"

            d.last_seen_at = utcnow()

            online += 1

        else:

            d.status = "失联"

            offline += 1

    db.commit()

    return {"checked": len(devices), "online": online, "offline": offline}

def device_summary(db: Session) -> dict:

    devices = list(db.scalars(select(NetworkDevice)))

    by_status: dict[str, int] = {}

    by_type: dict[str, int] = {}

    for d in devices:

        by_status[d.status] = by_status.get(d.status, 0) + 1

        by_type[d.device_type] = by_type.get(d.device_type, 0) + 1

    return {"total": len(devices), "by_status": by_status, "by_type": by_type}

# ---------- 终端合规巡检 ----------

def latest_records(db: Session) -> dict[tuple[int, int], ComplianceRecord]:

    """每个 (终端, 巡检项) 的最新一条记录。"""

    records = list(db.scalars(select(ComplianceRecord).order_by(ComplianceRecord.id)).all())

    latest: dict[tuple[int, int], ComplianceRecord] = {}

    for r in records:

        latest[(r.asset_id, r.item_id)] = r

    return latest

def compliance_summary(db: Session) -> dict:

    items = list(db.scalars(select(ComplianceItem).where(ComplianceItem.enabled.is_(True))))

    assets = list(db.scalars(select(Asset)))

    latest = latest_records(db)

    assets_map = {a.id: a for a in assets}

    per_item = []

    noncompliant: list[dict] = []

    ok_count = bad_count = 0

    for item in items:

        good = bad = 0

        for (asset_id, item_id), rec in latest.items():

            if item_id != item.id:

                continue

            if rec.result == "合规":

                good += 1

                ok_count += 1

            elif rec.result == "不合规":

                bad += 1

                bad_count += 1

                a = assets_map.get(asset_id)

                noncompliant.append({

                    "record_id": rec.id,

                    "asset_id": asset_id,

                    "asset_tag": a.asset_tag if a else "",

                    "asset_name": a.name if a else "",

                    "item_name": item.name,

                    "severity": item.severity,

                    "detail": rec.detail[:200],

                    "checked_at": rec.to_dict()["checked_at"],

                })

        total = good + bad

        per_item.append({

            "item_id": item.id,

            "name": item.name,

            "category": item.category,

            "severity": item.severity,

            "method": item.method,

            "total": total,

            "compliant": good,

            "noncompliant": bad,

            "rate": round(100 * good / total, 1) if total else None,

        })

    noncompliant.sort(key=lambda x: (x["severity"] != "高", x["severity"] != "中"))

    total = ok_count + bad_count

    return {

        "overall_rate": round(100 * ok_count / total, 1) if total else None,

        "per_item": per_item,

        "noncompliant": noncompliant,

        "terminals_total": len(assets),

    }

def upsert_agent_records(

    db: Session, asset: Asset, results: list[dict], scan_id: int | None = None

) -> int:

    """代理脚本上报：results = [{key, result, detail}]。item.key 匹配；未知 key 忽略并记录日志。"""

    items = {i.key: i for i in db.scalars(select(ComplianceItem)).all()}

    count = 0

    for r in results:

        item = items.get(r.get("key", ""))

        if not item:

            logger.warning("合规上报忽略未知巡检项 key=%s", r.get("key"))

            continue

        result = r.get("result", "")

        if result not in ("合规", "不合规"):

            continue

        db.add(ComplianceRecord(

            asset_id=asset.id, item_id=item.id, scan_id=scan_id,

            result=result, detail=(r.get("detail") or "")[:2000],

            checked_by="agent",

        ))

        count += 1

    db.commit()

    return count
