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

import json
import sys
from contextlib import redirect_stdout


def main() -> int:
    # Capture the real stdout up front. Everything risky runs with stdout swapped
    # to stderr; ONLY the final JSON line is written to this saved handle, so the
    # result no longer has to "happen to be the last stdout line".
    real_stdout = sys.stdout

    raw = sys.stdin.read()
    try:
        req = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 - report any parse failure as JSON
        real_stdout.write(
            json.dumps({"ok": False, "ticker": None, "error": f"bad input json: {exc}"})
        )
        return 0

    ticker = req.get("ticker")
    trade_date = req.get("trade_date")
    asset_type = req.get("asset_type", "stock")
    # Allowlist the overrides (defense in depth; the adapter filters too). Never let
    # caller-supplied keys redirect paths/urls inside the TradingAgents process.
    _allowed = {"deep_think_llm", "quick_think_llm", "max_debate_rounds", "online_tools"}
    overrides = {k: v for k, v in (req.get("config_overrides") or {}).items() if k in _allowed}

    try:
        # Swap stdout to stderr for the ENTIRE risky region — the imports (which may
        # print banners at module-load time), graph construction, and propagate — so
        # no library chatter can ever reach real stdout. The result dict is built here
        # too, then written to the saved real stdout outside the swap.
        with redirect_stdout(sys.stderr):
            from tradingagents.default_config import DEFAULT_CONFIG
            from tradingagents.graph.trading_graph import TradingAgentsGraph

            config = {**DEFAULT_CONFIG, **overrides}
            graph = TradingAgentsGraph(debug=False, config=config)
            final_state, decision = graph.propagate(ticker, trade_date, asset_type)

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
        real_stdout.write(json.dumps(result))
    except Exception as exc:  # noqa: BLE001 - any failure becomes a degraded JSON result
        import traceback

        real_stdout.write(
            json.dumps(
                {
                    "ok": False,
                    "ticker": ticker,
                    "error": str(exc),
                    "trace": traceback.format_exc()[-1500:],
                }
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
