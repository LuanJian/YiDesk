"""数据看板 API（v2.3，staff）：日期区间 + 日/月/年粒度聚合 + CSV 导出。"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.deps import require_admin, require_staff
from app.models.database import get_db
from app.models.user import User
from app.services import analytics_service

router = APIRouter()

GRANULARITIES = ("day", "week", "month", "year")


def _range_params(
    start: str | None = Query(default=None, description="YYYY-MM-DD，默认近 30 天"),
    end: str | None = Query(default=None, description="YYYY-MM-DD，含当日"),
    granularity: str = Query(default="day"),
    category: str | None = None,
    engineer_id: int | None = None,
    department: str | None = None,
):
    if granularity not in GRANULARITIES:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="granularity 必须是 day/month/year")
    return {
        "start": analytics_service._parse_day(start, 30, "start"),
        "end": analytics_service._parse_day(end, 30, "end"),
        "granularity": granularity,
        "category": category or None,
        "engineer_id": engineer_id,
        "department": department or None,
    }


@router.get("/dashboard")
def analytics_dashboard(
    params: dict = Depends(_range_params),
    db: Session = Depends(get_db),
    user: User = Depends(require_staff),
):
    return analytics_service.dashboard(db, user=user, **params)


@router.get("/export")
def analytics_export(
    sheet: str = Query(default="engineers"),
    params: dict = Depends(_range_params),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """导出 CSV（UTF-8 BOM，v2.11 起仅管理员）：sheet=engineers 处理人明细 | hot_issues 高频问题 | submitters 提单方。"""
    data = analytics_service.dashboard(db, user=user, **params)
    buf = io.StringIO()
    writer = csv.writer(buf)

    if sheet == "hot_issues":
        writer.writerow(["类型", "名称", "数量", "占总数百分比"])
        for c in data["hot_issues"]["categories"]:
            writer.writerow(["分类", c["name"], c["value"], f"{c['pct']}%"])
        for k in data["hot_issues"]["keywords"]:
            writer.writerow(["关键词", k["keyword"], k["count"], f"{k['pct']}%"])
        filename = "高频问题"
    elif sheet == "submitters":
        writer.writerow(["提单员工", "部门", "工单量"])
        for e in data["submitters"]["employees"]:
            writer.writerow([e["name"], e["department"], e["count"]])
        writer.writerow([])
        writer.writerow(["部门", "工单量", "占比"])
        for d in data["submitters"]["departments"]:
            writer.writerow([d["department"], d["count"], f"{d['pct']}%"])
        filename = "提单统计"
    else:
        sheet = "engineers"
        writer.writerow([
            "处理人", "受理量", "解决量", "当前未结",
            "平均响应(分)", "平均解决(分)", "响应达标率", "解决达标率", "平均星级", "评价数", "重开率",
        ])
        for e in data["engineers"]:
            writer.writerow([
                e["name"], e["assigned"], e["resolved"], e["open"],
                e["avg_response_minutes"] or "-", e["avg_resolution_minutes"] or "-",
                f"{e['response_sla_rate']}%" if e["response_sla_rate"] is not None else "-",
                f"{e['resolution_sla_rate']}%" if e["resolution_sla_rate"] is not None else "-",
                e["avg_stars"] or "-", e["rating_count"],
                f"{e['reopen_rate']}%" if e["reopen_rate"] is not None else "-",
            ])
        filename = "处理人统计"

    out = io.BytesIO()
    out.write(b"\xef\xbb\xbf")
    out.write(buf.getvalue().encode("utf-8"))
    out.seek(0)
    return StreamingResponse(
        out,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=analytics-{sheet}.csv"},
    )
