# -*- coding: utf-8 -*-
"""
report.py —— 早报 / 晚报 文本生成（markdown，适配 Server酱 / WxPusher）。

设计定位（按用户需求重构）：
  · 美股 = 风向标（只看方向/冷热/政策，不交易）
  · A股/港股 = 实盘（真正的投资标的）
  · 早报加「今日中国映射」、晚报加「风向验证」，把两者打通。

数字来自 main 传入的 quotes / pct_data / capital，本模块只排版。
涨跌颜色约定：涨=红(+)、跌=绿(-)（A股习惯），用 +/- 与 ▲▼ 标记。
"""

from config import (SECTORS, US_INDICES, HK_INDICES, A_INDICES,
                    A_H_SECTORS, HEAT_HOT, HEAT_COLD,
                    CHINA_MAPPING, WIND_PAIRS, SECTOR_ETF)

# code → 中文名（从 SECTORS 提取，早报资金热度用友好名而非英文/代码）
_CODE_NAME = {}
for _sec, _members in SECTORS.items():
    for _c, _n, _ in _members:
        _CODE_NAME[_c] = _n


def _f(v, nd=2):
    try:
        return ("%.*f" % (nd, float(v)))
    except (TypeError, ValueError):
        return "—"


def _pct(v):
    if v is None:
        return "—"
    return ("+%.2f%%" if v >= 0 else "%.2f%%") % v


def _pct_block(week52, three_year):
    w = ("%.0f%%" % week52) if week52 is not None else "—"
    t = ("%.0f%%" % three_year) if three_year is not None else "—"
    return "｜52周分位 %s｜3年分位 %s" % (w, t)


# ───────────────────────────── 板块聚合 helpers ─────────────────────────────
def _sector_avg(quotes, members):
    moves = [quotes.get(c, {}).get("change_pct")
             for c, _, _ in members if quotes.get(c, {}).get("change_pct") is not None]
    return (sum(moves) / len(moves)) if moves else None


def _sector_heat(pct_data, members):
    vals = [pct_data.get(c, {}).get("three_year")
            for c, _, _ in members if pct_data.get(c, {}).get("three_year") is not None]
    return (sum(vals) / len(vals)) if vals else None


def _top_mover(quotes, members):
    best = None
    for c, name, _ in members:
        q = quotes.get(c, {})
        if q.get("change_pct") is not None:
            if best is None or q["change_pct"] > best[1]:
                best = (name, q["change_pct"])
    return best


def _heat_tag(avg):
    if avg is None:
        return ""
    if avg >= HEAT_HOT:
        return " 🔥过热"
    if avg <= HEAT_COLD:
        return " ❄️过冷"
    return ""


def index_block(title, indices, quotes):
    lines = ["**%s**" % title]
    for code, name in indices:
        q = quotes.get(code)
        if not q:
            lines.append("- %s —" % name)
            continue
        arrow = "▲" if (q.get("change_pct") or 0) >= 0 else "▼"
        lines.append("- %s %s (%s%s)" % (name, _f(q.get("price"), 2),
                                          arrow, _pct(q.get("change_pct"))))
    return "\n".join(lines)


def _risk_appetite(quotes):
    ms = [quotes.get(c, {}).get("change_pct")
          for c, _ in US_INDICES if quotes.get(c, {}).get("change_pct") is not None]
    if not ms:
        return "中性（美股数据缺失）"
    up = sum(1 for m in ms if m > 0)
    dn = sum(1 for m in ms if m < 0)
    avg = sum(ms) / len(ms)
    if up == len(ms):
        return "Risk-On（美股普涨，风险偏好升温）"
    if dn == len(ms):
        return "Risk-Off（美股普跌，避险情绪升温）"
    return "中性分化（%s）" % ("偏强" if avg > 0 else "偏弱")


