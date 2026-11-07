# 板块冷热 + 资金方向 · 每日微信提醒（云端自动版 v2）

> 一套**全程云端运行**的 Python 项目：每天定时把「板块冷热」和「资金方向」推到微信，
> 每月 / 每半年 / 每年推送汇总报告。你**不开机**，由 GitHub Actions 免费跑。

---

## 一、它做什么

| 时间（北京时间） | 推送 | 内容 |
|---|---|---|
| **08:00** 早报 | 隔夜美股（**风向标**） | 三大指数 + 风险偏好定性；五大板块**冷热 + 资金热度**（板块均涨跌幅 + 3年分位均值 + **行业ETF成交额**，并标出"资金最活跃板块"）；**🧭今日中国映射**（把美股热点翻译成 A股/港股可关注方向）；异动提醒；明日财经事件（**含对A股影响**） |
| **20:30** 晚报 | A股/港股（**实盘**）+ 资金面 | A股/港股主要指数；对应五大板块的 A股/港股**映射表现**；**资金面**（**A股当日总成交额（万亿）+ 3年分位 + 历史中位/区间** / 南向净买入 / 9只行业ETF份额与成交额 / 两融余额，**每项均带 3 年分位与高低标签**）；**🧭风向验证**（早盘美股 → 今日A股 跟随/背离）；异动提醒；明日事件（含对A股影响） |
| 每月 1 日 | 月报 | 板块月度涨跌排名、最佳/最差板块、龙头个股排名、**分位变化榜**、资金流向总结、下月事件日历 |
| 1/1、7/1 | 半年报 | 各板块累计涨跌、历史分位变化轨迹（冷→热）、资金方向判断 |
| 12/31 | 年报 | 当年全年汇总 |

> **核心定位**：美股只作「风向标」——看全球风险偏好、产业趋势与政策方向，**不交易**；
> A股/港股才是真正的投资标的。早报负责"美国告诉我们什么"，晚报负责"中国盘面怎么走、资金往哪去"，
> 并用「今日中国映射」与「风向验证」把两者打通。
>
> **推送节奏**：每日早报/晚报**只在交易日发送**——周末、美股休市日、A股/港股休市日**静默跳过（不发任何消息，也不写数据）**；
> 月报 / 半年报 / 年报按周期生成，**不区分开市休市、照常发送**（它们是对过往数据的汇总）。

**核心新增 · 历史价格百分位**：当前价在「近 3 年（可改 1 年）全部交易日收盘价区间」中的位置，
公式 `(现价-最低)/(最高-最低)×100`。板块冷热 = 板块内成分股分位**均值**，≥80% 标「过热🔥」、≤20% 标「过冷❄️」。
还支持「52 周分位」简化版（优先从行情返回取，取不到则用已缓存历史回算）。

**资金热度（钱往哪去）**：用各板块**代表行业ETF的成交额**衡量（硬科技=SMH、创新药=XBI、锂矿=LIT、中概=KWEB；医美无对应美股ETF则用成分股成交额合计）。成交额越大=交易越热、资金越聚焦。A股侧则叠加**行业ETF份额净申购**（资金流入硬数据）+ **成交额**，双向印证。这五个板块本身就是你的**实盘持仓方向**（港股/A股），所以"美股最热在哪、资金在做什么"才是早报想给你看的。板块/持仓调整只需改 `src/config.py` 的 `SECTORS` / `A_H_SECTORS`（含 `SECTOR_ETF` 资金热度映射）。

**资金面每个数字都带「近 3 年分位」**：晚报里的 A股当日总成交额、南向净买入、9 只行业ETF成交额、两融余额，
全部给出 3 年分位 + 高低标签（≥90% 极高🔥 / ≥70% 偏高 / 30~70% 正常 / 10~30% 偏低 / ≤10% 极低❄️），
A股当日成交额还额外给出「近 3 年日成交额中位数与区间」作为直观基数。

- **A股当日总成交额**＝上证指数 + 深证成指**当日**成交额合计（东财日K `f57`），不再做月度累计。
- 资金面分位用**排名口径**：`今日值高于近 3 年约 X% 的交易日`。成交额/净买入常有极端尖峰，
  若沿用价格的「区间位置」公式 `(v-min)/(max-min)` 会把日常值压得偏低、误判成「冷」，故改用排名。
  两类分位口径不同，报告脚注已注明，不要横向比较。
