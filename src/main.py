# -*- coding: utf-8 -*-
"""
main.py —— 统一入口（GitHub Actions / 本地手动运行）。

用法：
  python main.py --mode morning      早报（隔夜美股）
  python main.py --mode evening       晚报（A股/港股 + 资金面）
  python main.py --mode monthly       月报（自动取上月）
  python main.py --mode semiannual    半年报（1/1→上年H2，7/1→本年H1）
  python main.py --mode annual        年报（12/31→当年全年）
  python main.py --mode init          初始化/补齐 3 年历史收盘价缓存
  python main.py --mode test          推送一条测试消息

数据落盘：每日快照写 data/daily_YYYY.json，历史缓存写 data/history.json，
          均随仓库 git 提交保存（见 .github/workflows 里的 commit 步骤）。
"""

import os
import sys
import json
import argparse
import datetime

# 让 src 可直接 import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import fetcher
import percentile
import pusher
import alerts as alerts_mod
import calendar as calendar_mod
import report as report_mod
import summarize


def _now_beijing():
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=8))


def us_market_closed_now():
    beijing = _now_beijing()
    us = beijing - datetime.timedelta(hours=12)
    d = us.date()
    if d.weekday() >= 5:
        return True
    if d.isoformat() in set(config.US_HOLIDAYS):
        return True
    return False


def a_market_closed_now():
    d = _now_beijing().date()
    if d.weekday() >= 5:
        return True
    if d.isoformat() in set(config.A_HOLIDAYS):
        return True
    return False


def _build_ppt(quotes, hist):
    """为每只 code 计算 52周分位 / 3年分位。"""
    ppt = {}
    for code, q in quotes.items():
        closes = fetcher.get_closes(code, hist)
        price = q.get("price") if q else None
        if price is None or not closes:
            ppt[code] = {"week52": None, "three_year": None}
            continue
        ppt[code] = {
            "week52": percentile.week52_percentile(price, closes),
            "three_year": percentile.three_year_percentile(price, closes),
        }
    return ppt


def _sector_avg_move(sector_members, quotes):
    moves = [quotes.get(c, {}).get("change_pct")
             for c, _, _ in sector_members
             if quotes.get(c, {}).get("change_pct") is not None]
    if not moves:
        return None
    return sum(moves) / len(moves)


def _snapshot(mode, quotes, ppt, sectors_info, capital):
    return {
        "date": _now_beijing().strftime("%Y-%m-%d"),
        "mode": mode,
        "quotes": {c: {"name": q.get("name"), "price": q.get("price"),
                       "change_pct": q.get("change_pct")}
                   for c, q in quotes.items() if q},
        "pct": {c: ppt.get(c, {}) for c in quotes},
        "sectors": sectors_info,
        "capital": capital or {},
    }


def _append_daily(snap):
    path = config.daily_file()
    data = []
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = []
    data.append(snap)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def _last_prior_snapshot():
    """读当年 daily 文件，返回按日期排序的最后一个快照（用于 ETF/两融 delta）。"""
    path = config.daily_file()
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data[-1] if data else None
    except Exception:
        return None


def _last_morning_path():
    return os.path.join(config.DATA_DIR, "last_morning.json")


def _save_last_morning(wind_dict):
    """保存早盘美股板块涨跌快照，供晚报做『风向验证』。"""
    try:
        with open(_last_morning_path(), "w", encoding="utf-8") as f:
            json.dump({"asof": _now_beijing().strftime("%Y-%m-%d"),
                       "sectors": wind_dict}, f, ensure_ascii=False)
    except Exception as e:
        print("save last_morning failed:", e)


def _load_last_morning():
    path = _last_morning_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("sectors") or {}
    except Exception:
        return None


def run_morning():
    if us_market_closed_now():
        title = "📊 早报 · 美股休市"
        desp = ("# 📊 早报\n\n美股今日（或最近交易日）休市，暂无隔夜行情。\n"
                "下一交易日恢复正常推送。\n\n> %s"
                % _now_beijing().strftime("%Y-%m-%d %H:%M"))
        ok, msg = pusher.push(title, desp)
        print("morning(休市):", ok, msg)
        return

    codes = [c for c, _ in config.US_INDICES]
    for sec, members in config.SECTORS.items():
        codes += [c for c, _, _ in members]
    quotes = fetcher.fetch_quotes(codes)
    hist = fetcher.ensure_history(codes, config.PERCENTILE_WINDOW_YEARS,
                                 {c: (quotes[c]["price"] if c in quotes else None)
                                  for c in codes})
    ppt = _build_ppt(quotes, hist)
    al = alerts_mod.check_alerts(quotes, ppt)
    ev = calendar_mod.tomorrow_events()

    sectors_info = {sec: {"avg_move": _sector_avg_move(members, quotes)}
                   for sec, members in config.SECTORS.items()}
    snap = _snapshot("morning", quotes, ppt, sectors_info, None)
    _append_daily(snap)
    # 导出早盘风向快照，供晚报做「风向验证」
    _save_last_morning(report_mod.morning_wind_snapshot(quotes))

    desp = report_mod.build_morning(quotes, ppt, al, ev,
                                   _now_beijing().strftime("%Y-%m-%d %H:%M"))
    ok, msg = pusher.push("📊 早报 · 隔夜美股", desp)
    print("morning:", ok, msg)