def _china_hint(sec, avg_move, heat):
    """把某美股板块的风向，翻译成 A股/港股方向提示。"""
    base = CHINA_MAPPING.get(sec, "")
    if not base:
        return None
    if avg_move is None:
        return "→ %s（美股数据缺失，仅列方向）" % base
    if avg_move > 0 and heat is not None and heat >= HEAT_HOT:
        tone = "趋势强但已处历史高位，关注业绩兑现、防追高"
    elif avg_move > 0 and heat is not None and heat <= HEAT_COLD:
        tone = "低位启动，估值修复空间较大，可重点跟踪"
    elif avg_move < 0 and heat is not None and heat >= HEAT_HOT:
        tone = "高位回落，注意止盈/回避"
    elif avg_move < 0 and heat is not None and heat <= HEAT_COLD:
        tone = "仍处过冷区间，观望等待企稳"
    else:
        tone = "中性，跟随大盘"
    return "→ %s：%s" % (base, tone)


def _us_amount(v):
    """美股成交额（美元）友好显示。"""
    if v is None:
        return "—"
    if v >= 1e9:
        return "$%.2fB" % (v / 1e9)
    if v >= 1e6:
        return "$%.1fM" % (v / 1e6)
    return "$%.0f" % v


def _sector_etf_amount(quotes, sec):
    """返回 (ETF名称, 成交额美元) 用于资金热度；无代表ETF则合计成分股成交额。"""
    etf_code = SECTOR_ETF.get(sec)
    if etf_code and quotes.get(etf_code, {}).get("amount") is not None:
        return _CODE_NAME.get(etf_code, etf_code), quotes[etf_code]["amount"]
    total = 0.0
    has = False
    for c, _, _ in SECTORS.get(sec, []):
        a = quotes.get(c, {}).get("amount")
        if a is not None:
            total += a
            has = True
    return (sec + "(成分股合计)", total) if has else (sec, None)


# ───────────────────────────── 早报（风向标） ─────────────────────────────
def build_morning(quotes, pct_data, alerts, events, asof):
    P = []
    P.append("# 🌍 早报 · 隔夜美股（风向标）")
    P.append("北京时间 %s ｜ 美股已收盘，仅供判断全球风向，非交易建议" % asof)
    P.append("")

    # 一、情绪温度
    P.append("## 一、美股情绪温度")
    P.append(index_block("三大指数", US_INDICES, quotes))
    P.append("- 风险偏好：%s" % _risk_appetite(quotes))
    P.append("")

    # 二、板块冷热 + 资金热度（ETF成交额 = 钱往哪去）
    etf_amts = {}
    for sec in SECTORS:
        etf_amts[sec] = _sector_etf_amount(quotes, sec)
    hot_sec = None
    valid = [s for s in SECTORS if etf_amts[s][1] is not None]
    if valid:
        hot_sec = max(valid, key=lambda s: etf_amts[s][1])
    P.append("## 二、五大板块冷热 + 资金热度（🔥≥%.0f过热/❄️≤%.0f过冷；资金=行业ETF成交额）"
             % (HEAT_HOT, HEAT_COLD))
    if hot_sec:
        nm, amt = etf_amts[hot_sec]
        P.append("- 🔥 资金最活跃：**%s**（%s 成交额 %s，五大板块最高）"
                 % (hot_sec, nm, _us_amount(amt)))
    for sec, members in SECTORS.items():
        mv = _sector_avg(quotes, members)
        h = _sector_heat(pct_data, members)
        top = _top_mover(quotes, members)
        nm, amt = etf_amts[sec]
        line = "- %s：板块均 %s ｜ 分位 %s%s ｜ 资金 %s" % (
            sec, _pct(mv), (_f(h, 0) if h is not None else "—"), _heat_tag(h),
            _us_amount(amt))
        if top:
            line += " ｜ 龙头%s %s" % (top[0], _pct(top[1]))
        P.append(line)
    P.append("")

    # 三、今日中国映射（核心增量）
    P.append("## 三、🧭 今日中国映射（仅提示方向，非荐股）")
    for sec, members in SECTORS.items():
        hint = _china_hint(sec, _sector_avg(quotes, members),
                           _sector_heat(pct_data, members))
        if hint:
            P.append("- " + hint)
    P.append("")

    # 四/五、异动 + 明日事件
    sec_n = 4
    if alerts:
        P.append("## 四、⚠ 异动提醒")
        for a in alerts:
            P.append("- " + a)
        P.append("")
        sec_n = 5
    if events:
        P.append("## %s、📅 明日财经事件（含对A股影响）" % sec_n)
        for d, title, etype, impact in events:
            P.append("- %s %s（%s）" % (d, title, etype))
            if impact and impact != "—":
                P.append("  ↳ %s" % impact)
        P.append("")

    P.append("> 数据：腾讯行情 qt.gtimg.cn（美股收盘）。红涨绿跌。")
    return "\n".join(P)


