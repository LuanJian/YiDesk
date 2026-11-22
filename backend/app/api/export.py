"""数据导出：工单 CSV（UTF-8 BOM，Excel 直接打开不乱码）。

支持按日/按月/按年/全部四种范围；v2.11 起仅管理员可导出（非管理员无任何导出权限）。

查询全部使用 SQLAlchemy 表达式与对象查询（服务端参数化），不拼接 SQL 字符串。

"""

from __future__ import annotations

import csv

import io

from datetime import datetime, timedelta

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException

from fastapi.responses import Response, StreamingResponse

from sqlalchemy import select

from sqlalchemy.orm import Session, aliased

from app.core.deps import require_admin

from app.models.database import get_db

from app.models.ticket import PRIORITY_LABELS, STATUS_LABELS, Rating, Ticket

from app.models.user import User, utcnow

router = APIRouter()

CHANNEL_LABELS = {"web": "Web", "dingtalk": "钉钉", "feishu": "飞书", "wecom": "企业微信"}

HEADERS = [

    "工单编号", "问题概述", "问题分类", "优先级", "状态", "发起人", "提出者", "处理人", "来源",

    "创建时间", "首次响应", "解决时间", "解决时长(分)", "响应是否超时", "解决是否超时", "满意度",

]

EXPORT_MODES = ("day", "month", "year", "all")

def _fmt(dt) -> str:

    return dt.strftime("%Y-%m-%d %H:%M") if dt else ""

def _mode_window(mode: str, date_str: str | None) -> tuple[datetime, datetime] | None:

    """导出范围 → [start, end)（UTC）；all 返回 None。非法日期转 400。

    用户选择的日/月/年按公司时区（Asia/Shanghai，与定时任务一致）理解，

    再换算为 UTC 区间过滤——否则本地上午提的单（UTC 还是昨天）会落错窗口。

    """

    try:

        anchor = datetime.strptime(date_str, "%Y-%m-%d") if date_str else utcnow()

    except ValueError as exc:

        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD") from exc

    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Shanghai")

    start_local = anchor.replace(tzinfo=tz)

    end_local = start_local + timedelta(days=1)

    if mode == "month":

        start_local = anchor.replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=tz)

        end_local = (start_local + timedelta(days=32)).replace(day=1)

    elif mode == "year":

        start_local = anchor.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=tz)

        end_local = start_local.replace(year=anchor.year + 1)

    elif mode != "day":

        return None

    # 换算为 naive UTC 与库内存储一致

    to_utc = lambda dt: dt.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

    return to_utc(start_local), to_utc(end_local)

@router.get("/monthly-report")

def export_monthly_report(

    month: str = "",

    db: Session = Depends(get_db),

    _: User = Depends(require_admin),

):

    """运维月报 PDF 导出：按月统计概览/分类/处理人/超时明细，admin。"""

    from app.services import report_service

    try:

        year, mon = (int(x) for x in (month or "").split("-"))

        assert 2020 <= year <= 2100 and 1 <= mon <= 12

    except Exception:

        raise HTTPException(status_code=400, detail="month 参数格式应为 YYYY-MM")

    pdf_bytes = report_service.monthly_report_pdf(db, year, mon)

    filename = f"运维月报-{year}-{mon:02d}.pdf"

    return Response(

        content=pdf_bytes,

        media_type="application/pdf",

        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},

    )

@router.get("/tickets")

def export_tickets(

    mode: str = "all",

    date: str | None = None,

    status: str | None = None,

    category: str | None = None,

    priority: str | None = None,

    days: int | None = None,

    # 按当前筛选导出——处理人/发起人（id 精确或人名模糊）/关键词（概述+编号）

    assignee_name: str | None = None,

    creator_name: str | None = None,

    assignee_id: int | None = None,

    creator_id: int | None = None,

    q: str | None = None,

    db: Session = Depends(get_db),

    _: User = Depends(require_admin),

):

    """工单导出：mode=day/month/year/all，可叠加列表筛选（分类/优先级/处理人/发起人/关键词）；v2.11 起仅管理员可用。"""

    if mode not in EXPORT_MODES:

        raise HTTPException(status_code=400, detail="mode 必须是 day/month/year/all")

    window = _mode_window(mode, date)

    stmt = select(Ticket).order_by(Ticket.id.desc())

    if window:

        stmt = stmt.where(Ticket.created_at >= window[0], Ticket.created_at < window[1])

    if status:

        stmt = stmt.where(Ticket.status == status)

    if category:

        stmt = stmt.where(Ticket.category == category)

    if priority:

        stmt = stmt.where(Ticket.priority == priority)

    if days:

        stmt = stmt.where(Ticket.created_at >= utcnow() - timedelta(days=days))

    if assignee_id:

        stmt = stmt.where(Ticket.assignee_id == assignee_id)

    if creator_id:

        stmt = stmt.where(Ticket.creator_id == creator_id)

    if assignee_name:

        stmt = stmt.join(User, Ticket.assignee_id == User.id).where(

            (User.name.contains(assignee_name)) | (User.username.contains(assignee_name))

        )

    if creator_name:

        creator_alias = aliased(User)

        stmt = stmt.join(creator_alias, Ticket.creator_id == creator_alias.id).where(

            (creator_alias.name.contains(creator_name)) | (creator_alias.username.contains(creator_name))

        )

    if q:

        stmt = stmt.where((Ticket.title.contains(q)) | (Ticket.no.contains(q)))

    tickets = list(db.scalars(stmt).all())

    ratings = {r.ticket_id: r.stars for r in db.scalars(select(Rating)).all()}

    requesters = {u.id: (u.name or u.username) for u in db.scalars(select(User)).all()}

    buf = io.StringIO()

    writer = csv.writer(buf)

    writer.writerow(HEADERS)

    for t in tickets:

        resolve_minutes = ""

        if t.resolved_at and t.created_at:

            resolve_minutes = round((t.resolved_at - t.created_at).total_seconds() / 60)

        resp_breach = "是" if t.sla_response_deadline and t.first_responded_at and t.first_responded_at > t.sla_response_deadline else "否"

        res_breach = "是" if t.sla_resolve_deadline and t.resolved_at and t.resolved_at > t.sla_resolve_deadline else "否"

        writer.writerow([

            t.no, t.title, t.category, PRIORITY_LABELS.get(t.priority, t.priority),

            STATUS_LABELS.get(t.status, t.status),

            (t.creator.name or t.creator.username) if t.creator else "",

            requesters.get(t.requester_id, "") if t.requester_id else "",

            (t.assignee.name or t.assignee.username) if t.assignee else "",

            CHANNEL_LABELS.get(t.channel, t.channel),

            _fmt(t.created_at), _fmt(t.first_responded_at), _fmt(t.resolved_at),

            resolve_minutes, resp_breach, res_breach,

            f"{ratings[t.id]}星" if t.id in ratings else "",

        ])

    buf.seek(0)

    csv_bytes = b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")  # UTF-8 BOM

    d = date or utcnow().strftime("%Y-%m-%d")

    label = {"day": f"按日_{d}", "month": f"按月_{d[:7]}", "year": f"按年_{d[:4]}", "all": "全部"}[mode]

    # RFC 5987：文件名含中文需 filename*=UTF-8'' 编码（HTTP 头仅 latin-1）

    from urllib.parse import quote

    fname = f"工单导出_{label}.csv"

    return StreamingResponse(

        iter([csv_bytes]),

        media_type="text/csv; charset=utf-8",

        headers={

            "Content-Disposition": (

                "attachment; filename=\"export.csv\"; "

                f"filename*=UTF-8''{quote(fname)}"

            )

        },

    )
