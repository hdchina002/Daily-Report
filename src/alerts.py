# -*- coding: utf-8 -*-
"""
alerts.py —— 阈值异动告警（第七节）。

触发条件：
  1) 任一板块单日平均涨跌幅 超 ±sector_move_pct（默认 3%）
  2) 关键个股（KEY_STOCKS）单日 超 ±stock_move_pct（默认 5%）
  3) 任一标的 3 年分位 突破 pct_hot（90%，过热）或 跌破 pct_cold（10%，过冷）

返回字符串列表，供 report 追加为「⚠ 异动提醒」区块。空列表表示无告警。
"""

from config import (SECTORS, THRESHOLDS, KEY_STOCKS)


def _sector_avg_move(sector_members, quotes):
    vals = []
    for code, _, _ in sector_members:
        q = quotes.get(code)
        if q and q.get("change_pct") is not None:
            vals.append(q["change_pct"])
    if not vals:
        return None
    return sum(vals) / len(vals)


def check_alerts(quotes, pct_data):
    """quotes: {code:{name,change_pct,...}}；pct_data: {code:{'three_year':float}}。
    返回告警字符串列表。"""
    alerts = []
    # 1) 板块单日涨跌
    for sec, members in SECTORS.items():
        avg = _sector_avg_move(members, quotes)
        if avg is None:
            continue
        if abs(avg) >= THRESHOLDS["sector_move_pct"]:
            tag = "大涨" if avg > 0 else "大跌"
            alerts.append("🔥【板块%s】%s 板块平均 %+.2f%%（阈值 ±%.0f%%）"
                          % (tag, sec, avg, THRESHOLDS["sector_move_pct"]))
    # 2) 关键个股单日涨跌
    for code in KEY_STOCKS:
        q = quotes.get(code)
        if not q or q.get("change_pct") is None:
            continue
        if abs(q["change_pct"]) >= THRESHOLDS["stock_move_pct"]:
            tag = "大涨" if q["change_pct"] > 0 else "大跌"
            alerts.append("⚡【个股%s】%s 单日 %+.2f%%（阈值 ±%.0f%%）"
                          % (tag, q.get("name", code), q["change_pct"],
                             THRESHOLDS["stock_move_pct"]))
    # 3) 3 年分位突破
    for code, p in pct_data.items():
        t = p.get("three_year")
        if t is None:
            continue
        if t >= THRESHOLDS["pct_hot"]:
            alerts.append("🌡️【过热预警】%s 3年分位 %.0f%%（突破 %.0f%%）"
                          % (quotes.get(code, {}).get("name", code),
                             t, THRESHOLDS["pct_hot"]))
        elif t <= THRESHOLDS["pct_cold"]:
            alerts.append("🧊【过冷预警】%s 3年分位 %.0f%%（跌破 %.0f%%）"
                          % (quotes.get(code, {}).get("name", code),
                             t, THRESHOLDS["pct_cold"]))
    return alerts


if __name__ == "__main__":
    q = {"usNVDA": {"name": "英伟达", "change_pct": 6.1},
         "usBABA": {"name": "阿里巴巴", "change_pct": -2.0}}
    pct = {"usNVDA": {"three_year": 92.0}, "usBABA": {"three_year": 8.0}}
    a = check_alerts(q, pct)
    assert any("英伟达" in x for x in a), a
    assert any("过热" in x for x in a), a
    assert any("过冷" in x for x in a), a
    print("alerts self-test OK:", a)