def run_evening():
    if a_market_closed_now():
        title = "📊 晚报 · A股/港股休市"
        desp = ("# 📊 晚报\n\nA股/港股今日休市，暂无收盘行情与资金面数据。\n"
                "下一交易日恢复正常推送。\n\n> %s"
                % _now_beijing().strftime("%Y-%m-%d %H:%M"))
        ok, msg = pusher.push(title, desp)
        print("evening(休市):", ok, msg)
        return

    codes = ([c for c, _ in config.A_INDICES] + [c for c, _ in config.HK_INDICES])
    for sec, members in config.A_H_SECTORS.items():
        codes += [c for c, _, _ in members]
    quotes = fetcher.fetch_quotes(codes)
    hist = fetcher.ensure_history(codes, config.PERCENTILE_WINDOW_YEARS,
                                 {c: (quotes[c]["price"] if c in quotes else None)
                                  for c in codes})
    ppt = _build_ppt(quotes, hist)
    al = alerts_mod.check_alerts(quotes, ppt)
    ev = calendar_mod.tomorrow_events()

    # 资金面
    capital = {"southbound": fetcher.fetch_southbound(),
               "etf": fetcher.fetch_etf_shares(),
               "margin": fetcher.fetch_margin_balance(),
               "southbound_focus": fetcher.fetch_southbound_focus()}
    # 计算 ETF 份额 / 两融 较上日 delta
    prev = _last_prior_snapshot()
    if prev and prev.get("capital"):
        prev_etf = (prev["capital"] or {}).get("etf") or {}
        for code, e in capital["etf"].items():
            pe = prev_etf.get(code, {})
            if e.get("shares") is not None and pe.get("shares") is not None:
                e["delta"] = round(e["shares"] - pe["shares"], 4)
        prev_mg = (prev["capital"] or {}).get("margin") or {}
        if (capital["margin"].get("balance") is not None
                and prev_mg.get("balance") is not None):
            capital["margin"]["delta"] = round(
                capital["margin"]["balance"] - prev_mg["balance"], 2)

    sectors_info = {sec: {"avg_move": _sector_avg_move(members, quotes)}
                   for sec, members in config.A_H_SECTORS.items()}
    snap = _snapshot("evening", quotes, ppt, sectors_info, capital)
    _append_daily(snap)

    wind_ref = _load_last_morning()
    desp = report_mod.build_evening(quotes, ppt, al, ev, capital,
                                   _now_beijing().strftime("%Y-%m-%d %H:%M"),
                                   wind_ref=wind_ref)
    ok, msg = pusher.push("📊 晚报 · A股/港股 + 资金面", desp)
    print("evening:", ok, msg)


def run_monthly():
    today = _now_beijing().date()
    # 取上月
    if today.month == 1:
        y, m = today.year - 1, 12
    else:
        y, m = today.year, today.month - 1
    desp = summarize.monthly_report(y, m)
    pusher.push("📅 月度报告 %04d-%02d" % (y, m), desp)
    _save_report("monthly_%04d_%02d" % (y, m), desp)


def run_semiannual():
    today = _now_beijing().date()
    if today.month == 1:
        # 1/1 → 上一年 H2
        y, sm, em = today.year - 1, 7, 12
    elif today.month == 7:
        y, sm, em = today.year, 1, 6
    else:
        print("semiannual 仅在 1/1 与 7/1 运行，当前 %02d-%02d 跳过" % (today.year, today.month))
        return
    desp = summarize.period_report("half", y, sm, em)
    pusher.push("📈 半年度报告 %d" % y, desp)
    _save_report("half_%d" % y, desp)


def run_annual():
    today = _now_beijing().date()
    y = today.year
    desp = summarize.period_report("year", y, 1, 12)
    pusher.push("📊 年度报告 %d" % y, desp)
    _save_report("annual_%d" % y, desp)


def _save_report(name, desp):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    p = os.path.join(config.DATA_DIR, "report_%s.md" % name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(desp)


def run_init():
    codes = config.all_us_hk_a_codes()
    print("init: 拉取 %d 个标的的 %d 年历史..." % (len(codes), config.PERCENTILE_WINDOW_YEARS))
    # 先拿到今日收盘价（用于把今天补进缓存）
    quotes = fetcher.fetch_quotes(list(codes))
    hist = fetcher.ensure_history(codes, config.PERCENTILE_WINDOW_YEARS,
                                 {c: (quotes[c]["price"] if c in quotes else None)
                                  for c in codes})
    total = sum(len(v.get("dates", [])) for v in hist.values())
    print("init done: %d 个标的，共 %d 条历史收盘价，已写入 %s"
          % (len(hist), total, config.HISTORY_FILE))


def run_test():
    title = "✅ 推送链路测试"
    desp = ("# 推送链路测试\n\n若你收到这条消息，说明 Server酱/WxPusher 配置成功。\n\n"
            "> %s" % _now_beijing().strftime("%Y-%m-%d %H:%M:%S"))
    ok, msg = pusher.push(title, desp)
    print("test:", ok, msg)


def main():
    ap = argparse.ArgumentParser(description="板块冷热 + 资金方向 每日提醒")
    ap.add_argument("--mode", required=True,
                    choices=["morning", "evening", "monthly", "semiannual",
                             "annual", "init", "test"])
    args = ap.parse_args()
    {
        "morning": run_morning,
        "evening": run_evening,
        "monthly": run_monthly,
        "semiannual": run_semiannual,
        "annual": run_annual,
        "init": run_init,
        "test": run_test,
    }[args.mode]()


if __name__ == "__main__":
    main()
