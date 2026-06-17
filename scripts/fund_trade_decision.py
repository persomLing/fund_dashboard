#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fund buy/sell decision from disclosed holdings and intraday stock moves."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
from dataclasses import asdict, dataclass
from typing import Any

import requests


CHINA_TZ = dt.timezone(dt.timedelta(hours=8), name="Asia/Shanghai")
DECISION_TIME = dt.time(14, 50)
PANIC_DRAWDOWN = -30.0


@dataclass
class Holding:
    code: str
    name: str
    weight_pct: float
    stock_pct: float | None = None
    contribution_pct: float | None = None


@dataclass
class HoldingModel:
    fund_code: str
    report_date: str
    quarter: str
    coverage_pct: float
    matched_weight_pct: float
    estimated_fund_pct: float
    estimated_nav: float | None
    confidence: str
    holdings: list[Holding]


@dataclass
class TradeDecision:
    mode: str
    action: str
    amount: float
    ratio_pct: float
    reason: str
    fund_code: str
    fund_name: str
    holding_value: float
    cost_nav: float | None
    last_nav: float | None
    estimated_nav: float | None
    estimated_fund_pct: float | None
    holdings_estimated_fund_pct: float | None
    nav_signal_pct: float | None
    signal_source: str
    signal_gap_pct: float | None
    coverage_pct: float | None
    matched_weight_pct: float | None
    estimated_position_return_pct: float
    confidence: str
    driver_reason: str
    checked_at: str


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    for old in ["%", ",", "，", " "]:
        text = text.replace(old, "")
    if text in {"", "-", "--", "None", "null"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def strip_tags(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()


def china_now() -> dt.datetime:
    return dt.datetime.now(tz=CHINA_TZ)


def time_gate_status(now: dt.datetime) -> tuple[bool, str]:
    if now.weekday() >= 5:
        return False, f"今天是周末（北京时间 {now:%Y-%m-%d %H:%M}），不做交易判断。"
    if now.time() < DECISION_TIME:
        return False, f"现在还没到北京时间 14:50（当前 {now:%Y-%m-%d %H:%M}），不做交易判断。"
    market_ok, market_msg = china_market_quote_date_status(now)
    if market_ok is False:
        return False, market_msg
    return True, ""


def china_market_quote_date_status(now: dt.datetime) -> tuple[bool | None, str]:
    """Return False only when live index quotes prove today is not an A-share trading day."""
    url = (
        "https://push2.eastmoney.com/api/qt/ulist.np/get"
        "?fltt=2&fields=f12,f14,f124&secids=1.000001,0.399001"
    )
    try:
        resp = requests.get(
            url,
            timeout=6,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
        )
        resp.raise_for_status()
        rows = (resp.json().get("data", {}) or {}).get("diff", []) or []
    except Exception:
        return None, "无法确认指数行情日期，按工作日继续。"

    quote_dates: list[dt.date] = []
    for row in rows:
        ts = to_float(row.get("f124"))
        if not ts:
            continue
        if ts > 100_000_000_000:
            ts = ts / 1000
        quote_dates.append(dt.datetime.fromtimestamp(ts, tz=CHINA_TZ).date())

    if not quote_dates:
        return None, "指数行情没有返回更新时间，按工作日继续。"
    if now.date() in quote_dates:
        return True, ""
    latest = max(quote_dates)
    return False, f"今天不像 A 股交易日：指数行情最新日期是 {latest:%Y-%m-%d}，当前是 {now:%Y-%m-%d}。"


def eastmoney_secid(code: str) -> str | None:
    code = code.strip()
    if not re.fullmatch(r"\d{6}", code):
        return None
    return ("1." if code.startswith(("5", "6", "9")) else "0.") + code


def sina_symbol(code: str) -> str | None:
    code = code.strip()
    if not re.fullmatch(r"\d{6}", code):
        return None
    return ("sh" if code.startswith(("5", "6", "9")) else "sz") + code


def get_latest_fund_nav(fund_code: str) -> tuple[str, float | None, str]:
    url = f"https://fundgz.1234567.com.cn/js/{fund_code}.js"
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://fund.eastmoney.com/"},
            timeout=8,
        )
        resp.raise_for_status()
        match = re.search(r"\{.*\}", resp.text)
        if not match:
            return "", None, ""
        data = json.loads(match.group(0))
        name = str(data.get("name") or "")
        nav = to_float(data.get("dwjz")) or to_float(data.get("gsz"))
        nav_time = str(data.get("jzrq") or data.get("gztime") or "")
        return name, nav, nav_time
    except Exception:
        return "", None, ""


def fetch_stock_quotes(codes: list[str]) -> dict[str, float]:
    result: dict[str, float] = {}
    secids = [secid for code in codes if (secid := eastmoney_secid(code))]
    if secids:
        url = (
            "https://push2.eastmoney.com/api/qt/ulist.np/get"
            "?fltt=2&fields=f3,f12,f14&secids=" + ",".join(secids)
        )
        try:
            resp = requests.get(
                url,
                timeout=8,
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
            )
            resp.raise_for_status()
            rows = (resp.json().get("data", {}) or {}).get("diff", []) or []
            for row in rows:
                code = str(row.get("f12", ""))
                pct = to_float(row.get("f3"))
                if code and pct is not None and -30.0 <= pct <= 30.0:
                    result[code] = pct
        except Exception:
            result = {}

    missing = [code for code in codes if code not in result]
    if missing:
        result.update(fetch_stock_quotes_sina(missing))
    return result


def fetch_stock_quotes_sina(codes: list[str]) -> dict[str, float]:
    symbols = [symbol for code in codes if (symbol := sina_symbol(code))]
    if not symbols:
        return {}
    url = "https://hq.sinajs.cn/list=" + ",".join(symbols)
    try:
        resp = requests.get(
            url,
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"},
        )
        resp.raise_for_status()
        resp.encoding = "gb18030"
    except Exception:
        return {}

    result: dict[str, float] = {}
    for match in re.finditer(r"var hq_str_(s[hz](\d{6}))=\"([^\"]*)\";", resp.text):
        code = match.group(2)
        fields = match.group(3).split(",")
        if len(fields) < 4:
            continue
        prev_close = to_float(fields[2])
        current = to_float(fields[3])
        if prev_close and current and prev_close > 0 and current > 0:
            pct = (current - prev_close) / prev_close * 100
            if -30.0 <= pct <= 30.0:
                result[code] = pct
    return result


def parse_holdings_sections(text: str) -> list[tuple[str, str, list[Holding]]]:
    sections: list[tuple[str, str, list[Holding]]] = []
    pattern = re.compile(
        r"<h4[^>]*>(?P<header>.*?)</h4>.*?<table[^>]*>(?P<table>.*?)</table>",
        re.S,
    )
    for match in pattern.finditer(text):
        header = strip_tags(match.group("header"))
        table = match.group("table")
        report_date_match = re.search(r"截止至：?(\d{4}-\d{2}-\d{2})", header)
        quarter_match = re.search(r"(\d{4}年\d季度股票投资明细)", header)
        report_date = report_date_match.group(1) if report_date_match else ""
        quarter = quarter_match.group(1) if quarter_match else header

        rows: list[Holding] = []
        for row_match in re.finditer(r"<tr[^>]*>(.*?)</tr>", table, re.S):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row_match.group(1), re.S)
            if len(cells) < 7:
                continue
            code = strip_tags(cells[1])
            name = strip_tags(cells[2])
            weight = to_float(strip_tags(cells[6]))
            if re.fullmatch(r"\d{6}", code) and weight is not None:
                rows.append(Holding(code=code, name=name, weight_pct=weight))
        if rows:
            sections.append((report_date, quarter, rows))
    return sections


