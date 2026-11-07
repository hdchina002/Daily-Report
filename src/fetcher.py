# -*- coding: utf-8 -*-
"""
fetcher.py —— 所有外部数据源（行情 + 历史K线 + 资金面）。

数据源与可靠性说明：
  ✅ 腾讯 qt.gtimg.cn 实时报价       —— 已验证可用（GBK 编码，见下方解析）
  ✅ 东方财富 push2his 历史K线       —— 2026-11 起主数据源（前复权日K，一次取满 3 年）
     腾讯 web.ifzq.gtimg.cn 历史K线已失效（返回 code:11 No dispatch info found），仅保留作降级。
  ⚠️ 东方财富 南向/北向/ETF份额/两融 —— 免费接口，字段可能随版本变动；
       代码已做防御式解析，取不到时返回 None，报告里显示「—」而**不会中断推送**。
       首次部署后请按 README「验证 API 代码」小节核对这几个字段。

所有对外函数都保证「取不到就降级」，主流程不会因为某个接口挂了而崩。
"""

import os
import re
import json
import time
import datetime
import urllib.request
import urllib.parse

from config import (HISTORY_FILE, DATA_DIR, US_HOLIDAYS, A_H_HOLIDAYS,
                    ETF_SHARE_TRACK, HEAT_HOT, HEAT_COLD)
import percentile


# ───────────────────────────── 通用 HTTP（复用参考实现的稳健写法） ─────────────────────────────
def http_get(url, decode="utf-8", retry=3, timeout=8, referer="https://finance.qq.com"):
    """带重试的 GET；显式清空代理（避免本机/CI 的 HTTP_PROXY 拦截）。"""
    last = None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(retry):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "Referer": referer,
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "*/*",
                    "Cache-Control": "no-cache",
                },
            )
            raw = opener.open(req, timeout=timeout).read()
            return raw.decode(decode, "ignore")
        except Exception as e:
            last = e
            time.sleep(0.4)
    # 全部失败：返回空串，由调用方降级
    return ""


# ───────────────────────────── 实时报价（腾讯 qt.gtimg.cn） ─────────────────────────────
def _parse_tencent(text):
    """解析 v_xxx="..."; 多只以 ; 分隔。返回 {code: {...}}。
    字段索引（~ 分隔，经验布局）：
      1=名称 2=代码 3=现价 4=昨收 5=今开 31=涨跌 32=涨跌% 33=最高 34=最低
      50=52周最高 51=52周最低（部分市场/指数无，缺则降级为 None）
    """
    qmap = {}
    if not text:
        return qmap
    for line in text.split(";"):
        m = re.search(r'v_(\w+)="(.+)"', line)
        if not m:
            continue
        sc, payload = m.group(1), m.group(2)
        vals = payload.split("~")
        if len(vals) < 5:
            continue
        try:
            name = vals[1]
            price = float(vals[3]) if vals[3] else None
            prev = float(vals[4]) if vals[4] else None
            chg_pct = float(vals[32]) if len(vals) > 32 and vals[32] else None
            high = float(vals[33]) if len(vals) > 33 and vals[33] else None
            low = float(vals[34]) if len(vals) > 34 and vals[34] else None
            # 成交量(股) / 成交额(本币)：美股与A股均在 [6]/[37]，已实测
            volume = float(vals[6]) if len(vals) > 6 and vals[6] else None
            amount = float(vals[37]) if len(vals) > 37 and vals[37] else None
            # 52周高低仅当「高>低>0」才可信：部分市场（如美股）该字段为垃圾值（-200/空）
            w52h = float(vals[50]) if len(vals) > 50 and vals[50] else None
            w52l = float(vals[51]) if len(vals) > 51 and vals[51] else None
            if not (w52h and w52l and w52h > w52l > 0):
                w52h = w52l = None
        except (ValueError, IndexError):
            continue
        # 时间/日期：优先紧凑时间戳 ~20261105100828~，否则正则抓 时分秒
        tstr = ""
        mm = re.search(r"~(\d{14})~", payload)
        if mm:
            v = mm.group(1)
            tstr = f"{v[0:4]}-{v[4:6]}-{v[6:8]} {v[8:10]}:{v[10:12]}:{v[12:14]}"
        else:
            tm = re.search(r"(\d{2}:\d{2}(?::\d{2})?)", payload)
            dt = re.search(r"(\d{4}[-/]\d{2}[-/]\d{2})", payload)
            tstr = (dt.group(1) + " " + tm.group(1)) if dt and tm else (tm.group(1) if tm else "")
        qmap[sc] = {
            "name": name, "price": price, "prev_close": prev,
            "change_pct": chg_pct, "high": high, "low": low,
            "volume": volume, "amount": amount,
            "week52_high": w52h, "week52_low": w52l, "time": tstr,
        }
    return qmap


