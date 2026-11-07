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
    "southbound": {"south_net": 25.4, "note": "", "pct": 45.0, "heat": "正常"},
    "southbound_focus": {"hk00700": {"net": 8.1}, "hk03690": {"net": -2.3}},
    "etf": {code: {"shares": 120.5, "delta": 1.2 if i % 2 == 0 else -0.8,
                    "amount": 50.0 + i, "amount_pct": 40.0 + i,
                    "amount_heat": "正常"}
            for i, (code, _) in enumerate(config.ETF_SHARE_TRACK)},
    "margin": {"balance": 15300.2, "delta": 45.6, "pct": 62.0, "heat": "正常"},
    "market_amount": {"date": "2026-11-06", "amount": 1.66e12, "pct": 53.0,
                      "heat": "正常", "median": 1.60e12, "low": 0.48e12,
                      "high": 3.94e12, "days": 737},
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
# 资金面：改为「当日成交额」，且每项都带 3 年分位
assert "A股当日总成交额" in e and "1.66 万亿" in e, "应显示当日成交额"
assert "参照：近3年" in e, "应给出近3年中位/区间作为基数"
assert e.count("3年分位") >= 12, "当日成交额/南向/9只ETF/两融都应带分位"
assert "本月（" not in e, "不应再出现月度累计成交额"
print("\n=== report smoke test OK ===")