def fetch_fund_holdings(fund_code: str, limit: int = 20, year: int | None = None) -> tuple[str, str, list[Holding]]:
    years = [year] if year else [china_now().year, china_now().year - 1]
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://fundf10.eastmoney.com/"}
    for y in years:
        url = (
            "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
            f"?type=jjcc&code={fund_code}&topline={limit}&year={y}"
        )
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
        except Exception:
            continue
        sections = parse_holdings_sections(resp.text)
        if sections:
            sections.sort(key=lambda item: item[0] or "0000-00-00", reverse=True)
            report_date, quarter, holdings = sections[0]
            return report_date, quarter, holdings[:limit]
    return "", "", []


def estimate_from_holdings(fund_code: str, last_nav: float | None, limit: int, year: int | None) -> HoldingModel | None:
    report_date, quarter, holdings = fetch_fund_holdings(fund_code, limit=limit, year=year)
    if not holdings:
        return None
    quotes = fetch_stock_quotes([h.code for h in holdings])
    estimated_fund_pct = 0.0
    matched_weight = 0.0
    for h in holdings:
        pct = quotes.get(h.code)
        h.stock_pct = pct
        if pct is not None:
            h.contribution_pct = h.weight_pct * pct / 100
            estimated_fund_pct += h.contribution_pct
            matched_weight += h.weight_pct

    coverage = sum(h.weight_pct for h in holdings)
    matched_ratio = matched_weight / coverage if coverage else 0
    if coverage >= 55 and matched_ratio >= 0.8:
        confidence = "high"
    elif coverage >= 35 and matched_ratio >= 0.7:
        confidence = "medium"
    else:
        confidence = "low"

    estimated_nav = last_nav * (1 + estimated_fund_pct / 100) if last_nav else None
    return HoldingModel(
        fund_code=fund_code,
        report_date=report_date,
        quarter=quarter,
        coverage_pct=coverage,
        matched_weight_pct=matched_weight,
        estimated_fund_pct=estimated_fund_pct,
        estimated_nav=estimated_nav,
        confidence=confidence,
        holdings=holdings,
    )


