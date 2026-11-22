"""运维月报 PDF 生成：按月统计导出，中文排版（fpdf2 + Noto Sans SC）。"""

from __future__ import annotations

import os

from datetime import datetime, timezone

from io import BytesIO

from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from sqlalchemy.orm import Session

from app.models.ticket import Ticket

FONT_PATH = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "fonts", "NotoSansSC-Regular.otf"))

_SH = ZoneInfo("Asia/Shanghai")

def _month_range(year: int, month: int) -> tuple[datetime, datetime]:

    start = datetime(year, month, 1, 0, 0, 0, tzinfo=_SH).replace(tzinfo=None)

    if month == 12:

        end = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=_SH).replace(tzinfo=None)

    else:

        end = datetime(year, month + 1, 1, 0, 0, 0, tzinfo=_SH).replace(tzinfo=None)

    return start, end

def _month_stats(db: Session, year: int, month: int) -> dict:

    start, end = _month_range(year, month)

    rows = list(

        db.scalars(

            select(Ticket).where(Ticket.created_at >= start, Ticket.created_at < end)

        ).all()

    )

    created = len(rows)

    resolved = len([t for t in rows if t.resolved_at and start <= t.resolved_at.replace(tzinfo=None) < end])

    closed = len([t for t in rows if t.status == "closed"])

    resp_times = [

        (t.first_responded_at.replace(tzinfo=None) - t.created_at.replace(tzinfo=None)).total_seconds() / 60

        for t in rows

        if t.first_responded_at and t.created_at

    ]

    res_times = [

        (t.resolved_at.replace(tzinfo=None) - t.created_at.replace(tzinfo=None)).total_seconds() / 60

        for t in rows

        if t.resolved_at and t.created_at

    ]

    urgent = len([t for t in rows if t.priority == "urgent"])

    breached_rows = [

        t for t in rows

        if t.sla_resolve_deadline and (

            (t.resolved_at and t.resolved_at.replace(tzinfo=None) > t.sla_resolve_deadline)

            or (not t.resolved_at and datetime.now() > t.sla_resolve_deadline)

        )

    ]

    breached = len(breached_rows)

    return {

        "created": created,

        "resolved": resolved,

        "closed": closed,

        "avg_resp": round(sum(resp_times) / len(resp_times)) if resp_times else 0,

        "avg_res": round(sum(res_times) / len(res_times)) if res_times else 0,

        "urgent": urgent,

        "breached": breached,

        "rows": rows,

    }

def monthly_report_pdf(db: Session, year: int, month: int) -> bytes:

    """生成运维月报 PDF：概览指标 + 问题分类分布 + 处理人工作量 + 超时工单列表。"""

    from fpdf import FPDF

    stats = _month_stats(db, year, month)

    rows: list[Ticket] = stats["rows"]

    # 超时工单集合（供明细表）

    breached_rows = [

        t for t in rows

        if t.sla_resolve_deadline and (

            (t.resolved_at and t.resolved_at.replace(tzinfo=None) > t.sla_resolve_deadline)

            or (not t.resolved_at and datetime.now() > t.sla_resolve_deadline)

        )

    ]

    pdf = FPDF(format="A4")

    pdf.add_font("NotoSC", "", FONT_PATH)

    pdf.set_auto_page_break(auto=True, margin=16)

    pdf.add_page()

    # 标题

    pdf.set_font("NotoSC", size=18)

    pdf.cell(text=f"YiDesk · 运维月报（{year} 年 {month} 月）", new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.ln(2)

    pdf.set_font("NotoSC", size=10)

    pdf.set_text_color(120, 120, 120)

    pdf.cell(text=f"生成时间 {datetime.now(_SH).strftime('%Y-%m-%d %H:%M')} · 工单创建时间按月统计", new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.set_text_color(0, 0, 0)

    pdf.ln(4)

    def _table(headers: list[str], widths: list[float], data_rows: list[list[str]]) -> None:

        pdf.set_font("NotoSC", size=10)

        pdf.set_fill_color(29, 37, 53)

        pdf.set_text_color(255, 255, 255)

        for h, w in zip(headers, widths):

            pdf.cell(w, 8, h, border=1, fill=True, align="C")

        pdf.ln()

        pdf.set_text_color(0, 0, 0)

        pdf.set_fill_color(245, 246, 248)

        for dr in data_rows:

            for v, w in zip(dr, widths):

                pdf.cell(w, 7, str(v), border=1, fill=True, align="C")

            pdf.ln()

        pdf.ln(2)

    # 一、概览指标

    pdf.set_font("NotoSC", size=13)

    pdf.cell(text="一、服务概览", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(1)

    _table(

        ["新建工单", "本月解决", "已关闭", "危急/紧急单", "SLA 超时", "平均响应(分)", "平均解决(分)"],

        [26, 26, 26, 30, 24, 30, 30],

        [[

            stats["created"], stats["resolved"], stats["closed"], stats["urgent"],

            stats["breached"], stats["avg_resp"], stats["avg_res"],

        ]],

    )

    # 二、问题分类分布

    pdf.set_font("NotoSC", size=13)

    pdf.cell(text="二、问题分类分布", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(1)

    cat_dist: dict[str, int] = {}

    for t in rows:

        cat_dist[t.category] = cat_dist.get(t.category, 0) + 1

    cat_rows = [[c, str(n), f"{round(100 * n / len(rows), 1)}%"] for c, n in sorted(cat_dist.items(), key=lambda x: -x[1])]

    _table(["问题分类", "数量", "占比"], [80, 50, 50], cat_rows or [["（本月无工单）", "-", "-"]])

    # 三、处理人工作量

    pdf.set_font("NotoSC", size=13)

    pdf.cell(text="三、处理人工作量", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(1)

    eng_dist: dict[str, int] = {}

    for t in rows:

        if t.assignee:

            name = t.assignee.name or t.assignee.username

            eng_dist[name] = eng_dist.get(name, 0) + 1

    eng_rows = [[n, str(c)] for n, c in sorted(eng_dist.items(), key=lambda x: -x[1])]

    _table(["处理人", "受理工单数"], [80, 50], eng_rows or [["（本月无指派工单）", "-"]])

    # 四、超时工单明细

    pdf.set_font("NotoSC", size=13)

    pdf.cell(text="四、SLA 超时工单明细", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(1)

    breach_rows = [

        [t.no, (t.title or "")[:22], (t.assignee.name if t.assignee else "-")[:8], "已超时"]

        for t in breached_rows

    ]

    _table(["工单编号", "问题概述", "处理人", "SLA"], [50, 70, 30, 28], breach_rows or [["（本月无超时工单）", "-", "-", "-"]])

    # 五、明细附录

    pdf.set_font("NotoSC", size=13)

    pdf.cell(text="五、本月工单明细", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(1)

    detail_rows = [

        [t.no, (t.title or "")[:24], t.status]

        for t in sorted(rows, key=lambda x: x.id)

    ]

    _table(["工单编号", "问题概述", "状态"], [50, 100, 28], detail_rows or [["（本月无工单）", "-", "-"]])

    return bytes(pdf.output())