- 近 3 年日频序列统一缓存在 `data/capital_history.json`（约 200KB，随仓库提交），
  每天晚报刷新一次；接口临时失败自动降级读旧缓存。ETF **份额**是趋势增长的存量规模，
  绝对值的分位参考意义低，故只对**成交额**算分位（份额另有「净申购/净赎回」日变化）。

**阈值告警**：任一板块单日 ±3%、关键个股（NVDA/BABA 等）±5% → 异动提醒；任一标的 3 年分位突破 90%/跌破 10% → 过热/过冷预警。
**事件日历**：美国非农（每月首周五）、CPI、PPI、零售销售**提前一天提醒**，**并附一句"对A股/港股意味着什么"**；FOMC 议息、重点公司财报在 `config.EVENTS_MANUAL` 维护。

---

## 二、架构

```
板块冷热提醒/
├── .github/workflows/        # GitHub Actions：5 个定时任务（早/晚/月/半年/年）
│   ├── daily_morning.yml
│   ├── daily_evening.yml
│   ├── monthly.yml
│   ├── semiannual.yml
│   └── annual.yml
├── src/                      # 全部源码（纯标准库，零第三方依赖）
│   ├── config.py             # ★ 监控标的 / 阈值 / 百分位窗口 / 事件日历（你最常改这里）
│   ├── fetcher.py            # 腾讯实时报价 + 东方财富历史K线 + 南向/ETF份额/两融（防御式降级）
│   ├── percentile.py         # 历史百分位核心算法（含自测）
│   ├── report.py             # 早报 / 晚报 文本生成
│   ├── alerts.py             # 阈值告警
│   ├── calendar.py           # 财经事件日历
│   ├── summarize.py          # 月报 / 半年报 / 年报
│   ├── pusher.py             # Server酱 / WxPusher 双通道
│   └── main.py               # CLI 入口：--mode morning|evening|monthly|semiannual|annual|init|test
├── data/                     # 历史与每日数据（随仓库提交保存）
│   ├── history.json          # 3 年历史收盘价缓存（init 拉全量，之后每日增量）
│   └── daily_YYYY.json       # 每日快照，月报/年报数据源
├── tests/test_percentile.py  # 集成冒烟测试
├── requirements.txt          # 仅标准库（可选 requests）
└── README.md
```

**数据源**：腾讯行情 `qt.gtimg.cn`（实时报价）、东方财富 `push2his.eastmoney.com`（历史前复权日K，2026-11 起主用）。
腾讯旧历史K线接口 `web.ifzq.gtimg.cn` 已失效（`code:11 No dispatch info found`），仅保留作降级；纳斯达克综合指数（`usIXIC`）与 OTC 的腾讯ADR（`usTCEHY`）在东财无对应历史，分位显示「—」属正常。
**推送**：Server酱 `sctapi.ftqq.com` 或 WxPusher（二选一，密钥走环境变量，**不写死**）。

---

## 三、部署步骤（约 10 分钟）

### 1. 建私有仓库 + 上传代码
- 在 GitHub 新建一个 **Private** 仓库（如 `sector-heat-reminder`）。
- 把本目录全部内容推上去（包含 `.github/` 与 `data/.gitkeep`）。
  ```bash
  git init && git add -A && git commit -m "init"
  git remote add origin git@github.com:<你>/<仓库>.git && git push -u origin main
  ```

### 2. 配置推送密钥（Settings → Secrets and variables → Actions → New repository secret）
二选一：
- **Server酱**（推荐，微信扫码拿 SendKey）：Name=`SERVERCHAN_SENDKEY`，Value=你的 SendKey。
  ① 打开 https://sct.ftqq.com 用微信扫码登录 → ② 复制「SendKey」→ ③ 公众号「方糖」会收到推送。
- **WxPusher**：Name=`WXPUSHER_TOKEN`（应用 Token）+ Name=`WXPUSHER_UIDS`（接收者 UID，逗号分隔）。
  ① 打开 https://wxpusher.zjiecode.com 注册应用拿 Token → ② 用「用户管理」拿到自己的 UID。

### 3. 初始化历史数据（关键一步）
历史百分位需要 3 年收盘价。两种办法：
- **本地初始化**（推荐，跑一次即可）：
  ```bash
  python src/main.py --mode init      # 拉全量，生成 data/history.json
  git add data/ && git commit -m "data: init history" && git push
  ```
