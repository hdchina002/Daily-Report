# -*- coding: utf-8 -*-
"""用合成数据验证 report.py 重构后的早/晚报渲染（含风向验证、事件影响）。"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/src")

import config
import report as R

# 给所有监控代码造一个合成报价
codes = config.all_us_hk_a_codes()
quotes = {}
for i, c in enumerate(sorted(codes)):
    quotes[c] = {
        "name": c,
        "price": 100.0 + i,
        # 让美股板块有方向差异：硬科技涨、锂矿跌，便于验证映射/验证逻辑
        "change_pct": 3.0 if "NVDA" in c or "AMD" in c else (-3.0 if "ALB" in c or "SQM" in c else 1.0),
    }
# A/H 映射板块：让 AI算力 跟随涨、锂矿/电池 跟随跌，制造"跟随"案例
for c, _, _ in config.A_H_SECTORS["AI算力"]:
    quotes[c] = {"name": c, "price": 50.0, "change_pct": 2.5}
for c, _, _ in config.A_H_SECTORS["锂矿/电池"]:
    quotes[c] = {"name": c, "price": 50.0, "change_pct": -2.5}

# 给代表ETF与医美成分股造成交额（美元），验证「资金热度」渲染
for c, amt in [("usSMH", 7.85e9), ("usXBI", 1.59e9), ("usLIT", 12.5e6),
               ("usKWEB", 2.0e9), ("usABBV", 5.0e9)]:
    if c in quotes:
        quotes[c]["amount"] = amt

ppt = {c: {"week52": 70.0, "three_year": 85.0 if "NVDA" in c else 60.0}
       for c in quotes}

capital = {
    "southbound": {"south_net": 25.4, "note": ""},
    "southbound_focus": {"hk00700": {"net": 8.1}, "hk03690": {"net": -2.3}},
    "etf": {code: {"shares": 120.5, "delta": 1.2 if i % 2 == 0 else -0.8,
                    "amount": 50.0 + i}   # 成交额（亿元），验证晚报展示
            for i, (code, _) in enumerate(config.ETF_SHARE_TRACK)},
    "margin": {"balance": 15300.2, "delta": 45.6},
}

events = [("2026-11-08", "美国CPI", "宏观", config.EVENT_IMPACT["美国CPI"]),
          ("2026-11-09", "FOMC 议息会议", "宏观", config.FOMC_IMPACT)]

wind_ref = R.morning_wind_snapshot(quotes)  # 真实函数算出的早盘风向

m = R.build_morning(quotes, ppt, ["硬科技板块均 +3.0%（超 ±3%）"], events, "2026-11-07 08:00")
e = R.build_evening(quotes, ppt, ["AI算力 中际旭创 +5.1%（超 ±5%）"], events, capital,
                    "2026-11-07 20:30", wind_ref=wind_ref)

print("========== 早报 ==========")
print(m)
print("\n========== 晚报 ==========")
print(e)

# 基本断言
assert "风向标" in m, "早报应标明风向标定位"
assert "今日中国映射" in m, "早报应有中国映射段"
assert "风向验证" in e, "晚报应有风向验证段"
assert "FOMC" in e and "美债" in e, "事件影响应渲染"
assert "跟随" in e or "背离" in e, "风向验证应有结论"
print("\n=== report smoke test OK ===")
