#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import mimetypes
import os
import subprocess
import sys
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote


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
        if self.path not in {"/api/analyze", "/api/funds/save", "/api/funds/delete"}:
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