- **云端初始化**：直接手动触发 `daily_morning` 或 `daily_evening` workflow（Actions 页面 → Run workflow），
  首次检测到没有 `history.json` 会自动先跑 `init`，再发当日报。

### 4. 启用定时任务
`.github/workflows/` 里的定时任务默认已启用（仓库有这些文件即生效）。
GitHub Actions 的 `schedule` 使用 **UTC**，本项目已换算好（并做了日级过滤，省额度）：
- 早报 `0 0 * * 1-6` = 北京 08:00（周一~周六；**保留周六**报周五美股收盘，周日无新鲜美股故跳过）。
- 晚报 `30 12 * * 1-5` = 北京 20:30（周一~周五；周末 A股/港股休市，跳过空跑）。
- 月报 `0 0 1 * *`、半年报 `0 0 1 1,7 *`、年报 `0 0 31 12 *`（均为北京当日 08:00；月报/年报不受开市影响，照常发）。
- 允许 5~15 分钟排队延迟，属正常现象。
- **工作日才真正推送**：周末、美股休市日、A股/港股休市日，脚本会自动**静默跳过**（GitHub Actions 仍会启动一次，但脚本直接结束、不发消息、也不写数据、不产生提交）。月报/半年报/年报的定时任务按固定日期触发，**不受休市影响，照常发送**。

### 5. 手动触发测试
- 想验证推送链路：本地跑 `python src/main.py --mode test`（会推一条测试消息）；
  或去 Actions 页面手动 Run `daily_morning` / `daily_evening`。
- 想看完整早报/晚报效果：本地用**合成数据**没法连真实行情，建议直接手动触发一次 workflow 看微信收到什么。

---

## 四、配置你自己的标的（改 `src/config.py`）

| 想改什么 | 改哪里 |
|---|---|
| 增删监控股票 / ETF | `SECTORS`（五大板块）、`A_H_SECTORS`（A股/港股映射）、`US_INDICES`/`HK_INDICES`/`A_INDICES` |
| 南向重点个股 | `SOUTHBOUND_FOCUS` |
| 跟踪的行业ETF | `ETF_SHARE_TRACK` |
| 告警阈值（±3%/±5%/分位90-10） | `THRESHOLDS`、`KEY_STOCKS`、`HEAT_HOT`/`HEAT_COLD` |
| 百分位窗口（3年/1年） | `PERCENTILE_WINDOW_YEARS` |
| FOMC / 财报等事件 | `EVENTS_MANUAL`（按当年实际日程维护） |
| 美股→中国 映射方向 | `CHINA_MAPPING`（早报"今日中国映射"用） |
| 板块代表ETF（资金热度） | `SECTOR_ETF`（早报"资金最热"用，可改/增减） |
| 早/晚 板块对应关系 | `WIND_PAIRS`（晚报"风向验证"用） |
| 宏观事件对A股影响 | `EVENT_IMPACT` / `FOMC_IMPACT`（事件提醒的"↳ 影响"用） |
| 美股/A股休市日（精确） | `US_HOLIDAYS` / `A_H_HOLIDAYS`（周末自动跳过；这里补精确休市日） |

**腾讯代码格式**：美股 `us+代码`（如 `usNVDA`）、港股 `hk+5位`（如 `hk00700`）、
A股 `sh/sz+6位`（如 `sh000001`）、港股指数 `r_hk+代码`（如 `r_hkHSI`）、美股指数 `us+代码`（如 `usDJI`）。

---

## 五、资金面数据源（2026-11-07 已全部校准 ✅）

实时报价（腾讯 `qt.gtimg.cn`）、历史K线与指数日成交额（东方财富 `push2his`）、以及下列资金面接口均已实测可用：

| 项目 | 数据源 | 关键字段 |
|---|---|---|
| 南向净买入 | datacenter `RPT_MUTUAL_DEAL_HISTORY`，`MUTUAL_TYPE=002/004`（港股通沪/深） | `NET_DEAL_AMT`（百万港元 → 亿港元，两通道相加） |
| 行业ETF份额 / 成交额 | `push2.eastmoney.com/api/qt/stock/get` | `f84` 份额(份)、`f48` 成交额(元)、`f170` 涨跌幅(×100) |
| 两融余额 | datacenter `RPTA_RZRQ_LSHJ`，排序列 `DIM_DATE` | `RZRQYE`（元 → 亿元） |
| A股当日总成交额 | `push2his` 日K `f57`，`1.000001` + `0.399001` 逐日相加 | 与 9 只ETF日成交额、南向、两融一起缓存进 `data/capital_history.json` |