def infer_theme(name: str) -> str:
    rules = [
        ("AI算力/光模块", ["中际旭创", "新易盛", "亨通光电", "天孚通信", "光迅科技", "源杰科技"]),
        ("半导体/存储", ["兆易创新", "江波龙", "德明利", "普冉股份", "佰维存储", "香农芯创", "朗科科技", "精智达", "海光信息", "寒武纪", "北方华创", "中微公司", "澜起科技", "芯源微", "芯碁微装"]),
        ("有色金属/铜金", ["紫金矿业", "洛阳钼业", "山东黄金", "西部矿业", "铜陵有色"]),
        ("化工", ["万华化学", "华鲁恒升", "江山股份", "扬农化工"]),
        ("新能源", ["宁德时代", "亿纬锂能", "阳光电源", "隆基绿能"]),
        ("消费电子/AI硬件", ["立讯精密", "工业富联", "歌尔股份", "沪电股份"]),
    ]
    for theme, keywords in rules:
        if any(keyword in name for keyword in keywords):
            return theme
    return "个股因素"


def stock_driver(h: Holding) -> str:
    pct = h.stock_pct if h.stock_pct is not None else 0.0
    contrib = h.contribution_pct if h.contribution_pct is not None else 0.0
    return f"{h.name}{pct:+.2f}%（贡献{contrib:+.2f}%）"


def driver_reason(model: HoldingModel | None) -> str:
    if model is None:
        return "未取到披露持仓，无法解释重仓股驱动。"
    rows = [h for h in model.holdings if h.contribution_pct is not None]
    if not rows:
        return "未取到重仓股有效行情，无法解释重仓股驱动。"
    positives = sorted([h for h in rows if (h.contribution_pct or 0) > 0], key=lambda h: h.contribution_pct or 0, reverse=True)
    negatives = sorted([h for h in rows if (h.contribution_pct or 0) < 0], key=lambda h: h.contribution_pct or 0)
    pos = "、".join(stock_driver(h) for h in positives[:3]) or "无明显拉动项"
    neg = "、".join(stock_driver(h) for h in negatives[:3]) or "无明显拖累项"
    pos_themes = "、".join(dict.fromkeys(infer_theme(h.name) for h in positives[:5])) or "无明显主题"
    neg_themes = "、".join(dict.fromkeys(infer_theme(h.name) for h in negatives[:5])) or "无明显主题"
    if model.estimated_fund_pct >= 0.5:
        return f"披露重仓股整体偏强，估算净值约{model.estimated_fund_pct:+.2f}%。主要拉动：{pos}。主要拖累：{neg}。偏强方向：{pos_themes}。"
    if model.estimated_fund_pct <= -0.5:
        return f"披露重仓股整体偏弱，估算净值约{model.estimated_fund_pct:+.2f}%。主要拖累：{neg}。主要对冲：{pos}。受压方向：{neg_themes}。"
    return f"披露重仓股分化，估算净值约{model.estimated_fund_pct:+.2f}%。拉动：{pos}。拖累：{neg}。"


def projected_return_pct(return_rate_pct: float | None, cost_nav: float | None, estimated_nav: float | None) -> float:
    if cost_nav and estimated_nav and cost_nav > 0:
        return (estimated_nav / cost_nav - 1) * 100
    if return_rate_pct is not None:
        return return_rate_pct
    raise ValueError("need cost_nav and estimated_nav, or return_rate_pct")