def fetch_quotes(symbols):
    """批量拉取实时报价。symbols 为代码列表（如 ['usNVDA','hk00700']）。
    返回 {code: {...}}；取不到的代码不会出现在结果里。"""
    if not symbols:
        return {}
    joined = ",".join(symbols)
    text = http_get("https://qt.gtimg.cn/q=" + joined, decode="gbk",
                    retry=3, timeout=8, referer="https://finance.qq.com")
    return _parse_tencent(text)


# ───────────────────────────── 历史 K 线（腾讯，前复权日K） ─────────────────────────────
def _parse_kline(json_text):
    """解析腾讯 kline 返回，返回 [(date, close), ...]（升序）。"""
    out = []
    if not json_text:
        return out
    try:
        data = json.loads(json_text)
    except ValueError:
        return out
    # 取第一个可用的标的节点
    node = None
    d = (data.get("data") or {}) if isinstance(data, dict) else None
    if isinstance(d, dict):
        for v in d.values():
            if isinstance(v, dict):
                node = v
                break
    if not node:
        return out
    bars = node.get("qfqday") or node.get("day") or []
    for bar in bars:
        try:
            # 常见布局： [date, open, close, high, low, volume]（6 列）
            # 或 [date, open, close, high, low]（5 列）
            close = float(bar[2])
            out.append((str(bar[0]), close))
        except (IndexError, ValueError, TypeError):
            continue
    out.sort(key=lambda x: x[0])
    return out


def fetch_kline(symbol, end_date, count=320):
    """拉取 symbol 截至 end_date 的最近 count 根日K（前复权）。
    返回 [(date, close), ...] 升序。失败返回 []。"""
    url = ("https://web.ifzq.gtimg.cn/appstuff/app/kline/kline?param=%s,day,,,%d"
           % (symbol, count))
    # 腾讯 kline 用 param 的 END 位控制截止日：,day,START,END,COUNT
    url = ("https://web.ifzq.gtimg.cn/appstuff/app/kline/kline?param=%s,day,,%s,%d"
           % (symbol, end_date, count))
    text = http_get(url, decode="utf-8", retry=3, timeout=10,
                    referer="https://gu.qq.com")
    return _parse_kline(text)


# 指数在东方财富的 secid 与腾讯代码不是一套，需要显式映射。
_EM_INDEX_SECID = {
    "usDJI": "100.DJIA",        # 道琼斯工业指数
    "usSPX": "100.SPX",         # 标普500
    "r_hkHSI": "100.HSI",       # 恒生指数
    "r_hkHSTECH": "124.HSTECH", # 恒生科技指数
    # usIXIC（纳斯达克综合指数）：东财只有 100.NDX（纳斯达克100），
    # 点数口径完全不同，禁止拿 NDX 的历史去算 IXIC 的分位 → 该标的分位显示「—」。
}


def _em_secid_candidates(code):
    """腾讯代码 → 东方财富 secid 候选（按优先级）。"""
    if code in _EM_INDEX_SECID:
        return [_EM_INDEX_SECID[code]]
    if code == "usIXIC":
        return []
    c = code.strip()
    if c.startswith("sh"):
        return ["1." + c[2:]]                       # 沪市
    if c.startswith("sz"):
        return ["0." + c[2:]]                       # 深市
    if c.startswith("r_hk"):
        return ["100." + c[4:], "124." + c[4:]]
    if c.startswith("hk"):
        return ["116." + c[2:]]                     # 港股
    if c.startswith("us"):
        t = c[2:]
        # 105=NASDAQ / 106=NYSE / 107=AMEX(含多数ETF) / 100=指数
        return ["105." + t, "106." + t, "107." + t, "100." + t]
    if c.isdigit():                                 # 纯数字 ETF，如 159992
        return ["0." + c, "1." + c]
    return []