**历史坑（勿回退）**：`kamt` 里的 `data.hkgt.netBuy`、`clist?fs=b:代码` 的 `f106`、报表 `RPTA_WEB_RZRQ_GMRQZ`
三处均已失效或根本不存在，是此前晚报资金面整排「—」的原因；「腾讯/美团 南向净买卖」原本更是一个只返回 `None` 的
空占位函数（东财免费接口只给十大活跃股、不给逐只净买卖），已移除该两行。

> 北向实时净流向 2024-08 已停用，报告只显示南向。
> 资金面 3 年分位＝**排名口径**（`percentile.capital_rank_stats`）；个股/板块的价格分位仍是**区间位置口径**（`pct_of_price`），两者不要混用。
> 历史序列来源：南向 `RPT_MUTUAL_DEAL_HISTORY`、两融 `RPTA_RZRQ_LSHJ` 均按 `pageSize=500` 分页拉近 3 年；
> ETF/指数成交额走 `push2his` 日K `f57`。缓存 `fetch_capital_history()` 每天刷新一次，单项失败沿用旧值。
> 指数代码备注：`usIXIC`（纳斯达克综合）与 `usTCEHY`（腾讯ADR，OTC）无可用历史K线，分位显示「—」属正常。

---

## 六、休市日处理
- **早报（美股）**：北京时间**周六早上照发**——此时美东周五刚收盘数小时（冬令时≈北京周六 05:00），数据新鲜，正好推送「周五晚上的美股」；**周日才静默跳过**（最近仍是上周五、已隔两日且属周末）。北京工作日正常发，若最近一个美股交易日恰逢美股假期则回退到再上一个交易日（如感恩节次日周五仍报上周三收盘）。
- **晚报（A股/港股）**：周六、周日都静默跳过（A/H 周末无交易）。
- 精确休市日在 `config.py` 的 `US_HOLIDAYS`（美股）与 `A_H_HOLIDAYS`（A股/港股）逐年补充（已内置 2026 全年 + 2027 待补）。
- A股/港股休市日与周日，早报/晚报**直接结束、不发任何消息、也不写数据**（不再发占位提醒）。月报 / 半年报 / 年报**不受休市影响，照常发送**。
- 中国大陆有「调休」：若某周六/周日其实是交易日，把那天加进 `TRADING_DAY_OVERRIDE` 即可照常推送。
- ⚠️ `US_HOLIDAYS` / `A_H_HOLIDAYS` **每年 12 月左右需按交易所新公告更新**，否则次年节假日会照常推送（可能显示一、两天前的陈旧数据）。

## 七、数据如何保存
- 每次运行把当日快照追加写入 `data/daily_YYYY.json`，history 增量补进 `data/history.json`，
  晚报再把近 3 年资金面日频序列刷新进 `data/capital_history.json`；
- workflow 末尾自动 `git commit + push` 回仓库（需要 `permissions: contents: write`，已配置）；
- 这样历史分位、月度/年度汇总都有据可查，**完全自包含、可复现**。

## 八、运行命令速查
```bash
python src/main.py --mode morning      # 早报
python src/main.py --mode evening      # 晚报
python src/main.py --mode monthly      # 月报（自动取上月）
python src/main.py --mode semiannual   # 半年报
python src/main.py --mode annual       # 年报
python src/main.py --mode init         # 初始化/增量更新 3 年历史
python src/main.py --mode test         # 推送链路测试
python tests/test_percentile.py        # 本地自测（百分位算法）
python tests/test_report.py            # 本地自测（早/晚报渲染 + 风向验证）
```

## 九、已知限制 / 后续可扩展
- 资金面四个东方财富接口已于 2026-11-07 全部校准可用；免费接口字段可能随版本变动，代码已做降级（显示「—」不中断推送）。
- 金龙指数(HXC)、腾讯ADR(TCEHY) 等个别标的若行情源无数据会显示「—」。
- 两融余额由官方披露，天然滞后一个交易日；南向净买入为港股通沪+深两通道合计。
- 百分位默认前复权口径；如需后复权，改 `fetcher.fetch_history_em` 里 kline 请求的 `fqt=1`→`fqt=2`。
- 可扩展：加入更多板块、把「板块冷热」做成趋势图。