def buy_ratio(position_return_pct: float, daily_pct: float, confidence: str, first_trigger_pct: float, max_ratio: float) -> tuple[float, str]:
    trigger = -abs(first_trigger_pct)
    if position_return_pct > trigger:
        return 0.0, f"预估回撤未达到 -{first_trigger_pct:g}% 触发线"
    if position_return_pct <= PANIC_DRAWDOWN:
        return 0.0, "回撤超过 -30%，停止机械补仓，先复盘基金逻辑"
    if position_return_pct <= -18:
        base = 6
    elif position_return_pct <= -12:
        base = 5
    elif position_return_pct <= -8:
        base = 4
    else:
        base = 3
    boost = 0
    if confidence in {"medium", "high"}:
        if daily_pct <= -3:
            boost = 3
        elif daily_pct <= -2:
            boost = 2
        elif daily_pct <= -1:
            boost = 1
    if confidence == "medium":
        boost = min(boost, 2)
    ratio = min(base + boost, max_ratio)
    return ratio, f"进入补仓档位，基础{base}% + 今日大跌放大{boost}%"


def sell_ratio(position_return_pct: float, daily_pct: float, confidence: str, max_ratio: float) -> tuple[float, str]:
    if confidence == "low":
        return 0.0, "持仓估算置信度低，不做卖出判断"

    if position_return_pct < 0:
        if daily_pct >= 5:
            return min(5.0, max_ratio), "仍未回本但今日大涨，可少量减仓降风险"
        return 0.0, "仍未回本，除非基金逻辑变坏，否则不因反弹卖出"

    if daily_pct >= 6:
        return min(20.0, max_ratio), "今日估算大涨，适合较大比例止盈"
    if daily_pct >= 4:
        return min(15.0, max_ratio), "今日估算明显上涨，适合分批止盈"
    if daily_pct >= 2 and position_return_pct >= 3:
        return min(10.0, max_ratio), "已有盈利且今日涨幅较大，可小幅止盈"
    if position_return_pct >= 8:
        return min(10.0, max_ratio), "持仓盈利较高，可做纪律性止盈"
    return 0.0, "涨幅或盈利不足，不卖"


def choose_daily_signal(model: HoldingModel | None, nav_signal_pct: float | None) -> tuple[float, str, float | None, str]:
    holdings_pct = model.estimated_fund_pct if model else None
    if nav_signal_pct is None:
        return holdings_pct or 0.0, "holdings", None, model.confidence if model else "none"
    signal_gap = nav_signal_pct - holdings_pct if holdings_pct is not None else None
    confidence = model.confidence if model else "medium"
    if confidence in {"none", "low"}:
        confidence = "medium"
    return nav_signal_pct, "nav_signal", signal_gap, confidence


def make_decision(
    mode: str,
    fund_code: str,
    fund_name: str,
    holding_value: float,
    cost_nav: float | None,
    last_nav: float | None,
    return_rate_pct: float | None,
    model: HoldingModel | None,
    nav_signal_pct: float | None,
    first_trigger_pct: float,
    max_buy_ratio: float,
    max_sell_ratio: float,
) -> TradeDecision:
    daily_pct, signal_source, signal_gap, confidence = choose_daily_signal(model, nav_signal_pct)
    if signal_source == "nav_signal" and last_nav:
        estimated_nav = last_nav * (1 + daily_pct / 100)
    else:
        estimated_nav = model.estimated_nav if model else last_nav
    position_return = projected_return_pct(return_rate_pct, cost_nav, estimated_nav)
    if mode == "buy":
        ratio, reason = buy_ratio(position_return, daily_pct, confidence, first_trigger_pct, max_buy_ratio)
        action = "不补" if ratio <= 0 else "可补"
    elif mode == "sell":
        ratio, reason = sell_ratio(position_return, daily_pct, confidence, max_sell_ratio)
        action = "不卖" if ratio <= 0 else "可卖/减仓"
    else:
        buy_r, buy_reason = buy_ratio(position_return, daily_pct, confidence, first_trigger_pct, max_buy_ratio)
        sell_r, sell_reason = sell_ratio(position_return, daily_pct, confidence, max_sell_ratio)
        if sell_r > 0:
            mode, ratio, reason, action = "sell", sell_r, sell_reason, "可卖/减仓"
        elif buy_r > 0:
            mode, ratio, reason, action = "buy", buy_r, buy_reason, "可补"
        else:
            mode, ratio, reason, action = "watch", 0.0, f"{buy_reason}；{sell_reason}", "观察"
    amount = holding_value * ratio / 100
    return TradeDecision(
        mode=mode,
        action=action,
        amount=amount,
        ratio_pct=ratio,
        reason=reason,
        fund_code=fund_code,
        fund_name=fund_name,
        holding_value=holding_value,
        cost_nav=cost_nav,
        last_nav=last_nav,
        estimated_nav=estimated_nav,
        estimated_fund_pct=daily_pct if model or nav_signal_pct is not None else None,
        holdings_estimated_fund_pct=model.estimated_fund_pct if model else None,
        nav_signal_pct=nav_signal_pct,
        signal_source=signal_source,
        signal_gap_pct=signal_gap,
        coverage_pct=model.coverage_pct if model else None,
        matched_weight_pct=model.matched_weight_pct if model else None,
        estimated_position_return_pct=position_return,
        confidence=confidence,
        driver_reason=driver_reason(model),
        checked_at=china_now().strftime("%Y-%m-%d %H:%M"),
    )


