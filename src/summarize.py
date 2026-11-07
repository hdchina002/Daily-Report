# -*- coding: utf-8 -*-
"""
summarize.py —— 月报 / 半年报 / 年报 汇总（第五节）。

数据来源：
  - data/daily_YYYY.json：每日快照（main 写入，随仓库提交）
  - data/history.json   ：3 年历史收盘价缓存（用于分位轨迹）

日快照 schema（main 写入）：
  {"date","mode","quotes":{code:{"name","price","change_pct"}},
   "pct":{code:{"week52","three_year"}}, "sectors":{sec:{"avg_move"}},
   "capital":{...}}   # 仅 evening
"""

import os
import json
import datetime

from config import SECTORS as _SECTORS
from percentile import three_year_percentile, week52_percentile
from fetcher import load_history
from calendar import next_month_events


def load_year_snapshots(year):
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "daily_%d.json" % year)
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _filter(snaps, y, m):
    prefix = "%04d-%02d" % (y, m)
    return [s for s in snaps if (s.get("date") or "").startswith(prefix)]


def _avg(vals):
    vals = [v for v in vals if v is not None]
    return (sum(vals) / len(vals)) if vals else None


def _pct_at_date(hist, code, date_str):
    node = hist.get(code)
    if not node:
        return None
    dates, closes = node["dates"], node["closes"]
    upto = [(d, c) for d, c in zip(dates, closes) if d <= date_str]
    if not upto:
        return None
    price = upto[-1][1]
    closes_upto = [c for _, c in upto]
    return three_year_percentile(price, closes_upto)


def monthly_report(year, month):
    snaps = _filter(load_year_snapshots(year), year, month)
    if not snaps:
        return "# 月报 %04d-%02d\n\n本月无数据快照（可能尚未运行或刚初始化）。" % (year, month)
    hist = load_history()

    # 板块月度平均涨跌
    sec_avgs = {}
    for sec, members in _SECTORS.items():
        moves = [s["sectors"].get(sec, {}).get("avg_move")
                 for s in snaps if s.get("sectors", {}).get(sec)]
        sec_avgs[sec] = _avg(moves)

    # 个股月度平均涨跌
    stock_avgs = {}
    for s in snaps:
        for code, q in (s.get("quotes") or {}).items():
            cp = q.get("change_pct")
            if cp is not None:
                stock_avgs.setdefault(code, []).append(cp)
    stock_avg = {c: _avg(v) for c, v in stock_avgs.items()}

    # 分位变化（月内：月末 vs 月初）
    first_date = min(s["date"] for s in snaps)
    last_date = max(s["date"] for s in snaps)
    pct_start, pct_end = {}, {}
    for sec, members in _SECTORS.items():
        ps = _avg([_pct_at_date(hist, c, first_date) for c, _, _ in members])
        pe = _avg([_pct_at_date(hist, c, last_date) for c, _, _ in members])
        pct_start[sec], pct_end[sec] = ps, pe
    pct_changes = {sec: (pct_end[sec] - pct_start[sec])
                   for sec in _SECTORS if pct_start[sec] is not None and pct_end[sec] is not None}

    # 资金面（仅 evening 有 capital）
    sb_list, etf_delta, mg_first, mg_last = [], {}, None, None
    for s in snaps:
        cap = s.get("capital") or {}
        sb = cap.get("southbound") or {}
        if sb.get("south_net") is not None:
            sb_list.append(sb["south_net"])
        for code, e in (cap.get("etf") or {}).items():
            if e.get("delta") is not None:
                etf_delta[code] = etf_delta.get(code, 0.0) + e["delta"]
        mg = cap.get("margin") or {}
        if mg.get("balance") is not None:
            mg_first = mg["balance"] if mg_first is None else mg_first
            mg_last = mg["balance"]

    # 组装
    lines = ["# 📅 月度报告 %04d-%02d" % (year, month), ""]
    # 板块涨跌排名
    ranked = sorted([(v, k) for k, v in sec_avgs.items() if v is not None],
                    reverse=True)
    lines.append("**板块月度平均涨跌排名**")
    for v, k in ranked:
        lines.append("- %s：%s" % (k, ("+%.2f%%" if v >= 0 else "%.2f%%") % v))
    if ranked:
        best, worst = ranked[0], ranked[-1]
        lines.append("- 最佳板块：**%s %s**；最差板块：**%s %s**"
                     % (best[1], ("+%.2f%%" % best[0]), worst[1], ("%.2f%%" % worst[0])))
    lines.append("")

    # 龙头个股表现排名
    sranked = sorted([(v, k) for k, v in stock_avg.items() if v is not None], reverse=True)
    lines.append("**龙头个股月度表现（均值）Top/Bottom**")
    for v, k in sranked[:5]:
        lines.append("- 🔝 %s %s" % (k, ("+%.2f%%" % v)))
    for v, k in sranked[-3:]:
        lines.append("- 🔻 %s %s" % (k, ("%.2f%%" % v)))
    lines.append("")

    # 分位变化榜
    pchg = sorted(pct_changes.items(), key=lambda x: x[1], reverse=True)
    lines.append("**分位变化榜（月末 vs 月初，3年分位）**")
    for sec, d in pchg:
        lines.append("- %s：%s 分位（%s%.0f）"
                     % (sec, ("升温🔥" if d >= 0 else "降温❄️"),
                        "+" if d >= 0 else "", d))
    lines.append("")

    # 资金方向总结
    lines.append("**板块月度资金流向总结**")
    if sb_list:
        lines.append("- 南向（港股通）月累计净买入：%s 亿元"
                     % ("%.2f" % sum(sb_list)))
    else:
        lines.append("- 南向资金：本月无数据")
    if etf_delta:
        lines.append("- 行业ETF 月净申购（份额变动合计）：")
        for code, d in sorted(etf_delta.items(), key=lambda x: x[1], reverse=True):
            lines.append("  - %s：%s 亿份" % (code, ("+%.2f" % d)))
    if mg_first is not None and mg_last is not None:
        lines.append("- 两融余额：%s → %s 亿元（月变动 %s 亿）"
                     % ("%.2f" % mg_first, "%.2f" % mg_last,
                        ("+%.2f" % (mg_last - mg_first))))
    lines.append("")

    lines.append("**📅 下月财经事件日历**")
    for d, title, etype in next_month_events(datetime.date(year, month, 1)):
        lines.append("- %s %s（%s）" % (d, title, etype))
    lines.append("")
    return "\n".join(lines)


