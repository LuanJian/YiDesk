"""后台定时任务：SLA 超时扫描、出站消息重试。

使用线程池型 BackgroundScheduler（任务内是同步阻塞 IO，避免阻塞事件循环）。
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import get_config
from app.models.database import create_session
from app.services import notify_service, sla_service, webhook_service

logger = logging.getLogger("jobs")

scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


def _sla_scan_job() -> None:
    db = create_session()
    try:
        logs = sla_service.scan(db)
        if logs:
            logger.info("SLA 扫描动作: %s", ", ".join(logs))
    except Exception:  # noqa: BLE001
        logger.exception("SLA 扫描失败")
    finally:
        db.close()


def _outbox_retry_job() -> None:
    db = create_session()
    try:
        sent = notify_service.flush(db)
        if sent:
            logger.info("Outbox 补投 %s 条", sent)
    except Exception:  # noqa: BLE001
        logger.exception("Outbox 重试失败")
    finally:
        db.close()


def _webhook_flush_job() -> None:
    db = create_session()
    try:
        sent = webhook_service.flush(db)
        if sent:
            logger.info("Webhook 投递 %s 条", sent)
    except Exception:  # noqa: BLE001
        logger.exception("Webhook 投递失败")
    finally:
        db.close()


def _backup_scan_job() -> None:
    """每 5 分钟扫描备份计划：到点执行 + 按份数轮换。"""
    from app.services import backup_service

    db = create_session()
    try:
        logs = backup_service.run_due_plans(db)
        for line in logs:
            logger.info("备份计划: %s", line)
    except Exception:  # noqa: BLE001
        logger.exception("备份计划扫描失败")
    finally:
        db.close()


def _daily_report_job() -> None:
    db = create_session()
    try:
        from app.services.v12_service import send_daily_report

        send_daily_report(db)
        logger.info("每日工单日报已发送")
    except Exception:  # noqa: BLE001
        logger.exception("日报发送失败")
    finally:
        db.close()


def _license_alert_job() -> None:
    db = create_session()
    try:
        from app.services.ledger_service import scan_license_alerts

        logs = scan_license_alerts(db)
        if logs:
            logger.info("许可预警: %s", ", ".join(logs))
    except Exception:  # noqa: BLE001
        logger.exception("许可预警扫描失败")
    finally:
        db.close()


def _device_probe_job() -> None:
    db = create_session()
    try:
        from app.services.ledger_service import probe_all_devices

        result = probe_all_devices(db)
        if result.get("offline"):
            logger.info("设备探活: %s", result)
    except Exception:  # noqa: BLE001
        logger.exception("设备探活失败")
    finally:
        db.close()


def _meeting_reminder_job() -> None:
    """v2.12 预约开始前 15 分钟推送预约人（每分钟扫描，reminded 标记防重发）。"""
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo

    db = create_session()
    try:
        from app.models.meeting import MeetingBooking
        from app.models.user import User
        from sqlalchemy import func, or_, select

        now_sh = _dt.now(ZoneInfo("Asia/Shanghai"))
        rows = db.scalars(
            select(MeetingBooking).where(
                MeetingBooking.status == MeetingBooking.STATUS_ACTIVE,
                MeetingBooking.reminded.is_(False),
            )
        ).all()
        sent = 0
        for b in rows:
            start_dt = _dt.combine(b.date, _dt.strptime(b.start_time, "%H:%M").time()).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            delta = (start_dt - now_sh).total_seconds() / 60
            if 0 <= delta <= 15:
                booker = db.get(User, b.booker_id)
                if booker:
                    from app.services import notify_service

                    notify_service.enqueue_for_user(
                        db, booker, ticket_id=None,
                        title=f"会议即将开始 {b.start_time}",
                        content=f"您预约的会议「{b.title or '未命名'}」将于 {b.start_time} 开始，请提前到场准备。",
                        url="",
                    )
                b.reminded = True
                sent += 1
        db.commit()
        if sent:
            logger.info("会议开始提醒: %s 场", sent)
    except Exception:  # noqa: BLE001
        logger.exception("会议提醒扫描失败")
    finally:
        db.close()


def _login_log_cleanup_job() -> None:
    """第三十七批：登录日志保留策略——每日清理超期记录（login_log_retention_days，默认 90 天，0=不清理）。"""
    from datetime import timedelta

    from app.core.config import get_config

    days = get_config().login_log_retention_days
    if days <= 0:
        return
    db = create_session()
    try:
        from app.models.login_log import LoginLog
        from app.models.user import utcnow

        cutoff = utcnow() - timedelta(days=days)
        n = db.query(LoginLog).filter(LoginLog.created_at < cutoff).delete()
        db.commit()
        if n:
            logging.getLogger("jobs").info("登录日志清理: 删除 %s 条早于 %s 的记录（保留 %s 天）", n, cutoff.date(), days)
    finally:
        db.close()


def _asset_expire_job() -> None:
    """第三十八批：资产到期提醒（每日 09:05）——「在用」资产的维保/租期到期日落在近 30 天内或已过期时，
    通知全部管理员一次（expire_warned 标记防重复，改期时由服务层重置）。"""
    from datetime import datetime as _dt, timedelta as _td
    from zoneinfo import ZoneInfo

    db = create_session()
    try:
        from app.models.knowledge import Asset
        from app.models.user import User
        from sqlalchemy import select

        today = _dt.now(ZoneInfo("Asia/Shanghai")).date()
        horizon = today + _td(days=30)
        due = []
        for a in db.scalars(select(Asset).where(Asset.status == "在用", Asset.expire_warned.is_(False), Asset.expire_date.is_not(None))).all():
            try:
                d = _dt.strptime(a.expire_date, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue
            if d <= horizon:
                due.append((a, (d - today).days))
        if not due:
            return
        from app.services import notify_service

        admins = list(db.scalars(select(User).where(User.role == "admin", User.is_active.is_(True))).all())
        for a, remain in due:
            tip = f"已过期 {-remain} 天" if remain < 0 else f"剩余 {remain} 天"
            for admin in admins:
                notify_service.enqueue_for_user(
                    db, admin, ticket_id=None,
                    title=f"资产到期提醒：{a.asset_tag} {a.name}",
                    content=f"「{a.asset_tag} {a.name}」（{a.location or '位置未填'}）到期日 {a.expire_date}，{tip}，请及时安排续保或处置。",
                    url="",
                )
            a.expire_warned = True
        db.commit()
        logger.info("资产到期提醒: %s 台", len(due))
    except Exception:  # noqa: BLE001
        logger.exception("资产到期扫描失败")
    finally:
        db.close()


def _inspection_due_job() -> None:
    """会议室定期巡检（每 6 小时扫描）。

    v2.12：按天周期到期 → 提醒全部管理员。
    第三十九批扩展：①周期支持 day（每 N 天）/ week（每 N 周）/ session（每 N 场已结束预约）
    ②到期自动生成巡检工单，按轮询派给现场运维（field 岗位）处理，同时保留管理员提醒；
    同一房间存在未结巡检工单时不重复生成。
    """
    import json as _json
    from datetime import datetime as _dt, timedelta
    from zoneinfo import ZoneInfo

    db = create_session()
    try:
        from app.models.meeting import MeetingBooking, MeetingRoom, RoomInspection
        from app.models.ticket import STATUS_CLOSED, Ticket
        from app.models.user import User
        from sqlalchemy import select

        now_sh = _dt.now(ZoneInfo("Asia/Shanghai"))
        tz = ZoneInfo("Asia/Shanghai")
        today = now_sh.date()
        admins = list(db.scalars(select(User).where(User.role == "admin", User.is_active.is_(True))).all())
        overdue: list[tuple[MeetingRoom, str]] = []
        for room in db.scalars(select(MeetingRoom).where(MeetingRoom.enabled.is_(True))).all():
            unit = (room.check_cycle_unit or "day")
            value = room.check_cycle_value or room.check_cycle_days  # 兼容旧值
            if not value or value <= 0:
                continue
            last = db.scalar(
                select(RoomInspection).where(RoomInspection.room_id == room.id).order_by(RoomInspection.id.desc()).limit(1)
            )
            last_at = last.inspected_at.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz) if last and last.inspected_at else None
            if unit == "session":
                # 场次模式：上次检查之后（按会议实际日期）已结束的预约达到 N 场（第四十批修正口径）
                last_date = last_at.date() if last_at else None
                sessions = db.query(MeetingBooking).filter(
                    MeetingBooking.room_id == room.id,
                    MeetingBooking.status == MeetingBooking.STATUS_ACTIVE,
                    MeetingBooking.date < today,
                    MeetingBooking.date > (last_date or _dt.min.date()),
                ).count()
                if sessions >= value:
                    overdue.append((room, f"距上次检查已累计 {sessions} 场使用（周期每 {value} 场）"))
            else:
                days = value * 7 if unit == "week" else value
                due_days = (today - last_at.date()).days if last_at else None
                if last_at is None or due_days is None or due_days >= days:
                    unit_label = "周" if unit == "week" else "天"
                    tip = f"距上次检查已 {due_days} 天" if due_days is not None else "从未检查"
                    overdue.append((room, f"{tip}（周期每 {value} {unit_label}）"))
        if not overdue:
            return

        from app.services import notify_service, ticket_service

        # 现场运维轮询序列：field 岗位在职在岗工程师按 id 排序；上一张巡检工单处理人之后的人
        field_engs = [
            u for u in db.scalars(
                select(User).where(
                    User.role == "engineer", User.is_active.is_(True),
                    (User.ops_type or "other") == "field",
                ).order_by(User.id)
            ).all()
        ]
        last_inspection_ticket = db.scalar(
            select(Ticket).where(Ticket.status != STATUS_CLOSED, Ticket.title.like("会议室巡检%")).order_by(Ticket.id.desc()).limit(1)
        ) or db.scalar(
            select(Ticket).where(Ticket.title.like("会议室巡检%")).order_by(Ticket.id.desc()).limit(1)
        )
        rotate_from = last_inspection_ticket.assignee_id if last_inspection_ticket else None
        idx = 0
        if rotate_from and field_engs:
            ids = [e.id for e in field_engs]
            idx = (ids.index(rotate_from) + 1) % len(ids) if rotate_from in ids else 0

        for room, reason in overdue:
            # 防重复：该房间已有未结巡检工单（第四十五批：改按 custom_fields.meeting_room_id JSON
            # 精确匹配——会议室改名后标题前缀不再匹配会导致防重复失效；保留标题匹配兜底存量旧单）
            open_same = db.query(Ticket).filter(
                or_(
                    func.json_extract(Ticket.custom_fields, "$.meeting_room_id") == room.id,
                    Ticket.title.like(f"会议室巡检：{room.name}%"),
                ),
                Ticket.status.in_(("pending", "processing", "pending_confirm")),
            ).first()
            if open_same:
                continue
            # 生成巡检工单（系统行为：actor=admin），按轮询派给现场运维
            sys_actor = admins[0]
            equip_bad = [e["name"] for e in room.equipment_items if e.get("status") in ("维修中", "损坏")]
            desc = (
                f"巡检原因：{reason}。\n"
                f"请到 {room.location or '会议室'} 现场检查设备状态并在会议室码完成检查填报。"
                + (f"\n已知异常设备：{'、'.join(equip_bad)}。" if equip_bad else "")
            )
            ticket = ticket_service.create_ticket(
                db,
                creator=sys_actor,
                title=f"会议室巡检：{room.name}",
                description=desc,
                category="其他问题",
                priority="low" if (room.check_cycle_unit or "day") == "week" else "medium",
                custom_fields={"meeting_room_id": room.id, "meeting_room": room.name, "巡检类型": "定期巡检"},
                validate_fields=False,
            )
            if field_engs:
                engineer = field_engs[idx % len(field_engs)]
                idx += 1
                ticket_service.assign_ticket(db, ticket=ticket, actor=sys_actor, engineer=engineer,
                                             reason="巡检工单轮询派发现场运维", skip_scope_check=True)
                ticket.custom_fields = _json.dumps(
                    {"meeting_room_id": room.id, "meeting_room": room.name, "巡检类型": "定期巡检"},
                    ensure_ascii=False,
                )
            for admin in admins:
                notify_service.enqueue_for_user(
                    db, admin, ticket_id=ticket.id,
                    title=f"会议室巡检工单已生成：{room.name}",
                    content=f"「{room.name}」{reason}，已自动生成巡检工单 {ticket.no}"
                            + (f"并派给 {ticket.assignee.name}" if ticket.assignee else "（无现场运维可派，请在工单台指派）"),
                    url="",
                )
            logger.info("会议室巡检工单: %s → %s（%s）", room.name, ticket.no, reason)
        db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("会议室巡检扫描失败")
    finally:
        db.close()


def _deferred_assign_job() -> None:
    """「其他问题」延迟分派扫描（第二十七批+，每分钟）：建单超 deferred_minutes 未指派则按负载/顺序分配。"""
    from datetime import datetime as _dt, timedelta as _td

    from sqlalchemy import select

    from app.core.config import get_config
    from app.models.database import create_session
    from app.models.ticket import Ticket
    from app.services import v12_service

    minutes = get_config().dispatch.deferred_minutes
    if minutes <= 0:
        return
    db = create_session()
    try:
        cutoff = _dt.utcnow() - _td(minutes=minutes)
        pending = list(db.scalars(
            select(Ticket).where(
                Ticket.category == "其他问题",
                Ticket.status == "pending",
                Ticket.assignee_id.is_(None),
                Ticket.merged_into_id.is_(None),
                Ticket.created_at <= cutoff,
            ).order_by(Ticket.id)
        ).all())
        for t in pending:
            try:
                if v12_service.assign_deferred(db, t):
                    logger.info("延迟分派: %s -> %s", t.no, t.assignee.name if t.assignee else "?")
            except Exception as exc:  # noqa: BLE001
                logger.error("延迟分派失败 %s: %s", t.no, exc)
                db.rollback()
    finally:
        db.close()


def start() -> None:
    if scheduler.get_jobs():
        return
    scheduler.add_job(_sla_scan_job, "interval", seconds=60, id="sla_scan", max_instances=1, coalesce=True)
    scheduler.add_job(_outbox_retry_job, "interval", seconds=60, id="outbox_retry", max_instances=1, coalesce=True)
    scheduler.add_job(_webhook_flush_job, "interval", seconds=60, id="webhook_flush", max_instances=1, coalesce=True)
    scheduler.add_job(_backup_scan_job, "interval", minutes=5, id="backup_scan", max_instances=1, coalesce=True)
    scheduler.add_job(_deferred_assign_job, "interval", seconds=60, id="deferred_assign", max_instances=1, coalesce=True)
    scheduler.add_job(_login_log_cleanup_job, "cron", hour=3, minute=10, id="login_log_cleanup", max_instances=1, coalesce=True)
    scheduler.add_job(_asset_expire_job, "cron", hour=9, minute=5, id="asset_expire", max_instances=1, coalesce=True)

    cfg = get_config().report
    if cfg.enabled:
        try:
            hh, mm = cfg.time.split(":")[:2]
            scheduler.add_job(
                _daily_report_job, "cron", hour=int(hh), minute=int(mm),
                id="daily_report", max_instances=1, coalesce=True,
            )
            logger.info("每日工单日报已排程: %s", cfg.time)
        except ValueError:
            logger.error("日报时间格式错误: %s（应为 HH:MM）", cfg.time)

    lic_cfg = get_config().licenses
    scheduler.add_job(_license_alert_job, "cron", hour=9, minute=30, id="license_alert", max_instances=1, coalesce=True)
    # v2.12 会议室：预约开始提醒（每分钟）+ 巡检超期扫描（每 6 小时）
    scheduler.add_job(_meeting_reminder_job, "interval", minutes=1, id="meeting_reminder", max_instances=1, coalesce=True)
    scheduler.add_job(_inspection_due_job, "interval", hours=6, id="inspection_due", max_instances=1, coalesce=True)

    net_cfg = get_config().network
    if net_cfg.probe_enabled:
        scheduler.add_job(
            _device_probe_job, "interval", seconds=max(60, net_cfg.probe_interval_seconds),
            id="device_probe", max_instances=1, coalesce=True,
        )
        logger.info("网络设备探活已排程: 每 %s 秒", net_cfg.probe_interval_seconds)

    scheduler.start()
    logger.info("定时任务已启动（SLA 扫描 / Outbox 重试，各 60s）")


def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