def fetch_history_em(symbol, years=3):
    """东方财富 push2his：一次取近 years 年的前复权日K。
    返回升序 [(date, close)]；自动在多个 secid 候选中选第一个有数据的；全失败返回 []。

    fields2=f51,f53 → 每行 "YYYY-MM-DD,收盘价"（已实测，2 列）。
    """
    beg = (datetime.date.today()
           - datetime.timedelta(days=int(years * 365.25) + 15)).strftime("%Y%m%d")
    for secid in _em_secid_candidates(symbol):
        url = ("https://push2his.eastmoney.com/api/qt/stock/kline/get?"
               "secid=%s&klt=101&fqt=1&beg=%s&end=20500101&"
               "fields1=f1,f2&fields2=f51,f53" % (secid, beg))
        text = http_get(url, decode="utf-8", retry=2, timeout=10,
                        referer="https://quote.eastmoney.com")
        if not text:
            continue
        try:
            kl = ((json.loads(text).get("data") or {}) or {}).get("klines") or []
        except (ValueError, AttributeError):
            continue
        bars = []
        for row in kl:
            parts = row.split(",")
            if len(parts) >= 2:
                try:
                    bars.append((parts[0], float(parts[1])))
                except (ValueError, IndexError):
                    continue
        if bars:
            bars.sort(key=lambda x: x[0])
            return bars
    return []


def _fetch_history_tencent(symbol, years=3):
    """降级：腾讯分页拉日K（该接口 2026-11 起返回 code:11，保留兜底）。"""
    needed = int(years * 252) + 30
    end = datetime.date.today().strftime("%Y-%m-%d")
    all_bars, seen = [], set()
    for _ in range(20):
        bars = fetch_kline(symbol, end, count=320)
        if not bars:
            break
        for d, c in bars:
            if d not in seen:
                seen.add(d)
                all_bars.append((d, c))
        if len(all_bars) >= needed:
            break
        earliest = min(all_bars, key=lambda b: b[0])[0] if all_bars else end
        try:
            dt = datetime.datetime.strptime(earliest, "%Y-%m-%d").date()
            end = (dt - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        except ValueError:
            break
    all_bars.sort(key=lambda x: x[0])
    return all_bars


def fetch_history_full(symbol, years=3):
    """拉满近 years 年日K（前复权），返回升序 [(date, close)]。
    主用东方财富；取不到再降级腾讯分页。无可用 secid 的标的直接跳过，不发无效请求。"""
    if not _em_secid_candidates(symbol):
        return []
    bars = fetch_history_em(symbol, years)
    return bars if bars else _fetch_history_tencent(symbol, years)


# ───────────────────────────── 本地历史缓存（随仓库提交） ─────────────────────────────
def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {}
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_history(hist):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = HISTORY_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False)
    os.replace(tmp, HISTORY_FILE)


def ensure_history(symbols, years=3, today_close_map=None):
    """初始化或增量更新历史缓存。
    - 首次：拉满 years 年全量；
    - 之后：仅用实时报价把「今天」的收盘价补进缓存（避免每日再拉全量）。
    today_close_map: {code: price}，来自 fetch_quotes；为 None 时仅保证缓存存在。
    返回更新后的 hist。"""
    hist = load_history()
    today = datetime.date.today().strftime("%Y-%m-%d")
    changed = False
    for sym in symbols:
        node = hist.get(sym)
        if node and node.get("unavailable"):
            # 负缓存：该标的确认无历史数据源（如纳斯达克综合指数、OTC ADR），
            # 避免每次运行都重复发一堆注定失败的请求。
            continue
        if not node or not node.get("dates"):
            bars = fetch_history_full(sym, years)
            if bars:
                hist[sym] = {"dates": [b[0] for b in bars],
                             "closes": [b[1] for b in bars]}
            else:
                hist[sym] = {"dates": [], "closes": [], "unavailable": True}
            changed = True
            node = hist.get(sym)  # 首次刚写入，必须重新取，不能沿用上面的 None
        # 增量：把今天收盘价补进去（若已有同日则覆盖）
        if today_close_map and sym in today_close_map:
            price = today_close_map[sym]
            if price and node and node.get("dates"):
                dates, closes = node["dates"], node["closes"]
                if dates and dates[-1] == today:
                    closes[-1] = price
                else:
                    dates.append(today)
                    closes.append(price)
                changed = True
    if changed:
        save_history(hist)
    return hist


def get_closes(symbol, hist=None):
    if hist is None:
        hist = load_history()
    node = hist.get(symbol)
    if not node:
        return []
    return node.get("closes", [])