def print_decision(d: TradeDecision) -> None:
    print(f"模式：{d.mode}")
    print(f"结论：{d.action}")
    print(f"金额：{d.amount:.0f} 元")
    print(f"比例：{d.ratio_pct:.0f}%")
    print(f"原因：{d.reason}")
    print(f"持仓驱动：{d.driver_reason}")
    if d.estimated_fund_pct is not None:
        print(f"预估今日净值变化：{d.estimated_fund_pct:+.2f}%")
    else:
        print("预估今日净值变化：无持仓估算")
    print(f"预估持仓收益率：{d.estimated_position_return_pct:+.2f}%")
    print(f"置信度：{d.confidence}")
    print(f"基金：{d.fund_code} {d.fund_name or '-'}")
    print(f"持有市值：{d.holding_value:.2f} 元")
    if d.cost_nav:
        print(f"成本净值：{d.cost_nav:.4f}")
    if d.last_nav:
        print(f"最近净值：{d.last_nav:.4f}")
    if d.estimated_nav:
        print(f"预估净值：{d.estimated_nav:.4f}")
    print(f"检查时间：{d.checked_at}")
    print("说明：这是规则化估算，不是投资建议；主动基金可能已调仓，最终净值以基金公司公布为准。")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["buy", "sell", "auto"], default="auto")
    parser.add_argument("--fund-code", required=True)
    parser.add_argument("--fund-name", default="")
    parser.add_argument("--holding-value", type=float, required=True)
    parser.add_argument("--cost-nav", type=float)
    parser.add_argument("--last-nav", type=float)
    parser.add_argument("--return-rate-pct", type=float)
    parser.add_argument("--nav-signal-pct", type=float)
    parser.add_argument("--first-trigger-pct", type=float, default=3.5)
    parser.add_argument("--max-buy-ratio", type=float, default=10)
    parser.add_argument("--max-sell-ratio", type=float, default=20)
    parser.add_argument("--holdings-limit", type=int, default=20)
    parser.add_argument("--holdings-year", type=int)
    parser.add_argument("--ignore-time-gate", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.mode in {"buy", "auto"} and args.first_trigger_pct not in {3.5, 4.0, 5.0}:
        print("停止判断：第一档触发线只能选择 5、4 或 3.5。")
        return 2

    now = china_now()
    if not args.ignore_time_gate:
        ok, msg = time_gate_status(now)
        if not ok:
            print(json.dumps({"action": "不分析", "reason": msg}, ensure_ascii=False) if args.json else msg)
            return 3

    fund_name = args.fund_name
    last_nav = args.last_nav
    if not fund_name or last_nav is None:
        fetched_name, fetched_nav, _ = get_latest_fund_nav(args.fund_code)
        fund_name = fund_name or fetched_name
        last_nav = last_nav or fetched_nav

    model = estimate_from_holdings(args.fund_code, last_nav, args.holdings_limit, args.holdings_year)
    if model is None and args.return_rate_pct is None:
        msg = "未取到披露持仓，且未提供持有收益率，无法判断。"
        print(json.dumps({"action": "停止判断", "reason": msg}, ensure_ascii=False) if args.json else msg)
        return 2

    try:
        decision = make_decision(
            mode=args.mode,
            fund_code=args.fund_code,
            fund_name=fund_name,
            holding_value=args.holding_value,
            cost_nav=args.cost_nav,
            last_nav=last_nav,
            return_rate_pct=args.return_rate_pct,
            model=model,
            nav_signal_pct=args.nav_signal_pct,
            first_trigger_pct=args.first_trigger_pct,
            max_buy_ratio=args.max_buy_ratio,
            max_sell_ratio=args.max_sell_ratio,
        )
    except ValueError as exc:
        print(f"停止判断：{exc}")
        return 2

    if args.json:
        print(json.dumps(asdict(decision), ensure_ascii=False, indent=2))
    else:
        print_decision(decision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
