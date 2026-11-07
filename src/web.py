# -*- coding: utf-8 -*-
"""
web.py —— 生成静态网页版报告（GitHub Pages 发布 docs/ 目录）。

每次早报/晚报运行会：
  1. 把报告正文写成 docs/reports/YYYY-MM-DD-morning.html（或 evening）
  2. 重建 docs/index.html —— 按月份分组、每天一行、上午/下午两列的目录页

纯标准库，页面自适应手机与电脑。仓库设为 public 后由 GitHub Pages 自动发布。
"""

import os
import re
import html
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(ROOT, "docs")
REPORTS_DIR = os.path.join(DOCS_DIR, "reports")
INDEX_FILE = os.path.join(DOCS_DIR, "index.html")

KIND_META = {
    "morning": ("🌅 早报 · 08:00", "隔夜美股风向标"),
    "evening": ("🌆 晚报 · 20:30", "A股/港股 + 资金面"),
    "monthly": ("📅 月报", "月度汇总"),
    "semiannual": ("📈 半年报", "半年度汇总"),
    "annual": ("📊 年报", "年度汇总"),
}

_CSS = """
:root{--bg:#f5f6f8;--card:#fff;--text:#1f2328;--muted:#6b7280;--line:#e5e7eb;
--accent:#2563eb;--up:#d1242f;--down:#1a7f37}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font:16px/1.75 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:860px;margin:0 auto;padding:24px 16px 60px}
header h1{font-size:22px;margin:0 0 6px}
.sub{color:var(--muted);font-size:14px;margin-bottom:22px;line-height:1.6}
.month{font-size:15px;color:var(--muted);margin:26px 0 12px;font-weight:600}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:16px;margin-bottom:12px;box-shadow:0 1px 2px rgba(0,0,0,.03)}
.date{font-weight:700;font-size:16px;margin-bottom:12px}
.date .tag{font-weight:400;font-size:13px;color:var(--muted);margin-left:8px}
.row{display:flex;gap:12px;flex-wrap:wrap}
.slot{flex:1 1 250px;min-width:0}
a.btn{display:block;text-decoration:none;padding:12px 14px;border:1px solid var(--line);
border-radius:10px;background:#fafbfc;color:var(--text);transition:.15s}
a.btn:hover{border-color:var(--accent);background:#f0f6ff}
a.btn .k{display:block;font-size:13px;color:var(--muted);margin-bottom:2px}
a.btn .v{font-weight:600}
.empty{display:block;padding:12px 14px;border:1px dashed var(--line);
border-radius:10px;color:var(--muted);background:#fafbfc;font-size:14px}
.report{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:22px 20px}
.report h1{font-size:20px;margin:0 0 4px;border-bottom:1px solid var(--line);padding-bottom:12px}
.report h2{font-size:17px;margin-top:26px;border-left:4px solid var(--accent);padding-left:10px}
.report h3,.report h4{font-size:15px;margin-top:20px}
.report p{margin:8px 0}
.report ul{padding-left:22px;margin:8px 0}
.report li{margin:4px 0}
.report blockquote{margin:20px 0 0;padding:10px 14px;background:#f6f8fa;
border-left:4px solid var(--line);color:var(--muted);font-size:14px}
.report code{background:#f3f4f6;padding:1px 5px;border-radius:4px;font-size:14px}
.report a{color:var(--accent)}
.up{color:var(--up)}.down{color:var(--down)}
.back{display:inline-block;margin-bottom:16px;color:var(--accent);text-decoration:none;font-size:14px}
footer{margin-top:28px;color:var(--muted);font-size:13px;text-align:center;line-height:1.7}
@media(max-width:520px){.wrap{padding:16px 12px 40px}.row{flex-direction:column}
.report{padding:16px 14px}header h1{font-size:20px}}
"""

_WEEK = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _inline(s):
    """极简行内 Markdown：加粗、代码、链接；并把涨跌数字按 A股习惯着色。"""
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)",
               r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
    s = re.sub(r"(\+\d+(?:\.\d+)?%)", r'<span class="up">\1</span>', s)
    s = re.sub(r"(\-\d+(?:\.\d+)?%)", r'<span class="down">\1</span>', s)
    return s


def md_to_html(md):
    """把报告用的 Markdown 子集转成 HTML（标题/列表/引用/段落）。"""
    out, in_ul, in_quote = [], False, False
    for raw in (md or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            if in_ul:
                out.append("</ul>"); in_ul = False
            if in_quote:
                out.append("</blockquote>"); in_quote = False
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            if in_ul:
                out.append("</ul>"); in_ul = False
            if in_quote:
                out.append("</blockquote>"); in_quote = False
            lvl = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (lvl, _inline(m.group(2)), lvl))
            continue
        if line.startswith("> "):
            if in_ul:
                out.append("</ul>"); in_ul = False
            if not in_quote:
                out.append("<blockquote>"); in_quote = True
            out.append("<p>%s</p>" % _inline(line[2:]))
            continue
        if in_quote:
            out.append("</blockquote>"); in_quote = False
        stripped = line.lstrip()
        if stripped.startswith("- "):
            if not in_ul:
                out.append("<ul>"); in_ul = True
            out.append("<li>%s</li>" % _inline(stripped[2:]))
            continue
        if in_ul:
            out.append("</ul>"); in_ul = False
        out.append("<p>%s</p>" % _inline(line))
    if in_ul:
        out.append("</ul>")
    if in_quote:
        out.append("</blockquote>")
    return "\n".join(out)


