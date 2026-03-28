def _detect_tp_index(tps, price, tolerance):
    for index, tp in enumerate(tps, start=1):
        tp_price = float(tp.get("price", 0) or 0)
        if tp_price and abs(price - tp_price) / tp_price < tolerance:
            return index
    return None


def _is_truthy(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"true", "1", "yes"}
    return bool(value)


def _manual_reason(tp_hits):
    if tp_hits > 0:
        return f"MANUAL_AFTER_TP{tp_hits}"
    return "MANUAL_CLOSE"


def classify_close_reason(trade, exit_price, close_executions=None, tolerance=0.003, close_summary=None):
    try:
        exit_price = float(exit_price)
        entry = float(trade.get("entry", 0) or 0)
        sl_raw = trade.get("sl")
        sl = float(sl_raw) if sl_raw not in (None, "") else 0
        tp_hits = int(trade.get("tp_hits", 0) or 0)
        if close_summary:
            tp_hits = int(close_summary.get("tp_hits", tp_hits) or 0)
        be_moved = bool(trade.get("be_moved", False))
        tps = trade.get("tps", []) or []
        latest_exec = None
        if close_executions:
            latest_exec = sorted(
                close_executions,
                key=lambda item: int(item.get("execTime", 0) or 0),
                reverse=True
            )[0]

        if close_summary:
            stop_exit_qty = float(close_summary.get("stop_exit_qty", 0) or 0)
            manual_exit_qty = float(close_summary.get("manual_exit_qty", 0) or 0)
            reduce_only_exit_qty = float(close_summary.get("reduce_only_exit_qty", 0) or 0)

            if stop_exit_qty > 0:
                if entry and abs(exit_price - entry) / entry < tolerance:
                    if tp_hits > 0:
                        return f"BE_AFTER_TP{tp_hits}"
                    return "BE"

                if tp_hits > 0:
                    return f"SL_AFTER_TP{tp_hits}"
                return "SL"

            if manual_exit_qty > 0:
                return _manual_reason(tp_hits)

            if reduce_only_exit_qty > 0:
                tp_index = _detect_tp_index(tps, exit_price, tolerance)
                if tp_hits > 0 and tp_index and tp_index <= tp_hits:
                    return f"TP{tp_index}"
                if tp_hits > 0:
                    return f"EXIT_AFTER_TP{tp_hits}"
                if tp_index:
                    return f"TP{tp_index}"
                return "TP_EXIT"

        if latest_exec:
            exec_price = float(latest_exec.get("execPrice", exit_price) or exit_price)
            stop_order_type = str(latest_exec.get("stopOrderType", "") or "")
            order_type = str(latest_exec.get("orderType", "") or "")
            exec_type = str(latest_exec.get("execType", "") or "")
            reduce_only = _is_truthy(latest_exec.get("reduceOnly"))
            is_stop_exit = stop_order_type in {"StopLoss", "Stop", "TrailingStop"} or exec_type in {
                "BustTrade",
                "SessionSettlePnL",
                "Settle",
            }

            tp_index = _detect_tp_index(tps, exec_price, tolerance)
            if tp_index:
                return f"TP{tp_index}"

            if is_stop_exit:
                if entry and abs(exec_price - entry) / entry < tolerance:
                    if tp_hits > 0:
                        return f"BE_AFTER_TP{tp_hits}"
                    return "BE"

                if tp_hits > 0:
                    return f"SL_AFTER_TP{tp_hits}"
                return "SL"

            if order_type == "Limit" and reduce_only:
                if tp_hits > 0:
                    return f"EXIT_AFTER_TP{tp_hits}"
                return "TP_EXIT"

            if order_type in {"Market", "Limit"} and not reduce_only:
                return _manual_reason(tp_hits)

        if entry and be_moved and abs(exit_price - entry) / entry < tolerance:
            if tp_hits > 0:
                return f"BE_AFTER_TP{tp_hits}"
            return "BE"

        if sl and abs(exit_price - sl) / sl < tolerance:
            if entry and abs(sl - entry) / entry < tolerance:
                if tp_hits > 0:
                    return f"BE_AFTER_TP{tp_hits}"
                return "BE"

            if tp_hits > 0:
                return f"SL_AFTER_TP{tp_hits}"
            return "SL"

        tp_index = _detect_tp_index(tps, exit_price, tolerance)
        if tp_index:
            return f"TP{tp_index}"

        if tp_hits > 0:
            return f"EXIT_AFTER_TP{tp_hits}"

        return "UNCLASSIFIED"

    except Exception:
        return "UNKNOWN"
