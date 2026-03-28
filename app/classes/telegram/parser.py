import re


def parse_signal(text: str):
    if "Новый сигнал" not in text and "Новий сигнал" not in text:
        return None

    symbol_match = re.search(r'([A-Z0-9]+USDT)\s+(LONG|SHORT)', text)
    entry_match = re.search(r'(?:Вход|Вхід):\s*([\d\.]+)', text)
    sl_match = re.search(r'(?:SL|Стоп):\s*([\d\.]+)', text)
    tp_matches = re.findall(r'(?:TP\d+|Тейк\s*\d+):\s*([\d\.]+)', text)
    risk_match = re.search(r'(\d+(?:\.\d+)?)%', text)

    if not symbol_match or not entry_match or not sl_match or not tp_matches:
        return None

    symbol = symbol_match.group(1)
    side = symbol_match.group(2)
    entry = float(entry_match.group(1))
    sl = float(sl_match.group(1))
    tps = [float(tp) for tp in tp_matches]
    risk = float(risk_match.group(1)) / 100 if risk_match else 0.01

    return {
        "symbol": symbol,
        "side": side,
        "entry": entry,
        "sl": sl,
        "tps": tps,
        "risk": risk
    }


def parse_tp_hit(text: str):
    lowered = text.lower()

    be_patterns = [
        r"\bбезубыт",
        r"\bбеззбит",
        r"\bbreakeven\b",
        r"\bbe\b",
        r"\bб/у\b",
        r"\bбу\b",
        r"стоп.*б/у",
        r"стоп.*бу",
        r"sl.*б/у",
        r"sl.*бу",
    ]
    move_to_be = any(re.search(pattern, lowered) for pattern in be_patterns)

    if (
        "тейк-профит" not in lowered
        and "тейк профит" not in lowered
        and "тейк-профіт" not in lowered
        and "тейк профіт" not in lowered
        and "тейк" not in lowered
        and "tp" not in lowered
        and not move_to_be
    ):
        return None

    symbol_match = re.search(r'([A-Z0-9]+USDT)\s+(LONG|SHORT)', text)
    tp_match = re.search(r'(?:TP|Тейк)\s*(\d+)', text, re.IGNORECASE)
    be = move_to_be

    if not tp_match and not be:
        return None

    tp_index = int(tp_match.group(1)) - 1 if tp_match else None
    if tp_index is None and be:
        # In ua_plain replies "Переставити стоп в беззбиток" is emitted on TP2.
        tp_index = 1

    return {
        "symbol": symbol_match.group(1) if symbol_match else None,
        "tp_index": tp_index,
        "move_to_be": be
    }


def parse_trade_result(text: str):
    lowered = text.lower()

    if "результат сделки" not in lowered and "результат угоди" not in lowered:
        return None

    symbol_match = re.search(r'([A-Z0-9]+USDT)\s+(LONG|SHORT)', text)
    exit_match = re.search(r'(?:Цена закрытия|Ціна закриття):\s*([\d\.]+)', text)
    tp_summary_match = re.search(r'(?:взято|узято)\s*TP:\s*(\d+)\s*/\s*(\d+)', text, re.IGNORECASE)

    if not symbol_match or not exit_match:
        return None

    if (
        "тейк-профиту" in lowered
        or "тейк-профіту" in lowered
        or "закрито по тейку" in lowered
    ):
        result_type = "tp"
    elif (
        "стоп-приказ" in lowered
        or "стоп-наказ" in lowered
        or "sl" == lowered.strip().splitlines()[0].strip().lower()
    ):
        result_type = "sl"
    elif "безубыт" in lowered or "беззбит" in lowered or lowered.strip().splitlines()[0].strip().lower() == "be":
        result_type = "be"
    else:
        result_type = "result"

    return {
        "symbol": symbol_match.group(1),
        "side": symbol_match.group(2),
        "exit_price": float(exit_match.group(1)),
        "result_type": result_type,
        "tp_hits": int(tp_summary_match.group(1)) if tp_summary_match else None,
        "tp_total": int(tp_summary_match.group(2)) if tp_summary_match else None,
    }


def classify_message(text: str):
    signal = parse_signal(text)
    if signal:
        return {
            "type": "signal",
            "payload": signal
        }

    tp_event = parse_tp_hit(text)
    if tp_event:
        return {
            "type": "tp_event",
            "payload": tp_event
        }

    result_event = parse_trade_result(text)
    if result_event:
        return {
            "type": "result_event",
            "payload": result_event
        }

    return {
        "type": "ignored",
        "payload": None
    }