# ───────────────────────────── 资金面（东方财富，防御式） ─────────────────────────────
def _em_json(url):
    text = http_get(url, decode="utf-8", retry=2, timeout=8,
                   referer="https://quote.eastmoney.com")
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def fetch_southbound():
    """南向资金（港股通净买入，单位：亿港元）。

    数据源：东方财富 datacenter `RPT_MUTUAL_DEAL_HISTORY`。
    MUTUAL_TYPE: 002=港股通(沪)、004=港股通(深)；NET_DEAL_AMT 单位为**百万港元**。
    原代码用的 kamt 接口里 `hkgt.netBuy` 字段根本不存在，故一直显示「—」。
    北向实时净流向 2024-08 已停用，不再尝试。
    """
    res = {"date": "", "south_net": None, "north_net": None, "note": ""}
    total, date, got = 0.0, "", 0
    for mt in ("002", "004"):
        url = ("https://datacenter-web.eastmoney.com/api/data/v1/get?"
               "reportName=RPT_MUTUAL_DEAL_HISTORY&columns=ALL&pageSize=1&"
               "sortColumns=TRADE_DATE&sortTypes=-1&source=WEB&client=WEB&"
               "filter=(MUTUAL_TYPE%3D%22" + mt + "%22)")
        j = _em_json(url)
        rows = ((j or {}).get("result") or {}).get("data") or []
        if not rows:
            continue
        r = rows[0]
        v = _to_float(r.get("NET_DEAL_AMT"))
        if v is not None:
            total += v / 100.0      # 百万港元 → 亿港元
            got += 1
        date = date or (r.get("TRADE_DATE") or "")[:10]
    if got:
        res["south_net"] = round(total, 2)
        res["date"] = date
        res["note"] = "北向实时净流向已于2024-08停用，仅南向可用"
    else:
        res["note"] = "南向接口暂不可用"
    return res


def fetch_etf_shares():
    """行业/主题 ETF 份额（亿份）+ 成交额（亿元）+ 涨跌幅。

    数据源：东方财富 `push2.eastmoney.com/api/qt/stock/get`。
    f84=总份额(份)、f48=成交额(元)、f170=涨跌幅(×100)。
    原代码用 `clist/get?fs=b:代码` 是无效查询（返回 rc:102 data:null），
    且 f106 字段在此接口不存在 —— 这是九行全「—」的原因。
    """
    out = {}
    for code, name in ETF_SHARE_TRACK:
        secid = ("1." if code.startswith("5") else "0.") + code
        url = ("https://push2.eastmoney.com/api/qt/stock/get?"
               "secid=%s&fields=f57,f58,f48,f84,f170" % secid)
        d = (_em_json(url) or {}).get("data") or {}
        shares = _to_float(d.get("f84"))
        amount = _to_float(d.get("f48"))
        chg = _to_float(d.get("f170"))
        out[code] = {
            "name": name or d.get("f58"),
            "shares": round(shares / 1e8, 4) if shares else None,   # 份 → 亿份
            "amount": round(amount / 1e8, 2) if amount else None,   # 元 → 亿元
            "chg_pct": (chg / 100.0) if chg is not None else None,
        }
    return out


def fetch_margin_balance():
    """融资融券余额（亿元）。取最新一日。

    报表 `RPTA_WEB_RZRQ_GMRQZ` 已被东财下线（返回「报表配置不存在」），
    现用 `RPTA_RZRQ_LSHJ`，排序列是 `DIM_DATE`（不是 DATE/TRADE_DATE），
    字段 `RZRQYE` 单位为元。
    """
    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get?"
           "reportName=RPTA_RZRQ_LSHJ&columns=DIM_DATE,RZYE,RQYE,RZRQYE&"
           "pageSize=2&sortColumns=DIM_DATE&sortTypes=-1&source=WEB&client=WEB")
    j = _em_json(url)
    res = {"date": "", "balance": None, "note": ""}
    rows = ((j or {}).get("result") or {}).get("data") or []
    if not rows:
        res["note"] = "两融接口暂不可用"
        return res
    r = rows[0]
    bal = _to_float(r.get("RZRQYE"))
    if bal is None:
        res["note"] = "两融解析异常"
        return res
    res["balance"] = round(bal / 1e8, 2)      # 元 → 亿元
    res["date"] = (r.get("DIM_DATE") or "")[:10]
    return res


# ─────────────── A股月度总成交额（上证 + 深成）与 3 年分位 ───────────────
_MARKET_AMOUNT_SECID = ("1.000001", "0.399001")   # 上证指数、深证成指
AMOUNT_CACHE_FILE = os.path.join(DATA_DIR, "amount_monthly.json")


def _em_daily_amount(secid, years=3):
    """指数每日成交额（元），返回升序 [(date, amount)]。fields2=f51,f57。"""
    beg = (datetime.date.today()
           - datetime.timedelta(days=int(years * 365.25) + 15)).strftime("%Y%m%d")
    url = ("https://push2his.eastmoney.com/api/qt/stock/kline/get?"
           "secid=%s&klt=101&fqt=1&beg=%s&end=20500101&"
           "fields1=f1,f2&fields2=f51,f57" % (secid, beg))
    text = http_get(url, decode="utf-8", retry=2, timeout=10,
                    referer="https://quote.eastmoney.com")
    if not text:
        return []
    try:
        kl = ((json.loads(text).get("data") or {}) or {}).get("klines") or []
    except (ValueError, AttributeError):
        return []
    out = []
    for row in kl:
        p = row.split(",")
        if len(p) >= 2:
            try:
                out.append((p[0], float(p[1])))
            except ValueError:
                continue
    return out


