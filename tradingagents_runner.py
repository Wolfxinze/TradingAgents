"""Process-isolated JSON wrapper around TradingAgents' debate graph.

This is the ai-hedge-fund ⇄ TradingAgents seam. ai-hedge-fund pins langgraph 0.2
while TradingAgents needs 0.4+, so they cannot share an interpreter; ai-hedge-fund
shells into THIS file via `uv run --project <TradingAgent>` and exchanges JSON over
stdin/stdout.

This file is additive (no TradingAgents source is modified → no Apache-2.0 §4(b)
"changed file" obligation). It is intentionally dependency-free beyond TradingAgents.

Protocol:
  stdin  : {"ticker": "...", "trade_date": "YYYY-MM-DD", "asset_type": "stock",
            "config_overrides": {...}}
  stdout : exactly one JSON line — {"ok": true, "ticker", "decision", "reports"}
           or {"ok": false, "ticker", "error"}.  All graph chatter is redirected
           to stderr so stdout carries only the result line.
"""

import io
import json
import sys
from contextlib import redirect_stdout


def main() -> int:
    raw = sys.stdin.read()
    try:
        req = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 - report any parse failure as JSON
        sys.stdout.write(json.dumps({"ok": False, "error": f"bad input json: {exc}"}))
        return 0

    ticker = req.get("ticker")
    trade_date = req.get("trade_date")
    asset_type = req.get("asset_type", "stock")
    overrides = req.get("config_overrides") or {}

    try:
        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        config = {**DEFAULT_CONFIG, **overrides}
        # Redirect any print/rich output the graph emits to stderr so stdout stays clean.
        sink = io.StringIO()
        with redirect_stdout(sys.stderr):
            graph = TradingAgentsGraph(debug=False, config=config)
            final_state, decision = graph.propagate(ticker, trade_date, asset_type)
        _ = sink  # reserved; graph output already diverted to stderr

        state = final_state if isinstance(final_state, dict) else {}
        result = {
            "ok": True,
            "ticker": ticker,
            "trade_date": trade_date,
            "decision": str(decision) if decision is not None else None,
            "reports": {
                "market_report": state.get("market_report"),
                "sentiment_report": state.get("sentiment_report"),
                "news_report": state.get("news_report"),
                "fundamentals_report": state.get("fundamentals_report"),
                "final_trade_decision": state.get("final_trade_decision"),
            },
        }
        sys.stdout.write(json.dumps(result))
    except Exception as exc:  # noqa: BLE001 - any failure becomes a degraded JSON result
        import traceback

        sys.stdout.write(
            json.dumps({"ok": False, "ticker": ticker, "error": str(exc), "trace": traceback.format_exc()[-1500:]})
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
