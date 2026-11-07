# -*- coding: utf-8 -*-
"""
percentile.py —— 历史价格百分位（本项目的「重点新增」核心逻辑）。

定义（与需求一致）：取历史区间 [low, high] 的全部交易日收盘价，
    分位 = (当前价 - low) / (high - low) × 100
  - 现价 = low  → 0%（历史最冷/最低）
  - 现价 = high → 100%（历史最热/最高）
  - 例：区间 1.0~10.0，现价 10.0 → 100% 分位

提供：
  - pct_of_price(price, closes)        ：通用分位
  - week52_percentile(price, closes)   ：近 252 交易日分位（零额外请求，从已缓存历史取）
  - three_year_percentile(price, ...)  ：近 N 年分位（从已缓存历史取）
  - sector_heat(member_pcts)           ：板块冷热（成分股分位均值 + 过热/过冷标签）
"""

from config import PERCENTILE_WINDOW_YEARS, WEEK52_TRADING_DAYS


def _to_floats(closes):
    out = []
    for v in closes:
        try:
            f = float(v)
            if f == f and f > 0:   # 过滤 NaN 与非正
                out.append(f)
        except (TypeError, ValueError):
            continue
    return out


def pct_of_price(price, closes):
    """(price - min) / (max - min) × 100，clamp 到 [0,100]。
    历史为空或 max==min 时返回 None（无法计算）。"""
    closes = _to_floats(closes)
    if not closes or price is None:
        return None
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None
    lo, hi = min(closes), max(closes)
    if hi <= lo:
        return None
    raw = (p - lo) / (hi - lo) * 100.0
    # 当前价可能略超历史极值（如当日创出新高/新低，缓存尚未包含当日收盘）
    # 这里按「是否创新高/新低」做信息增强，但分位数字仍 clamp 到 [0,100]。
    return max(0.0, min(100.0, raw))


def window_closes(closes, n_days):
    """取最近 n_days 个收盘价（用于 52 周窗口）。closes 已按日期升序。"""
    if not closes:
        return []
    return closes[-n_days:]


def week52_percentile(price, closes):
    return pct_of_price(price, window_closes(closes, WEEK52_TRADING_DAYS))


def three_year_percentile(price, closes):
    # 3 年 ≈ 3×252 = 756 个交易日；PERCENTILE_WINDOW_YEARS 可改成 1。
    n = int(PERCENTILE_WINDOW_YEARS * 252)
    return pct_of_price(price, window_closes(closes, n))


def range_text(closes):
    """返回 (low, high) 用于展示，如 '1.0~10.0'。"""
    closes = _to_floats(closes)
    if not closes:
        return None, None
    return min(closes), max(closes)


def sector_heat(member_pcts):
    """member_pcts: 成分股分位列表（含 None 会被忽略）。
    返回 (avg_pct_or_None, tag)。tag ∈ {'过热','过冷','', 且 None 时无标签}。"""
    vals = [p for p in member_pcts if p is not None]
    if not vals:
        return None, ""
    avg = sum(vals) / len(vals)
    tag = ""
    if avg >= 80.0:
        tag = "过热🔥"
    elif avg <= 20.0:
        tag = "过冷❄️"
    return avg, tag


def heat_tag(avg_pct):
    if avg_pct is None:
        return ""
    if avg_pct >= 80.0:
        return "过热🔥"
    if avg_pct <= 20.0:
        return "过冷❄️"
    return ""


# ───────────── 资金面分位（排名口径，与上面的「价格区间位置」不同） ─────────────
# 成交额 / 净买入 / 两融余额这类数据常有极端尖峰（例如 2024-10 的天量），
# 用 (v-min)/(max-min) 会把日常值压得很低，无法回答「今天算高还是低」。
# 故资金面统一用「排名百分位」：今日值高于近 3 年多少比例的交易日。
def capital_heat(pct):
    """资金面高低标签（5 档），比价格分位只分过热/正常/过冷更细腻。"""
    if pct is None:
        return ""
    if pct >= 90.0:
        return "极高🔥"
    if pct >= 70.0:
        return "偏高"
    if pct >= 30.0:
        return "正常"
    if pct >= 10.0:
        return "偏低"
    return "极低❄️"


def capital_rank_stats(value, series):
    """把当前值放进近 3 年日频序列，一次算出分位与「基数」。

    返回 {'pct','median','low','high','n','heat'}；样本不足 30 个返回 {}。
    - pct = 排名百分位（严格小于 value 的样本占比 ×100），允许负值（南向净买入可正可负）
    - median / low / high 用于给用户一个直观的「历史基数」
    """
    vals = []
    for v in series or []:
        try:
            f = float(v)
            if f == f:                     # 过滤 NaN，但保留负数
                vals.append(f)
        except (TypeError, ValueError):
            continue
    if value is None or len(vals) < 30:
        return {}
    try:
        x = float(value)
    except (TypeError, ValueError):
        return {}
    s = sorted(vals)
    n = len(s)
    pct = round(sum(1 for v in s if v < x) / n * 100.0, 1)
    return {"pct": pct, "median": s[n // 2], "low": s[0], "high": s[-1],
            "n": n, "heat": capital_heat(pct)}


if __name__ == "__main__":
    # 自测：覆盖需求文档里的示例与边界
    closes = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    assert pct_of_price(10.0, closes) == 100.0, "最高应 100%"
    assert pct_of_price(1.0, closes) == 0.0, "最低应 0%"
    assert abs(pct_of_price(5.5, closes) - 50.0) < 1e-9, "中位应 50%"
    # 区间 1~10，现价 10 → 100%（需求示例）
    assert pct_of_price(10.0, [1.0, 10.0]) == 100.0
    # 窗口
    assert week52_percentile(10.0, closes) == 100.0
    # 板块冷热
    avg, tag = sector_heat([90.0, 85.0, 78.0])
    assert tag == "过热🔥", tag
    avg, tag = sector_heat([10.0, 5.0, 18.0])
    assert tag == "过冷❄️", tag
    avg, tag = sector_heat([30.0, 50.0])
    assert tag == "", tag
    # 空/异常
    assert pct_of_price(5.0, []) is None
    assert pct_of_price(None, closes) is None
    assert sector_heat([None, None])[0] is None
    # 资金面排名分位：允许负值、抗极端值、样本不足返回 {}
    s100 = [float(i) for i in range(-50, 50)]          # -50 ~ 49，共 100 个
    st = capital_rank_stats(40.0, s100)
    assert st["pct"] == 90.0 and st["low"] == -50.0 and st["n"] == 100, st
    assert capital_rank_stats(-40.0, s100)["pct"] == 10.0   # 负值也成立
    assert capital_rank_stats(5.0, []) == {}
    assert capital_rank_stats(5.0, [1.0, 2.0]) == {}
    assert capital_heat(None) == "" and capital_heat(95.0) == "极高🔥"
    print("percentile self-test OK")
