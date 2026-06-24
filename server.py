#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import html
import json
import mimetypes
import os
import re
import subprocess
import sys
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

import requests


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DATA_DIR = ROOT / "data"
FUNDS_FILE = DATA_DIR / "funds.json"
SKILL_SCRIPT = ROOT / "scripts" / "fund_trade_decision.py"


def load_skill_module():
    spec = importlib.util.spec_from_file_location("fund_trade_decision_dashboard", SKILL_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load fund decision script")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def optional_float(data: dict, key: str) -> float | None:
    value = data.get(key)
    if value in (None, ""):
        return None
    return float(value)


def add_arg(args: list[str], flag: str, value) -> None:
    if value not in (None, ""):
        args.extend([flag, str(value)])


def read_saved_funds() -> dict:
    if not FUNDS_FILE.exists():
        return {}
    with FUNDS_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return data if isinstance(data, dict) else {}


def save_fund_record(payload: dict) -> dict:
    fund_code = str(payload.get("fundCode", "")).strip()
    if not fund_code:
        raise ValueError("Fund code is required")

    record_keys = [
        "fundCode",
        "fundName",
        "holdingValue",
        "costNav",
        "lastNav",
        "returnRatePct",
        "navSignalPct",
    ]
    record = {key: "" if payload.get(key) is None else str(payload.get(key)) for key in record_keys}
    record["fundCode"] = fund_code

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    funds = read_saved_funds()
    funds[fund_code] = record
    tmp = FUNDS_FILE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as file:
        json.dump(funds, file, ensure_ascii=False, indent=2)
        file.write("\n")
    tmp.replace(FUNDS_FILE)
    return record


def delete_fund_record(payload: dict) -> dict:
    fund_code = str(payload.get("fundCode", "")).strip()
    if not fund_code:
        raise ValueError("Fund code is required")
    funds = read_saved_funds()
    funds.pop(fund_code, None)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = FUNDS_FILE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as file:
        json.dump(funds, file, ensure_ascii=False, indent=2)
        file.write("\n")
    tmp.replace(FUNDS_FILE)
    return {"fundCode": fund_code}


def run_decision(payload: dict) -> dict:
    fund_code = str(payload.get("fundCode", "")).strip()
    if not fund_code:
        raise ValueError("基金代码不能为空")

    args = [
        sys.executable,
        str(SKILL_SCRIPT),
        "--mode",
        str(payload.get("mode") or "auto"),
        "--fund-code",
        fund_code,
        "--holding-value",
        str(float(payload.get("holdingValue") or 0)),
        "--json",
    ]
    add_arg(args, "--fund-name", payload.get("fundName"))
    add_arg(args, "--cost-nav", payload.get("costNav"))
    add_arg(args, "--last-nav", payload.get("lastNav"))
    add_arg(args, "--return-rate-pct", payload.get("returnRatePct"))
    add_arg(args, "--nav-signal-pct", payload.get("navSignalPct"))
    add_arg(args, "--first-trigger-pct", payload.get("firstTriggerPct"))
    add_arg(args, "--max-buy-ratio", payload.get("maxBuyRatio"))
    add_arg(args, "--max-sell-ratio", payload.get("maxSellRatio"))
    if payload.get("ignoreTimeGate", True):
        args.append("--ignore-time-gate")

    proc = subprocess.run(
        args,
        cwd=str(ROOT),
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=45,
    )
    text = proc.stdout.strip() or proc.stderr.strip()
    try:
        decision = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(text or str(exc)) from exc
    if proc.returncode not in (0, 3):
        raise RuntimeError(decision.get("reason") or decision.get("action") or text)
    return decision


def fetch_driver_details(payload: dict) -> dict:
    fund_code = str(payload.get("fundCode", "")).strip()
    if not fund_code:
        return {"holdings": []}
    try:
        module = load_skill_module()
        last_nav = optional_float(payload, "lastNav")
        model = module.estimate_from_holdings(fund_code, last_nav, 20, None)
        if model is None:
            return {"holdings": []}
        rows = []
        for holding in model.holdings:
            item = asdict(holding)
            item["theme"] = module.infer_theme(holding.name)
            rows.append(item)
        rows.sort(key=lambda item: abs(item.get("contribution_pct") or 0), reverse=True)
        return {
            "holdings": rows,
            "reportDate": model.report_date,
            "quarter": model.quarter,
            "coveragePct": model.coverage_pct,
            "matchedWeightPct": model.matched_weight_pct,
        }
    except Exception as exc:
        return {"holdings": [], "detailsError": str(exc)}


def clean_text(value: object) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", "", str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def fetch_market_indices() -> list[dict]:
    secids = "1.000001,0.399001,0.399006"
    url = (
        "https://push2.eastmoney.com/api/qt/ulist.np/get"
        "?fltt=2&fields=f3,f4,f12,f14,f124&secids=" + secids
    )
    rows = []
    try:
        resp = requests.get(
            url,
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
        )
        resp.raise_for_status()
        for row in (resp.json().get("data", {}) or {}).get("diff", []) or []:
            rows.append(
                {
                    "code": row.get("f12"),
                    "name": row.get("f14"),
                    "pct": row.get("f3"),
                    "change": row.get("f4"),
                }
            )
    except Exception:
        rows = []
    if rows:
        return rows
    try:
        resp = requests.get(
            "https://hq.sinajs.cn/list=s_sh000001,s_sz399001,s_sz399006",
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"},
        )
        resp.raise_for_status()
        resp.encoding = "gb18030"
        names = {"sh000001": "上证指数", "sz399001": "深证成指", "sz399006": "创业板指"}
        for match in re.finditer(r"var hq_str_s_(s[hz]\d{6})=\"([^\"]*)\";", resp.text):
            code = match.group(1)
            fields = match.group(2).split(",")
            if len(fields) >= 4:
                rows.append({"code": code, "name": fields[0] or names.get(code, code), "pct": float(fields[3]), "change": float(fields[2])})
    except Exception:
        return []
    return rows


def yahoo_chart_pct(symbol: str) -> dict | None:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"
    try:
        resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        result = (resp.json().get("chart", {}) or {}).get("result", []) or []
        if not result:
            return None
        meta = result[0].get("meta", {}) or {}
        price = meta.get("regularMarketPrice")
        prev = meta.get("previousClose")
        if not price or not prev:
            closes = [x for x in (result[0].get("indicators", {}).get("quote", [{}])[0].get("close", []) or []) if x]
            if len(closes) >= 2:
                prev, price = closes[-2], closes[-1]
        if not price or not prev:
            return None
        pct = (float(price) - float(prev)) / float(prev) * 100
        return {"symbol": symbol, "pct": pct, "price": price}
    except Exception:
        return None


def theme_keywords(holdings: list[dict]) -> list[str]:
    themes: list[str] = []
    for item in holdings:
        theme = str(item.get("theme") or "")
        if theme and theme not in themes:
            themes.append(theme)
    return themes[:4]


def fetch_us_proxies(themes: list[str]) -> list[dict]:
    mapping = {
        "半导体/存储": ["^IXIC", "SMH", "NVDA"],
        "AI算力/光模块": ["^IXIC", "NVDA", "AVGO"],
        "消费电子/AI硬件": ["^IXIC", "AAPL", "NVDA"],
        "有色金属/铜金": ["GLD", "FCX"],
        "化工": ["DOW"],
        "新能源": ["TSLA", "LIT"],
    }
    symbols: list[str] = ["^IXIC", "^GSPC"]
    for theme in themes:
        for symbol in mapping.get(theme, []):
            if symbol not in symbols:
                symbols.append(symbol)
    rows = []
    for symbol in symbols[:6]:
        item = yahoo_chart_pct(symbol)
        if item:
            rows.append(item)
    return rows


def collect_search_items(node: object, rows: list[dict]) -> None:
    if isinstance(node, dict):
        title = node.get("title") or node.get("Title") or node.get("name") or node.get("Name")
        url = node.get("url") or node.get("Url") or node.get("articleUrl") or node.get("ArticleUrl")
        summary = node.get("content") or node.get("summary") or node.get("digest") or node.get("desc")
        date = node.get("date") or node.get("showTime") or node.get("publishTime") or node.get("time")
        if title and len(rows) < 8:
            rows.append(
                {
                    "title": clean_text(title),
                    "summary": clean_text(summary),
                    "date": clean_text(date),
                    "url": str(url or ""),
                }
            )
        for value in node.values():
            collect_search_items(value, rows)
    elif isinstance(node, list):
        for value in node:
            collect_search_items(value, rows)


def fetch_recent_news(keywords: list[str]) -> list[dict]:
    rows: list[dict] = []
    for keyword in keywords:
        param = {
            "uid": "",
            "keyword": keyword,
            "type": ["cmsTopicWebHome", "gubaArticleWebHome", "baikeWeb"],
            "client": "web",
            "clientVersion": "curr",
            "clientType": "web",
            "param": {
                "cmsTopicWebHome": {"pageSize": 3, "pageIndex": 1, "postTag": "", "preTag": ""},
                "gubaArticleWebHome": {"pageSize": 2, "pageIndex": 1, "postTag": "", "preTag": ""},
                "baikeWeb": {"pageSize": 1, "pageIndex": 1, "postTag": "", "preTag": ""},
            },
        }
        try:
            resp = requests.get(
                "https://search-api-web.eastmoney.com/search/jsonp",
                params={"param": json.dumps(param, ensure_ascii=False)},
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://so.eastmoney.com/"},
                timeout=8,
            )
            resp.raise_for_status()
            text = resp.text.strip()
            body = text[text.find("(") + 1 : text.rfind(")")] if "(" in text and ")" in text else text
            collect_search_items(json.loads(body), rows)
        except Exception:
            continue
        if len(rows) >= 6:
            break
    deduped = []
    seen = set()
    for row in rows:
        key = row["title"]
        if key and key not in seen:
            seen.add(key)
            deduped.append(row)
    return deduped[:6]


def average_pct(rows: list[dict]) -> float | None:
    values = [float(item["pct"]) for item in rows if item.get("pct") is not None]
    return sum(values) / len(values) if values else None


def purchase_verdict(estimated_daily: float | None, market_avg: float | None, us_avg: float | None, confidence: str, themes: list[str]) -> tuple[str, int, str, str]:
    score = 50
    reasons = []
    if estimated_daily is not None:
        if estimated_daily >= 1.2:
            score += 18
            reasons.append("重仓股当日表现偏强")
        elif estimated_daily >= 0.2:
            score += 8
            reasons.append("重仓股小幅偏强")
        elif estimated_daily <= -1.2:
            score -= 18
            reasons.append("重仓股当日明显承压")
        elif estimated_daily <= -0.2:
            score -= 8
            reasons.append("重仓股小幅偏弱")
    if market_avg is not None:
        if market_avg >= 0.6:
            score += 8
            reasons.append("A股大盘偏强")
        elif market_avg <= -0.6:
            score -= 8
            reasons.append("A股大盘偏弱")
    if us_avg is not None:
        if us_avg >= 0.7:
            score += 6
            reasons.append("美股相关代理偏强")
        elif us_avg <= -0.7:
            score -= 6
            reasons.append("美股相关代理偏弱")
    if confidence == "high":
        score += 6
    elif confidence == "low":
        score -= 10
    if any(theme in {"半导体/存储", "AI算力/光模块", "消费电子/AI硬件"} for theme in themes):
        long_term = "长期弹性较高，但波动也大，适合分批而不是一次性重仓。"
    elif themes:
        long_term = "长期是否持有取决于行业景气和估值，适合用小仓位观察趋势。"
    else:
        long_term = "主题识别不足，长期持有需要先确认基金实际持仓是否稳定。"
    score = max(0, min(100, score))
    if score >= 68:
        verdict = "可小额购入"
    elif score >= 52:
        verdict = "观察或轻仓试探"
    else:
        verdict = "暂不购入"
    reason = "；".join(reasons) or "有效行情不足，先观察。"
    return verdict, score, reason, long_term


def run_purchase_analysis(payload: dict) -> dict:
    fund_code = str(payload.get("fundCode", "")).strip()
    if not fund_code:
        raise ValueError("基金代码不能为空")
    module = load_skill_module()
    fund_name = str(payload.get("fundName") or "").strip()
    nav = optional_float(payload, "lastNav")
    platform_estimate = module.get_fund_platform_estimate(fund_code) if hasattr(module, "get_fund_platform_estimate") else None
    if not fund_name or nav is None:
        fund_name = fund_name or (platform_estimate.fund_name if platform_estimate else "")
        nav = nav or (platform_estimate.last_nav if platform_estimate else None)
        if nav is None and platform_estimate:
            nav = platform_estimate.estimated_nav
        nav_date = (platform_estimate.last_nav_date if platform_estimate else "") or (
            platform_estimate.estimated_time if platform_estimate else ""
        )
    else:
        nav_date = ""
    model = module.estimate_from_holdings(fund_code, nav, 20, None)
    if model is None:
        raise RuntimeError("未取到基金披露持仓，无法做购入分析")
    holdings = []
    for holding in model.holdings:
        item = asdict(holding)
        item["theme"] = module.infer_theme(holding.name)
        holdings.append(item)
    holdings.sort(key=lambda item: abs(item.get("contribution_pct") or 0), reverse=True)
    themes = theme_keywords(holdings)
    market = fetch_market_indices()
    us = fetch_us_proxies(themes)
    keywords = [item["name"] for item in holdings[:3]] + themes[:2]
    news = fetch_recent_news(keywords)
    market_avg = average_pct(market)
    us_avg = average_pct(us)
    holdings_daily = model.estimated_fund_pct
    platform_daily = platform_estimate.estimated_fund_pct if platform_estimate else None
    signal_daily = platform_daily if platform_daily is not None else holdings_daily
    signal_source = "fund_platform" if platform_daily is not None else "holdings"
    signal_gap = signal_daily - holdings_daily if signal_daily is not None and holdings_daily is not None else None
    estimated_nav = (
        platform_estimate.estimated_nav
        if platform_estimate and platform_estimate.estimated_nav is not None and signal_source == "fund_platform"
        else model.estimated_nav
    )
    theme_breakdown = module.theme_breakdown(model) if hasattr(module, "theme_breakdown") else []
    data_sources = ["东方财富基金F10披露持仓", "东方财富/新浪实时股票行情"]
    if platform_estimate and platform_estimate.estimated_fund_pct is not None:
        data_sources.insert(0, platform_estimate.source)
    if market:
        data_sources.append("东方财富主要指数行情")
    if us:
        data_sources.append("Yahoo Finance 美股/ETF代理行情")
    if news:
        data_sources.append("东方财富搜索资讯")
    perspectives = [
        {
            "angle": "基金平台估值",
            "signal_pct": platform_daily,
            "confidence": "medium" if platform_daily is not None else "none",
            "source": platform_estimate.source if platform_estimate else "未取到",
            "interpretation": (
                f"平台估值为 {platform_daily:+.2f}%（{platform_estimate.estimated_time or '时间未知'}），作为购入分析主信号。"
                if platform_daily is not None
                else "未取到基金平台估值，本次使用披露持仓估算。"
            ),
        },
        {
            "angle": "披露重仓股贡献",
            "signal_pct": holdings_daily,
            "confidence": model.confidence,
            "source": "基金F10持仓 + 实时个股涨跌",
            "interpretation": f"匹配持仓权重 {model.matched_weight_pct:.2f}% / 披露权重 {model.coverage_pct:.2f}%，估算贡献 {holdings_daily:+.2f}%。",
        },
        {
            "angle": "主题暴露",
            "signal_pct": holdings_daily,
            "confidence": model.confidence,
            "source": "重仓股主题归因",
            "interpretation": "；".join(
                f"{item['theme']}权重{float(item['weight_pct']):.1f}%、贡献{float(item['contribution_pct']):+.2f}%"
                for item in theme_breakdown[:3]
            )
            or "主题识别不足。",
        },
        {
            "angle": "市场环境",
            "signal_pct": market_avg,
            "confidence": "medium" if market else "none",
            "source": "主要A股指数",
            "interpretation": "、".join(f"{item.get('name')} {float(item.get('pct')):+.2f}%" for item in market if item.get("pct") is not None)
            or "未取到主要指数行情。",
        },
        {
            "angle": "美股/外盘代理",
            "signal_pct": us_avg,
            "confidence": "low" if us else "none",
            "source": "Yahoo Finance",
            "interpretation": "、".join(f"{item.get('symbol')} {float(item.get('pct')):+.2f}%" for item in us if item.get("pct") is not None)
            or "未取到相关美股/ETF代理行情。",
        },
        {
            "angle": "汇总信号",
            "signal_pct": signal_daily,
            "confidence": model.confidence,
            "source": signal_source,
            "interpretation": f"购入分析主信号采用 {'基金平台估值' if signal_source == 'fund_platform' else '披露持仓估算'} {signal_daily:+.2f}%。",
        },
    ]
    verdict, score, reason, long_term = purchase_verdict(
        signal_daily,
        market_avg,
        us_avg,
        model.confidence,
        themes,
    )
    return {
        "fundCode": fund_code,
        "fundName": fund_name,
        "lastNav": nav,
        "navDate": nav_date,
        "estimatedDailyPct": signal_daily,
        "estimatedNav": estimated_nav,
        "holdingsEstimatedDailyPct": holdings_daily,
        "platformEstimatedDailyPct": platform_daily,
        "signalSource": signal_source,
        "signalGapPct": signal_gap,
        "confidence": model.confidence,
        "coveragePct": model.coverage_pct,
        "matchedWeightPct": model.matched_weight_pct,
        "reportDate": model.report_date,
        "quarter": model.quarter,
        "themes": themes,
        "holdings": holdings[:10],
        "market": market,
        "usProxies": us,
        "news": news,
        "analysisPerspectives": perspectives,
        "dataSources": list(dict.fromkeys(data_sources)),
        "verdict": verdict,
        "score": score,
        "reason": reason,
        "longTerm": long_term,
        "checkedAt": module.china_now().strftime("%Y-%m-%d %H:%M"),
        "notes": "公开披露持仓可能滞后，新闻只做辅助，不构成投资建议。",
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "FundDashboard/1.0"

    def send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] == "/api/funds":
            self.send_json(200, {"funds": read_saved_funds()})
            return

        raw_path = unquote(self.path.split("?", 1)[0])
        rel = raw_path.lstrip("/") or "index.html"
        target = (STATIC / rel).resolve()
        if not str(target).startswith(str(STATIC.resolve())) or not target.exists() or target.is_dir():
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path not in {"/api/analyze", "/api/purchase-analysis", "/api/funds/save", "/api/funds/delete"}:
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if self.path == "/api/funds/save":
                record = save_fund_record(payload)
                self.send_json(200, {"record": record, "funds": read_saved_funds()})
            elif self.path == "/api/funds/delete":
                record = delete_fund_record(payload)
                self.send_json(200, {"record": record, "funds": read_saved_funds()})
            elif self.path == "/api/purchase-analysis":
                self.send_json(200, {"analysis": run_purchase_analysis(payload)})
            else:
                decision = run_decision(payload)
                details = fetch_driver_details(payload)
                self.send_json(200, {"decision": decision, "details": details})
        except Exception as exc:
            self.send_json(400, {"error": str(exc)})

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Fund dashboard: http://127.0.0.1:{port}")
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