def _shell(inner, title):
    return ("<!doctype html>\n<html lang=\"zh-CN\">\n<head>\n"
            "<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
            "<title>%s</title>\n<style>%s</style>\n</head>\n<body>\n"
            "<div class=\"wrap\">%s</div>\n</body>\n</html>\n"
            % (html.escape(title), _CSS, inner))


def save_report(kind, date_str, title, desp):
    """生成单篇报告页，返回相对 docs/ 的路径。"""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    name = "%s-%s.html" % (date_str, kind)
    label = KIND_META.get(kind, ("报告", ""))[0]
    inner = ('<a class="back" href="../index.html">← 返回报告列表</a>\n'
             '<div class="report">%s</div>\n'
             '<footer>%s · %s<br>数据仅供参考，不构成投资建议</footer>'
             % (md_to_html(desp), html.escape(label), html.escape(date_str)))
    with open(os.path.join(REPORTS_DIR, name), "w", encoding="utf-8") as f:
        f.write(_shell(inner, title or "%s %s" % (label, date_str)))
    return "reports/" + name


def _scan():
    """扫描已生成的报告页，返回 {date: {kind: path}}。"""
    found = {}
    if not os.path.isdir(REPORTS_DIR):
        return found
    pat = re.compile(r"^(\d{4}-\d{2}-\d{2})-(\w+)\.html$")
    for fn in os.listdir(REPORTS_DIR):
        m = pat.match(fn)
        if m:
            found.setdefault(m.group(1), {})[m.group(2)] = "reports/" + fn
    return found


def rebuild_index():
    """重建目录页：按月份分组、每天一行、上午/下午两列。"""
    os.makedirs(DOCS_DIR, exist_ok=True)
    data = _scan()
    parts = [
        '<header><h1>📊 板块冷热提醒 · 报告列表</h1>',
        '<div class="sub">早报 08:00（隔夜美股风向标）· 晚报 20:30（A股/港股 + 资金面）'
        '｜点任意一条看全文｜周末与休市日不生成</div></header>',
    ]
    if not data:
        parts.append('<div class="card"><div class="empty">暂无报告，下一次交易日自动推送后这里会出现内容。</div></div>')
    by_month = {}
    for d in sorted(data, reverse=True):
        by_month.setdefault(d[:7], []).append(d)
    for ym in sorted(by_month, reverse=True):
        y, m = ym.split("-")
        parts.append('<div class="month">%s年%s月</div>' % (y, int(m)))
        for d in by_month[ym]:
            try:
                wd = _WEEK[datetime.date(*map(int, d.split("-"))).weekday()]
            except Exception:
                wd = ""
            parts.append('<div class="card"><div class="date">%s<span class="tag">%s</span></div><div class="row">'
                         % (d, wd))
            for kind in ("morning", "evening"):
                label, subtitle = KIND_META[kind]
                path = data[d].get(kind)
                if path:
                    parts.append('<div class="slot"><a class="btn" href="%s">'
                                 '<span class="k">%s</span><span class="v">%s →</span></a></div>'
                                 % (path, label, subtitle))
                else:
                    parts.append('<div class="slot"><span class="empty">%s　%s</span></div>'
                                 % (label, "休市 / 未生成"))
            parts.append('</div></div>')
    # 汇总类报告（月/半年/年）
    extras = [(d, k, p) for d, kinds in data.items() for k, p in kinds.items()
              if k in ("monthly", "semiannual", "annual")]
    if extras:
        parts.append('<div class="month">汇总报告</div><div class="card"><div class="row">')
        for d, k, p in sorted(extras, reverse=True):
            label, _ = KIND_META[k]
            parts.append('<div class="slot"><a class="btn" href="%s">'
                         '<span class="k">%s</span><span class="v">%s →</span></a></div>'
                         % (p, label, d))
        parts.append('</div></div>')
    parts.append('<footer>由 GitHub Actions 每日自动生成并发布<br>'
                 '数据：腾讯行情 / 东方财富｜仅供参考，不构成投资建议</footer>')
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        f.write(_shell("\n".join(parts), "板块冷热提醒 · 报告列表"))
    return INDEX_FILE


if __name__ == "__main__":
    print("rebuild ->", rebuild_index())
