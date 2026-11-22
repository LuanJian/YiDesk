"""工作日历 SLA 计算。

work_hours.enabled=false（默认）→ 7x24 自然时间，行为与 v1.1 一致；

enabled=true → SLA 时限按工作时间推进（跳过非工作日与下班时段）。

workdays 约定：0=周一 … 6=周日。

"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from app.core.config import get_config

MAX_DAYS_PROBE = 3660  # 防御性上限：最多推进约 10 年，避免配置错误导致死循环

def _parse_hhmm(s: str) -> time:

    hh, mm = (s or "09:00").split(":")[:2]

    return time(int(hh), int(mm))

def work_bounds(day: datetime) -> tuple[datetime, datetime]:

    cfg = get_config().sla.work_hours

    start = _parse_hhmm(cfg.get("start", "09:00"))

    end = _parse_hhmm(cfg.get("end", "18:00"))

    base = day.date()

    return (

        datetime.combine(base, start),

        datetime.combine(base, end),

    )

def _config_dates(key: str) -> set:

    """读取 holidays / extra_workdays 配置为 date 集合（格式 YYYY-MM-DD，非法项忽略）。"""

    from datetime import date as _date

    out = set()

    for s in get_config().sla.work_hours.get(key, []) or []:

        try:

            out.add(_date.fromisoformat(s))

        except (ValueError, TypeError):

            continue

    return out

def is_workday(day: datetime) -> bool:

    cfg = get_config().sla.work_hours

    d = day.date()

    # 调休上班日优先（周末也可能是工作日）

    if d in _config_dates("extra_workdays"):

        return True

    if d in _config_dates("holidays"):

        return False

    workdays = [int(x) for x in cfg.get("workdays", [0, 1, 2, 3, 4])]

    return day.weekday() in workdays

def add_business_minutes(start: datetime, minutes: int) -> datetime:

    """从 start 起推进 minutes 分钟，仅累计工作日历内的时间。"""

    cfg = get_config().sla.work_hours

    if not cfg.get("enabled"):

        return start + timedelta(minutes=minutes)

    remaining = minutes

    cur = start

    for _ in range(MAX_DAYS_PROBE):

        if not is_workday(cur):

            cur = _next_day_start(cur)

            continue

        day_start, day_end = work_bounds(cur)

        if cur < day_start:

            cur = day_start

        if cur >= day_end:

            cur = _next_day_start(cur)

            continue

        available = int((day_end - cur).total_seconds() // 60)

        if remaining <= available:

            return cur + timedelta(minutes=remaining)

        remaining -= available

        cur = _next_day_start(cur)

    return cur  # 配置极端异常时兜底返回

def _next_day_start(day: datetime) -> datetime:

    nxt = day.date() + timedelta(days=1)

    day_start, _ = work_bounds(datetime.combine(nxt, time(0, 0)))

    return day_start

def business_minutes_between(a: datetime, b: datetime) -> int:

    """a→b 之间的工作分钟数（用于按日历统计，7x24 时退化为自然时间差）。"""

    cfg = get_config().sla.work_hours

    if not cfg.get("enabled"):

        return int((b - a).total_seconds() // 60)

    if b <= a:

        return 0

    total = 0

    cur = a

    for _ in range(MAX_DAYS_PROBE):

        if cur >= b:

            break

        if not is_workday(cur):

            cur = _next_day_start(cur)

            continue

        day_start, day_end = work_bounds(cur)

        seg_start = max(cur, day_start)

        seg_end = min(b, day_end)

        if seg_end > seg_start:

            total += int((seg_end - seg_start).total_seconds() // 60)

        cur = _next_day_start(cur)

    return total
