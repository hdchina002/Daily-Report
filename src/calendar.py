# -*- coding: utf-8 -*-
"""
calendar.py —— 财经事件日历（第八节）。

两类事件：
  A) 固定节律宏观事件（自动推算下次日期）：
       - 美国非农就业：每月第一个周五
       - 美国CPI：每月 12 日（官方多在 8~13 日，取 12 日近似）
       - 美国PPI：每月 13 日
       - 美国零售销售：每月 15 日
  B) 维护式事件（FOMC 议息、重点公司财报等，逐年更新）：见 config.EVENTS_MANUAL

对外：
  - tomorrow_events()        ：返回「明天」发生的事件列表（日报告警用）
  - month_events(y, m)       ：返回某年某月的全部事件（月报「下月事件日历」用）
  - next_month_events(base)  ：返回 base 之后最近一个月的事件
"""

import datetime
from config import EVENTS_FIXED, EVENTS_MANUAL, EVENT_IMPACT, FOMC_IMPACT


def _impact_of(title, etype):
    """返回某事件的『对 A股/港股影响』一句话。"""
    if "FOMC" in title:
        return FOMC_IMPACT
    return EVENT_IMPACT.get(title, "—")


def _first_friday(y, m):
    d = datetime.date(y, m, 1)
    # 找到第一个周五（weekday 4）
    offset = (4 - d.weekday()) % 7
    return d + datetime.timedelta(days=offset)


def _fixed_date(kind, y, m):
    if kind == "monthly_first_friday":
        return _first_friday(y, m)
    if kind.startswith("day:"):
        day = int(kind.split(":", 1)[1])
        try:
            return datetime.date(y, m, day)
        except ValueError:
            # 该月无此日（如 2 月 30 日）→ 取月末
            nxt = datetime.date(y, m, 28) + datetime.timedelta(days=4)
            return nxt - datetime.timedelta(days=nxt.day)
    return None


def _fixed_events_for_month(y, m):
    out = []
    for name, kind in EVENTS_FIXED:
        d = _fixed_date(kind, y, m)
        if d:
            out.append((d.isoformat(), name, "宏观", EVENT_IMPACT.get(name, "—")))
    return out


def all_events_for_month(y, m):
    out = _fixed_events_for_month(y, m)
    for date_str, title, etype in EVENTS_MANUAL:
        try:
            d = datetime.date.fromisoformat(date_str)
            if d.year == y and d.month == m:
                out.append((date_str, title, etype, _impact_of(title, etype)))
        except ValueError:
            continue
    out.sort(key=lambda x: x[0])
    return out


def tomorrow_events():
    t = (datetime.date.today() + datetime.timedelta(days=1))
    return _events_on_date(t)


def _events_on_date(target):
    out = []
    # 固定事件：检查 target 所在月 + 上一月（防止跨月）
    for ym in ((target.year, target.month),
               (target.year, target.month - 1) if target.month > 1
               else (target.year - 1, 12)):
        for date_str, title, etype, impact in _fixed_events_for_month(*ym):
            if date_str == target.isoformat():
                out.append((date_str, title, etype, impact))
    for date_str, title, etype in EVENTS_MANUAL:
        if date_str == target.isoformat():
            out.append((date_str, title, etype, _impact_of(title, etype)))
    out.sort(key=lambda x: x[0])
    return out


def next_month_events(base=None):
    base = base or datetime.date.today()
    # 下个月
    if base.month == 12:
        y, m = base.year + 1, 1
    else:
        y, m = base.year, base.month + 1
    return all_events_for_month(y, m)


if __name__ == "__main__":
    # 自测：非空运行不抛异常；首周五正确
    ff = _first_friday(2026, 11)
    assert ff.weekday() == 4, ff
    ev = tomorrow_events()
    me = all_events_for_month(2026, 12)
    assert any("非农" in e[1] for e in me), me
    print("calendar self-test OK; 2026-11 首周五:", ff, "; 明日事件:", ev)
