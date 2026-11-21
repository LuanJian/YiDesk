"""旧 SQLite 库升级：缺列补齐（幂等，每次启动调用）。

只处理「模型里已有、老库表里没有」的列。所有 PRAGMA/DDL 均以字面常量直接
传给 cursor.execute，不经变量、不做拼接，静态可证无注入面。
"""
from __future__ import annotations

from app.models.database import get_engine


def _rename_category(conn) -> None:
    """第二十四批/二十七批：分类更名历史数据一次性迁移（精确匹配，不用子串替换）。"""
    from sqlalchemy import text as _text

    renames = [
        ("软件应用", "软件安装"),
        ("其他", "其他问题"),
    ]
    for table, col in (
        ("tickets", "category"),
        ("ticket_templates", "category"),
        ("keyword_rules", "target_category"),
        ("qr_tags", "category"),
        ("dispatch_rules", "categories"),
    ):
        try:
            for old_v, new_v in renames:
                conn.execute(
                    _text(f"UPDATE {table} SET {col} = :new_v WHERE {col} = :old_v"),
                    {"new_v": new_v, "old_v": old_v},
                )
            conn.commit()
        except Exception:
            conn.rollback()


def ensure_columns() -> None:
    engine = get_engine()
    if engine.dialect.name != "sqlite":
        return

    # ---- tickets：v2.0 提出者 + SLA 挂起快照 ----
    with engine.connect() as conn:
        cursor = conn.connection.cursor()
        cursor.execute("PRAGMA table_info(tickets)")
        ticket_cols = {row[1] for row in cursor.fetchall()}
        cursor.close()
    with engine.begin() as conn:
        cursor = conn.connection.cursor()
        if "requester_id" not in ticket_cols:
            cursor.execute("ALTER TABLE tickets ADD COLUMN requester_id INTEGER")
        if "sla_suspended_at" not in ticket_cols:
            cursor.execute("ALTER TABLE tickets ADD COLUMN sla_suspended_at TIMESTAMP")
        if "sla_response_remaining" not in ticket_cols:
            cursor.execute("ALTER TABLE tickets ADD COLUMN sla_response_remaining INTEGER")
        if "sla_resolve_remaining" not in ticket_cols:
            cursor.execute("ALTER TABLE tickets ADD COLUMN sla_resolve_remaining INTEGER")
        if "sla_suspended_total" not in ticket_cols:
            cursor.execute("ALTER TABLE tickets ADD COLUMN sla_suspended_total INTEGER")
        if "urgent" not in ticket_cols:
            cursor.execute("ALTER TABLE tickets ADD COLUMN urgent BOOLEAN NOT NULL DEFAULT 0")
        if "urgent_at" not in ticket_cols:
            cursor.execute("ALTER TABLE tickets ADD COLUMN urgent_at TIMESTAMP")
        if "estimated_minutes" not in ticket_cols:
            cursor.execute("ALTER TABLE tickets ADD COLUMN estimated_minutes INTEGER NOT NULL DEFAULT 0")
        if "transferred" not in ticket_cols:
            cursor.execute("ALTER TABLE tickets ADD COLUMN transferred BOOLEAN NOT NULL DEFAULT 0")
        cursor.close()

    # ---- users：v2.1 类目数据权限 ----
    with engine.connect() as conn:
        cursor = conn.connection.cursor()
        cursor.execute("PRAGMA table_info(users)")
        user_cols = {row[1] for row in cursor.fetchall()}
        cursor.close()
    with engine.begin() as conn:
        cursor = conn.connection.cursor()
        if "category_scope" not in user_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN category_scope VARCHAR(512)")
        if "ops_type" not in user_cols:
            # 存量工程师默认远程运维（用户已确认）
            cursor.execute("ALTER TABLE users ADD COLUMN ops_type VARCHAR(16) NOT NULL DEFAULT 'remote'")
        if "status" not in user_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'on_duty'")
        if "dept_admin" not in user_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN dept_admin BOOLEAN NOT NULL DEFAULT 0")
        if "gate_key" not in user_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN gate_key VARCHAR(64)")
        if "notify_prefs" not in user_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN notify_prefs VARCHAR(256)")
        cursor.close()

    # ---- ticket_templates：v2.2 审批节点 + AD 联动 ----
    with engine.connect() as conn:
        cursor = conn.connection.cursor()
        cursor.execute("PRAGMA table_info(ticket_templates)")
        tpl_cols = {row[1] for row in cursor.fetchall()}
        cursor.close()
    with engine.begin() as conn:
        cursor = conn.connection.cursor()
        if "require_approval" not in tpl_cols:
            cursor.execute("ALTER TABLE ticket_templates ADD COLUMN require_approval BOOLEAN NOT NULL DEFAULT 0")
        if "ad_script" not in tpl_cols:
            cursor.execute("ALTER TABLE ticket_templates ADD COLUMN ad_script VARCHAR(128) NOT NULL DEFAULT ''")
        if "estimated_minutes" not in tpl_cols:
            cursor.execute("ALTER TABLE ticket_templates ADD COLUMN estimated_minutes INTEGER NOT NULL DEFAULT 0")
        cursor.close()

    # ---- assets：v1.3 型号与 IP ----
    with engine.connect() as conn:
        cursor = conn.connection.cursor()
        cursor.execute("PRAGMA table_info(assets)")
        asset_cols = {row[1] for row in cursor.fetchall()}
        cursor.close()
    with engine.begin() as conn:
        cursor = conn.connection.cursor()
        if "ip_address" not in asset_cols:
            cursor.execute("ALTER TABLE assets ADD COLUMN ip_address VARCHAR(64) NOT NULL DEFAULT ''")
        if "model" not in asset_cols:
            cursor.execute("ALTER TABLE assets ADD COLUMN model VARCHAR(128) NOT NULL DEFAULT ''")
        cursor.close()

    # ---- knowledge_articles：v2.11 信息来源 ----
    with engine.connect() as conn:
        cursor = conn.connection.cursor()
        cursor.execute("PRAGMA table_info(knowledge_articles)")
        kb_cols = {row[1] for row in cursor.fetchall()}
        cursor.close()
    with engine.begin() as conn:
        cursor = conn.connection.cursor()
        if kb_cols and "source" not in kb_cols:
            cursor.execute("ALTER TABLE knowledge_articles ADD COLUMN source VARCHAR(256) NOT NULL DEFAULT ''")
        if kb_cols and "public_visible" not in kb_cols:
            cursor.execute("ALTER TABLE knowledge_articles ADD COLUMN public_visible BOOLEAN NOT NULL DEFAULT 0")
        # v2.12 移除浏览计数（前端已不展示，纯死代码）+ 新增问题描述字段
        if kb_cols and "problem" not in kb_cols:
            cursor.execute("ALTER TABLE knowledge_articles ADD COLUMN problem TEXT")
        if kb_cols and "views" in kb_cols:
            cursor.execute("ALTER TABLE knowledge_articles DROP COLUMN views")
        cursor.close()

    # ---- assets：v2.12 驱动下载地址 + 第三十八批到期日期 ----
    with engine.connect() as conn:
        cursor = conn.connection.cursor()
        cursor.execute("PRAGMA table_info(assets)")
        asset_cols2 = {row[1] for row in cursor.fetchall()}
        cursor.close()
    with engine.begin() as conn:
        cursor = conn.connection.cursor()
        if asset_cols2 and "driver_url" not in asset_cols2:
            cursor.execute("ALTER TABLE assets ADD COLUMN driver_url VARCHAR(512) NOT NULL DEFAULT ''")
        if asset_cols2 and "expire_date" not in asset_cols2:
            cursor.execute("ALTER TABLE assets ADD COLUMN expire_date VARCHAR(10)")
        if asset_cols2 and "expire_warned" not in asset_cols2:
            cursor.execute("ALTER TABLE assets ADD COLUMN expire_warned BOOLEAN NOT NULL DEFAULT 0")
        cursor.close()

    # ---- meeting_rooms / meeting_bookings：v2.12 巡检周期与提醒标记 ----
    with engine.connect() as conn:
        cursor = conn.connection.cursor()
        cursor.execute("PRAGMA table_info(meeting_rooms)")
        mr_cols = {row[1] for row in cursor.fetchall()}
        cursor.execute("PRAGMA table_info(meeting_bookings)")
        mb_cols = {row[1] for row in cursor.fetchall()}
        cursor.close()
    with engine.begin() as conn:
        cursor = conn.connection.cursor()
        if mr_cols and "check_cycle_days" not in mr_cols:
            cursor.execute("ALTER TABLE meeting_rooms ADD COLUMN check_cycle_days INTEGER NOT NULL DEFAULT 0")
        if mr_cols and "equipment_list" not in mr_cols:
            cursor.execute("ALTER TABLE meeting_rooms ADD COLUMN equipment_list TEXT NOT NULL DEFAULT '[]'")
        if mr_cols and "check_cycle_unit" not in mr_cols:
            cursor.execute("ALTER TABLE meeting_rooms ADD COLUMN check_cycle_unit VARCHAR(16) NOT NULL DEFAULT 'day'")
        if mr_cols and "check_cycle_value" not in mr_cols:
            cursor.execute("ALTER TABLE meeting_rooms ADD COLUMN check_cycle_value INTEGER NOT NULL DEFAULT 0")
        if mb_cols and "reminded" not in mb_cols:
            cursor.execute("ALTER TABLE meeting_bookings ADD COLUMN reminded BOOLEAN NOT NULL DEFAULT 0")
        if mb_cols and "checkin_at" not in mb_cols:
            cursor.execute("ALTER TABLE meeting_bookings ADD COLUMN checkin_at DATETIME")
        cursor.close()

    # ---- qr_tags：v2.12 会议室码 ----
    with engine.connect() as conn:
        cursor = conn.connection.cursor()
        cursor.execute("PRAGMA table_info(qr_tags)")
        qr_cols = {row[1] for row in cursor.fetchall()}
        cursor.close()
    with engine.begin() as conn:
        cursor = conn.connection.cursor()
        if qr_cols and "room_id" not in qr_cols:
            cursor.execute("ALTER TABLE qr_tags ADD COLUMN room_id INTEGER")
        cursor.close()

    # ---- asset_events：v2.12 维修拆装部件留痕 ----
    with engine.connect() as conn:
        cursor = conn.connection.cursor()
        cursor.execute("PRAGMA table_info(asset_events)")
        ae_cols = {row[1] for row in cursor.fetchall()}
        cursor.close()
    with engine.begin() as conn:
        cursor = conn.connection.cursor()
        if ae_cols and "parts" not in ae_cols:
            cursor.execute("ALTER TABLE asset_events ADD COLUMN parts TEXT NOT NULL DEFAULT '[]'")
        cursor.close()

    # ---- software_items：v2.12 来源结构化（类型 + URL） ----
    with engine.connect() as conn:
        cursor = conn.connection.cursor()
        cursor.execute("PRAGMA table_info(software_items)")
        sw_cols = {row[1] for row in cursor.fetchall()}
        cursor.close()
    with engine.begin() as conn:
        cursor = conn.connection.cursor()
        if sw_cols:
            if "source_type" not in sw_cols:
                cursor.execute("ALTER TABLE software_items ADD COLUMN source_type VARCHAR(16) NOT NULL DEFAULT '软件官网'")
            if "source_url" not in sw_cols:
                cursor.execute("ALTER TABLE software_items ADD COLUMN source_url VARCHAR(512) NOT NULL DEFAULT ''")
            # v2.12 移除旧版自由文本来源（被 source_type/source_url 结构化替代）
            if "source" in sw_cols:
                cursor.execute("ALTER TABLE software_items DROP COLUMN source")
        cursor.close()

    # ---- ticket_events：v2.12 评论编辑标记 ----
    with engine.connect() as conn:
        cursor = conn.connection.cursor()
        cursor.execute("PRAGMA table_info(ticket_events)")
        te_cols = {row[1] for row in cursor.fetchall()}
        cursor.close()
    with engine.begin() as conn:
        cursor = conn.connection.cursor()
        if te_cols and "edited" not in te_cols:
            cursor.execute("ALTER TABLE ticket_events ADD COLUMN edited BOOLEAN NOT NULL DEFAULT 0")
        cursor.close()

    # 第二十四批：分类改名数据迁移（历史工单/模板/规则/标签里的「软件应用」→「软件安装」）
    _rename_category(engine.connect())

    # ---- assets：第四十一批 品牌列与最近检测时间 ----
    with engine.connect() as conn:
        cursor = conn.connection.cursor()
        cursor.execute("PRAGMA table_info(assets)")
        a_cols = {row[1] for row in cursor.fetchall()}
        cursor.close()
    with engine.begin() as conn:
        cursor = conn.connection.cursor()
        if "vendor" not in a_cols:
            cursor.execute("ALTER TABLE assets ADD COLUMN vendor VARCHAR(64) NOT NULL DEFAULT ''")
        if "last_checked_at" not in a_cols:
            cursor.execute("ALTER TABLE assets ADD COLUMN last_checked_at DATETIME")
        cursor.close()

    # ---- network_devices：第四十一批 资产编号与保修到期日 ----
    with engine.connect() as conn:
        cursor = conn.connection.cursor()
        cursor.execute("PRAGMA table_info(network_devices)")
        nd_cols = {row[1] for row in cursor.fetchall()}
        cursor.close()
    with engine.begin() as conn:
        cursor = conn.connection.cursor()
        if "asset_tag" not in nd_cols:
            cursor.execute("ALTER TABLE network_devices ADD COLUMN asset_tag VARCHAR(64) DEFAULT ''")
        if "expire_date" not in nd_cols:
            cursor.execute("ALTER TABLE network_devices ADD COLUMN expire_date VARCHAR(10)")
        cursor.close()