# ───────────────────────────── 晚报（实盘） ─────────────────────────────
def build_evening(quotes, pct_data, alerts, events, capital, asof, wind_ref=None):
    P = []
    P.append("# 📈 晚报 · A股/港股收盘 + 资金面")
    P.append("北京时间 %s" % asof)
    P.append("")

    # 一、指数收盘
    P.append("## 一、指数收盘")
    P.append(index_block("A股", A_INDICES, quotes))
    P.append(index_block("港股", HK_INDICES, quotes))
    P.append("")

    # 二、映射板块表现
    P.append("## 二、映射板块表现（对应早盘美股风向）")
    for sec, members in A_H_SECTORS.items():
        mv = _sector_avg(quotes, members)
        h = _sector_heat(pct_data, members)
        top = _top_mover(quotes, members)
        line = "- %s：板块均 %s ｜ 分位 %s%s" % (
            sec, _pct(mv), (_f(h, 0) if h is not None else "—"), _heat_tag(h))
        if top:
            line += " ｜ 领涨%s %s" % (top[0], _pct(top[1]))
        P.append(line)
    P.append("")

    # 三、资金面（硬数据）
    P.append("## 三、资金面（硬数据）")
    sb = (capital or {}).get("southbound") or {}
    if sb.get("south_net") is not None:
        P.append("- 南向（港股通）净买入：**%s 亿元**" % _f(sb["south_net"], 2))
    else:
        P.append("- 南向（港股通）净买入：—（%s）" % sb.get("note", "接口暂不可用"))
    focus = (capital or {}).get("southbound_focus") or {}
    for code, name in [("hk00700", "腾讯控股"), ("hk03690", "美团")]:
        f = focus.get(code)
        net = f.get("net") if f else None
        P.append("  - %s 南向净买卖：%s" % (
            name, (_f(net, 2) + " 亿元") if net is not None else "—"))
    P.append("")

    P.append("**行业ETF份额变化 + 成交额**（净申购=资金流入；成交额大=交易热）")
    etf = (capital or {}).get("etf") or {}
    for code, name in _etf_list():
        e = etf.get(code) or {}
        sh = _f(e["shares"], 2) if e.get("shares") is not None else None
        d = e.get("delta")
        dstr = ("（净申购 +%s 亿份）" % _f(d, 2)) if d is not None and d > 0 else \
              ("（净赎回 %s 亿份）" % _f(d, 2)) if d is not None and d < 0 else ""
        astr = ("｜ 成交额 %s亿" % _f(e["amount"], 1)) if e.get("amount") is not None else ""
        bits = []
        if sh is not None:
            bits.append("%s 亿份" % sh)
        if dstr:
            bits.append(dstr)
        if astr:
            bits.append(astr)
        P.append("- %s %s" % (name, " ".join(bits) if bits else "—"))
    P.append("")

    mg = (capital or {}).get("margin") or {}
    if mg.get("balance") is not None:
        delta = mg.get("delta")
        dstr = ("（较上日 %s%s 亿）" % ("+" if (delta or 0) >= 0 else "",
                                        _f(delta, 2))) if delta is not None else ""
        P.append("**融资融券余额**：%s 亿元%s" % (_f(mg["balance"], 2), dstr))
    else:
        P.append("**融资融券余额**：—（%s）" % mg.get("note", "接口暂不可用"))
    P.append("")

    # 四、风向验证（早盘美股 → 今日A股）
    P.append("## 四、🧭 风向验证（早盘美股 → 今日A股）")
    if wind_ref:
        for us_sec, ah_sec in WIND_PAIRS:
            us_mv = wind_ref.get(us_sec)
            ah_mv = _sector_avg(quotes, A_H_SECTORS.get(ah_sec, []))
            if us_mv is None or ah_mv is None:
                P.append("- %s ↔ %s：数据不全" % (us_sec, ah_sec))
                continue
            if us_mv > 0 and ah_mv > 0:
                rel = "跟随向上 ✅"
            elif us_mv < 0 and ah_mv < 0:
                rel = "跟随向下 ⬇️"
            elif us_mv > 0 and ah_mv < 0:
                rel = "背离（美股热 / A股冷）⚠️"
            elif us_mv < 0 and ah_mv > 0:
                rel = "背离（美股冷 / A股强）🔄"
            else:
                rel = "中性"
            P.append("- %s(%s) → %s(%s)：%s"
                     % (us_sec, _pct(us_mv), ah_sec, _pct(ah_mv), rel))
    else:
        P.append("- 无早盘数据，跳过验证")
    P.append("")

    # 五/六、异动 + 明日事件
    sec_n = 5
    if alerts:
        P.append("## 五、⚠ 异动提醒")
        for a in alerts:
            P.append("- " + a)
        P.append("")
        sec_n = 6
    if events:
        P.append("## %s、📅 明日财经事件（含对A股影响）" % sec_n)
        for d, title, etype, impact in events:
            P.append("- %s %s（%s）" % (d, title, etype))
            if impact and impact != "—":
                P.append("  ↳ %s" % impact)
        P.append("")

    P.append("> 数据：腾讯行情（A/H 收盘）+ 东方财富（资金面，字段以部署后校验为准）。")
    return "\n".join(P)


