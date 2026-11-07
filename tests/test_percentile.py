# -*- coding: utf-8 -*-
"""集成冒烟测试：用合成数据验证 report / alerts / calendar / percentile 串联不崩。"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import config
import report as report_mod
import alerts as alerts_mod
import calendar as calendar_mod
import percentile


def _fake_quotes():
    q = {}
    for sec, members in config.SECTORS.items():
        for i, (code, name, _) in enumerate(members):
            q[code] = {"name": name, "price": 100.0 + i * 5, "change_pct": -2.0 + i}
    for code, name in config.US_INDICES + config.A_INDICES + config.HK_INDICES:
        q[code] = {"name": name, "price": 3000.0, "change_pct": 0.5}
    return q


def _fake_ppt():
    ppt = {}
    for sec, members in config.SECTORS.items():
        for i, (code, name, _) in enumerate(members):
            ppt[code] = {"week52": 50.0 + i * 5, "three_year": 40.0 + i * 8}
    return ppt


def _fake_capital():
    return {
        "southbound": {"south_net": 12.34, "north_net": None, "note": "", "date": "2026-11-06"},
        "etf": {code: {"name": n, "shares": 120.5, "chg_pct": 0.8, "delta": 1.2}
                for code, n in config.ETF_SHARE_TRACK},
        "margin": {"balance": 15000.0, "delta": 25.0, "note": ""},
        "southbound_focus": {c: {"name": n, "net": 3.1} for c, n in config.SOUTHBOUND_FOCUS},
    }


def main():
    quotes = _fake_quotes()
    ppt = _fake_ppt()
    capital = _fake_capital()
    al = alerts_mod.check_alerts(quotes, ppt)
    ev = calendar_mod.tomorrow_events()

    morn = report_mod.build_morning(quotes, ppt, al, ev, "2026-11-07 08:00")
    eve = report_mod.build_evening(quotes, ppt, al, ev, capital, "2026-11-07 20:30")

    assert "早报" in morn and "风向标" in morn and "今日中国映射" in morn, "morning render failed"
    assert "晚报" in eve and "南向" in eve and "ETF份额" in eve and "风向验证" in eve, "evening render failed"
    # percentile sanity
    assert percentile.pct_of_price(10.0, [1, 10]) == 100.0
    print("integration smoke OK")
    print("---- morning (head) ----")
    print("\n".join(morn.splitlines()[:14]))
    print("---- evening (head) ----")
    print("\n".join(eve.splitlines()[:20]))


if __name__ == "__main__":
    main()