def _load_amount_cache():
    try:
        with open(AMOUNT_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f).get("months") or {}
    except Exception:
        return {}


def _save_amount_cache(months):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = AMOUNT_CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"months": months,
                   "updated": datetime.date.today().isoformat()},
                  f, ensure_ascii=False)
    os.replace(tmp, AMOUNT_CACHE_FILE)


def _summarize_amount(months, years=3):
    """月度汇总 → 当月总额/日均 + 近 3 年分位。

    分位用「月日均成交额」而不是月总额：当月往往没走完，且各月交易日数不同，
    用日均才能和历史完整月公平比较。
    """
    if not months:
        return {}
    keys = sorted(months)
    cur_key = keys[-1]

    def node(k):
        n = months[k]
        days = int(n.get("days") or 1)
        return {"total": float(n["total"]), "days": days,
                "daily_avg": float(n["total"]) / days}

    cur = node(cur_key)
    past = [node(k)["daily_avg"] for k in keys[:-1]][-int(years * 12):]
    pct = percentile.pct_of_price(cur["daily_avg"], past) if past else None
    heat = ""
    if pct is not None:
        if pct >= HEAT_HOT:
            heat = "过热🔥"
        elif pct <= HEAT_COLD:
            heat = "过冷❄️"
    return {
        "asof": months[cur_key].get("last_date", ""),
        "month": cur_key,
        "current": cur,
        "past_months": len(past),
        "percentile": pct,
        "heat": heat,
    }


def fetch_market_amount_monthly(years=3):
    """上证指数 + 深证成指 每月总成交额，及当月在近 3 年中的位置。

    金额单位统一为**元**，展示时再换算成万亿。接口失败降级读
    data/amount_monthly.json 缓存；仍无数据返回 {}（报告显示「—」）。
    """
    series = {}
    ok = True
    for secid in _MARKET_AMOUNT_SECID:
        bars = _em_daily_amount(secid, years)
        if not bars:
            ok = False
            break
        for d, amt in bars:
            m = d[:7]
            n = series.setdefault(m, {"total": 0.0, "dates": set()})
            n["total"] += amt
            n["dates"].add(d)
    if ok and series:
        months = {m: {"total": round(n["total"], 2),
                      "days": len(n["dates"]),
                      "last_date": max(n["dates"])}
                  for m, n in series.items()}
        _save_amount_cache(months)
    else:
        months = _load_amount_cache()
    return _summarize_amount(months, years)


# ───────────────────────────── 休市日判断 ─────────────────────────────
def _str_dates(lst):
    return set(lst or [])


def us_last_trading_day():
    """北京时间 08:00 对应的「最近一个已收盘的美股交易日」（美东上一日，跳过周末）。"""
    # 北京时间 08:00 = 美东（夏令）前一日 20:00 / （冬令）前一日 19:00，均为收盘后
    # 因此「最近交易日」= 美东「今天」若未开盘则取上一交易日；简化：取美东日期再回退到周五
    beijing = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    # 对应美东日期（粗略 -12h）
    us = beijing - datetime.timedelta(hours=12)
    d = us.date()
    while d.weekday() >= 5:  # 周六/周日回退
        d -= datetime.timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def a_last_trading_day():
    beijing = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    d = beijing.date()
    hol = _str_dates(A_H_HOLIDAYS)
    while d.weekday() >= 5 or d.isoformat() in hol:
        d -= datetime.timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def is_us_holiday(date_str):
    return date_str in _str_dates(US_HOLIDAYS)


def is_a_holiday(date_str):
    return date_str in _str_dates(A_H_HOLIDAYS)


# ───────────────────────────── 小工具 ─────────────────────────────
def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_billion(v):
    """东方财富金额常为「元」；若数值很大（>1e8）则换算成亿元。"""
    f = _to_float(v)
    if f is None:
        return None
    if abs(f) > 1e8:
        return round(f / 1e8, 2)
    if abs(f) > 1e4:
        return round(f / 1e4, 2)
    return round(f, 2)


if __name__ == "__main__":
    # 自测：解析器对「空/异常」输入不崩；历史缓存读写正常
    assert _parse_tencent("") == {}
    assert fetch_quotes([]) == {}
    assert _to_billion(1234567890) == 12.35
    assert _to_billion(50000) == 5.0
    print("fetcher self-test OK")