def period_report(kind, year, start_month, end_month):
    """kind: 'half' / 'year'；统计 [year-start_month, year-end_month]。"""
    snaps = []
    for m in range(start_month, end_month + 1):
        snaps.extend(_filter(load_year_snapshots(year), year, m))
    label = "半年度" if kind == "half" else "年度"
    if not snaps:
        return "# %s报告 %d\n\n本期无数据快照。" % (label, year)
    hist = load_history()
    title = label

    first_date = min(s["date"] for s in snaps)
    last_date = max(s["date"] for s in snaps)

    # 累计涨跌（首快照 vs 末快照的个股/板块）
    def snap_pct_map(date_str):
        for s in snaps:
            if s["date"] == date_str:
                return s
        return None
    s0, s1 = snap_pct_map(first_date), snap_pct_map(last_date)
    lines = ["# 📈 %s报告 %d（%02d-%02d 至 %02d-%02d）"
             % (title, year, start_month, int(first_date[5:7]),
                end_month, int(last_date[5:7])), ""]

    lines.append("**各板块累计涨跌对比**")
    for sec in _SECTORS:
        a0 = (s0.get("sectors", {}).get(sec, {}).get("avg_move") if s0 else None)
        a1 = (s1.get("sectors", {}).get(sec, {}).get("avg_move") if s1 else None)
        lines.append("- %s：期初 %s → 期末 %s"
                     % (sec,
                        ("%.2f%%" % a0) if a0 is not None else "—",
                        ("%.2f%%" % a1) if a1 is not None else "—"))
    lines.append("")

    # 分位轨迹（冷→热）
    lines.append("**各板块历史分位变化轨迹（3年分位）**")
    for sec, members in _SECTORS.items():
        ps = _avg([_pct_at_date(hist, c, first_date) for c, _, _ in members])
        pe = _avg([_pct_at_date(hist, c, last_date) for c, _, _ in members])
        if ps is not None and pe is not None:
            moved = "升温🔥" if pe > ps else ("降温❄️" if pe < ps else "持平")
            lines.append("- %s：%s%% → %s%%（%s）"
                         % (sec, "%.0f" % ps, "%.0f" % pe, moved))
        else:
            lines.append("- %s：分位数据不足" % sec)
    lines.append("")

    lines.append("**资金方向总结判断**")
    sb = [s.get("capital", {}).get("southbound", {}).get("south_net")
          for s in snaps if (s.get("capital") or {}).get("southbound", {}).get("south_net") is not None]
    if sb:
        lines.append("- 南向（港股通）区间累计净买入：%s 亿元（%s方向）"
                     % ("%.2f" % sum(sb), "净流入" if sum(sb) >= 0 else "净流出"))
    lines.append("- 详见每日晚报的资金面字段（南向/ETF份额/两融）。")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    # 自测：空数据时优雅返回，不抛异常
    t = monthly_report(2000, 1)
    assert "月报" in t and "无数据" in t, t
    p = period_report("half", 2000, 1, 6)
    assert "半年度" in p and "无数据" in p, p
    print("summarize self-test OK")