def _etf_list():
    from config import ETF_SHARE_TRACK
    return ETF_SHARE_TRACK


def morning_wind_snapshot(quotes):
    """早报跑完，导出各美股板块平均涨跌，供晚报做风向验证。"""
    return {sec: _sector_avg(quotes, members) for sec, members in SECTORS.items()}


# ───────────── 标题：免费版微信卡片只显示标题，把核心结论压进去 ─────────────
# Server酱 免费会员卡片「仅显示标题」，正文要点开「查看详情」。
# 官方限制：title ≤ 32 字符、不能含换行。故标题要自带结论。
_INDEX_SHORT = {
    "usIXIC": "纳指", "usDJI": "道指", "usSPX": "标普",
    "sh000001": "沪指", "sz399001": "深成", "sz399006": "创业板",
    "r_hkHSI": "恒指", "r_hkHSTECH": "恒科",
}


def _index_brief(code, quotes):
    v = (quotes.get(code) or {}).get("change_pct")
    if v is None:
        return None
    return "%s%+.1f%%" % (_INDEX_SHORT.get(code, "指数"), v)


def _hot_sector_count(pct_data, sectors):
    n = 0
    for members in sectors.values():
        vals = [(pct_data.get(c) or {}).get("three_year") for c, _, _ in members]
        vals = [v for v in vals if v is not None]
        if vals and sum(vals) / len(vals) >= HEAT_HOT:
            n += 1
    return n


def _brief(prefix, quotes, pct_data, alerts, index_code, sectors, focus):
    parts = [prefix]
    idx = _index_brief(index_code, quotes)
    if idx:
        parts.append(idx)
    if focus:
        parts.append(focus)
    hot = _hot_sector_count(pct_data, sectors)
    if hot:
        parts.append("过热%d" % hot)
    if alerts:
        parts.append("⚠%d" % len(alerts))
    return " ".join(parts)[:32]


def build_morning_title(quotes, pct_data, alerts):
    """早报标题：纳指风向 + 资金最活跃板块（ETF成交额最大）+ 过热数。"""
    best = None
    for sec, code in SECTOR_ETF.items():
        amt = (quotes.get(code) or {}).get("amount") if code else None
        if amt is not None and (best is None or amt > best[1]):
            best = (sec, amt)
    focus = ("钱在%s" % best[0]) if best else None
    return _brief("📊早报", quotes, pct_data, alerts, "usIXIC", SECTORS, focus)


def build_evening_title(quotes, pct_data, alerts):
    """晚报标题：沪指 + 领涨板块 + 过热数。"""
    best = None
    for sec, members in A_H_SECTORS.items():
        mv = _sector_avg(quotes, members)
        if mv is not None and (best is None or mv > best[1]):
            best = (sec, mv)
    focus = ("%s领涨" % best[0]) if best else None
    return _brief("📊晚报", quotes, pct_data, alerts, "sh000001", A_H_SECTORS, focus)
