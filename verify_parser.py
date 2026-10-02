"""
Standalone verification of the portfolio parser ONLY.
No Streamlit, no Plotly needed. Just regex parsing and validation.

Usage: python verify_parser.py
"""
import re
import json
import sys
from pathlib import Path

APP_DIR = Path(__file__).parent


# ── Inline _try_num helper (mimics app.py's version) ──────────────────────
def _try_num(v):
    try:
        return float(v.replace(",", "."))
    except (ValueError, TypeError):
        return None


def parse_portfolio(text: str) -> dict:
    raw_lines = text.split("\n")
    lines = []
    for ln in raw_lines:
        s = ln.strip()
        if not s:
            continue
        if re.match(r"^\d{2}\.\d{2}\.\d{4}", s):
            continue
        if re.match(r"^[=\-#]+$", s):
            continue
        lines.append(re.sub(r"\s+", " ", s))
    joined = "\n".join(lines)

    positions = []
    free_cash = []
    futures_list = []
    fund_total = 0.0
    cash_total = 0.0
    notional_total = 0.0
    go_total = 0.0
    portfolio_total = 0.0

    # --- Positions ----------------------------------------------------------
    for line in joined.split("\n"):
        parts = line.split()
        if len(parts) < 5:
            continue
        cc = parts[1]
        if not re.match(r"^TQ[A-Z]{2}$", cc):
            continue
        ticker = parts[0]
        if ticker == "Итого":
            continue
        val_f = _try_num(parts[-1])
        pr_f = _try_num(parts[-2])
        try:
            q_i = int(parts[-3])
        except ValueError:
            continue
        if val_f is None or pr_f is None:
            continue
        name = " ".join(parts[2:-3])
        positions.append({
            "sec_code": ticker, "class_code": cc, "name": name,
            "qty": q_i, "price": pr_f, "value": val_f,
        })

    m = re.search(r"Итого\s+по\s+активам[^:]*:\s*([\d.,]+)", joined)
    if m:
        fund_total = float(m.group(1).replace(",", "."))

    # --- Gold ---------------------------------------------------------------
    for m in re.finditer(
        r"([\d.,]+)\s+GLD\s*[×x]\s*([\d.,]+)[^=]*?=\s*([\d.,]+)\s*(?:RUB|$)",
        joined,
    ):
        grams = float(m.group(1).replace(",", "."))
        gold_price_g = float(m.group(2).replace(",", "."))
        value_rub = float(m.group(3).replace(",", "."))
        free_cash.append({
            "type": "gold", "grams": grams,
            "price_per_g": gold_price_g, "value_rub": value_rub,
        })

    # --- SUR ----------------------------------------------------------------
    cash_section = ""
    idx_srochny = joined.find("СРОЧНЫЙ")
    if idx_srochny > 0:
        idx_gold = joined.rfind("GLD")
        if idx_gold > 0:
            cash_section = joined[idx_gold:idx_srochny]
    else:
        cash_section = joined

    for m in re.finditer(r"([\d.,]+)\s+SUR\b", cash_section):
        amount = float(m.group(1).replace(",", "."))
        free_cash.append({
            "type": "cash", "currency": "SUR",
            "amount": amount, "value_rub": amount,
        })

    m = re.search(r"Итого:\s*([\d.,]+)\s*RUB", cash_section)
    if m:
        cash_total = float(m.group(1).replace(",", "."))

    # --- Futures ------------------------------------------------------------
    fut_section = ""
    if "СРОЧНЫЙ" in joined:
        fut_section = joined[joined.find("СРОЧНЫЙ"):]
    elif "фьючерс" in joined.lower():
        fut_section = joined

    for line in fut_section.split("\n"):
        parts = line.split()
        if len(parts) < 7:
            continue
        ticker = parts[0]
        if re.match(r"^[\-=]+$", ticker) or ticker in ("Тикер", "Счёт:", "Итого"):
            continue
        if not re.match(r"^[A-Za-z]", ticker):
            continue
        try:
            qty_i = int(parts[-5])
        except ValueError:
            continue
        price_f = _try_num(parts[-4])
        cv_f = _try_num(parts[-3])
        not_f = _try_num(parts[-2])
        go_f = _try_num(parts[-1])
        if any(v is None for v in [price_f, cv_f, not_f, go_f]):
            continue
        name_joined = " ".join(parts[1:-5])
        futures_list.append({
            "sec_code": ticker, "name": name_joined,
            "qty": qty_i, "price": price_f, "contract_value": cv_f,
            "notional": not_f, "go": go_f,
        })

    m = re.search(r"Итого\s+номинал[^:]*:\s*([\d.,]+)\s*RUB", joined)
    if m:
        notional_total = float(m.group(1).replace(",", "."))

    m = re.search(r"Итого\s+заблокировано\s+ГО[^:]*:\s*([\d.,]+)\s*RUB", joined)
    if m:
        go_total = float(m.group(1).replace(",", "."))

    m = re.search(r"ИТОГО[^:]*:\s*([\d.,]+)\s*RUB", joined)
    if m:
        portfolio_total = float(m.group(1).replace(",", "."))

    return {
        "positions": positions,
        "free_cash": free_cash,
        "futures": futures_list,
        "fund_total": fund_total,
        "cash_total": cash_total,
        "notional_total": notional_total,
        "go_total": go_total,
        "portfolio_total": portfolio_total,
    }


def fmt(val):
    return f"{val:,.2f}"


def check(name, got, expected, tol=0.01):
    if tol > 0:
        ok = abs(got - expected) <= tol
    else:
        ok = got == expected
    status = "✅" if ok else "❌ FAIL"
    print(f"  {status} {name}: got={got!r}, expected={expected!r}")
    return ok


errors = 0

print("=" * 60)
print("STANDALONE PARSER VERIFICATION")
print("=" * 60)

test_file = APP_DIR / "test_portfolio.txt"
if not test_file.exists():
    print("ERROR: test_portfolio.txt not found")
    sys.exit(1)

with open(test_file, encoding="utf-8") as f:
    text = f.read()

data = parse_portfolio(text)
print(f"\nParsed from {test_file.name}")
print("-" * 60)

# 1. Positions
print("\n[Positions]")
n_pos = len(data["positions"])
check("Position count", n_pos, 26)
for p in data["positions"]:
    check(f"  {p['sec_code']}: qty={p['qty']}", p["qty"], True)

# Specific positions
lqdt = next((p for p in data["positions"] if p["sec_code"] == "LQDT"), None)
if lqdt:
    check("LQDT qty", lqdt["qty"], 30001)
    check("LQDT class", lqdt["class_code"], "TQBR")
    check("LQDT value", lqdt["value"], 62741.09)

sber = next((p for p in data["positions"] if p["sec_code"] == "SBER"), None)
if sber:
    check("SBER class", sber["class_code"], "TQBR")
    check("SBER value", sber["value"], 280.57)

ofz = next((p for p in data["positions"] if p["sec_code"] == "SU26207RMFS9"), None)
if ofz:
    check("OFZ class", ofz["class_code"], "TQOB")
    check("OFZ qty", ofz["qty"], 190)
    check("OFZ value", ofz["value"], 187037.90)

corp = next((p for p in data["positions"] if p["sec_code"] == "RU000A102556"), None)
if corp:
    check("CORP class", corp["class_code"], "TQCB")

# 2. Fund total
print(f"\n[Fund Total]")
check("fund_total", data["fund_total"], 1046822.65)

# 3. Gold
print(f"\n[Gold]")
gold_items = [c for c in data["free_cash"] if c["type"] == "gold"]
check("Gold items", len(gold_items), 1)
if gold_items:
    g = gold_items[0]
    check("Gold grams", g["grams"], 1.0)
    check("Gold price/g", g["price_per_g"], 11717.0)
    check("Gold RUB", g["value_rub"], 11717.0)

# 4. SUR
print(f"\n[SUR]")
sur_items = [c for c in data["free_cash"] if c["type"] == "cash"]
check("SUR items", len(sur_items), 1)
if sur_items:
    check("SUR amount", sur_items[0]["amount"], 377112.78)

# 5. Cash total
print(f"\n[Cash Total]")
check("cash_total", data["cash_total"], 388829.78)

# 6. Futures
print(f"\n[Futures]")
check("Futures count", len(data["futures"]), 1)
if data["futures"]:
    f = data["futures"][0]
    check("NGV6 ticker", f["sec_code"], "NGV6")
    check("NGV6 qty", f["qty"], 9)
    check("NGV6 price", f["price"], 3.0550)
    check("NGV6 contract_value", f["contract_value"], 25691.14)
    check("NGV6 notional", f["notional"], 231220.30)
    check("NGV6 GO", f["go"], 62451.54)

check("notional_total", data["notional_total"], 231220.30)
check("go_total", data["go_total"], 62451.54)

# 7. Portfolio total
print(f"\n[Portfolio Total]")
check("portfolio_total", data["portfolio_total"], 1435652.43)

# 8. Equity calculation
print(f"\n[Equity Calculation]")
gold_val = sum(c.get("value_rub", 0) for c in data["free_cash"] if c["type"] == "gold")
sur_val = sum(c.get("value_rub", 0) for c in data["free_cash"] if c["type"] == "cash")
equity = data["fund_total"] + gold_val + sur_val + data["go_total"]
print(f"  equity = {fmt(data['fund_total'])} + {fmt(gold_val)} + {fmt(sur_val)} + {fmt(data['go_total'])}")
print(f"  = {fmt(equity)}")
check("computed equity", equity, 1435652.43, tol=1.0)

# 9. Empty portfolio test
print(f"\n[Empty Portfolio Test]")
empty_text = """
====================================================================================================
ФОНДОВЫЙ РЫНОК   Счёт: L01-00000F00
====================================================================================================
Тикер          Класс      Название                         Кол-во           Цена            Сумма
----------------------------------------------------------------------------------------------------
----------------------------------------------------------------------------------------------------
Итого по активам:                                                                          0.00

Свободные средства (T1):

  Итого: 0.00 RUB

====================================================================================================
СРОЧНЫЙ РЫНОК (фьючерсы)
====================================================================================================

Открытых фьючерсных позиций не найдено.

####################################################################################################
ИТОГО портфель (фондовый рынок): 0.00 RUB
####################################################################################################
"""
empty = parse_portfolio(empty_text)
check("empty: positions", len(empty["positions"]), 0)
check("empty: fund_total", empty["fund_total"], 0.0)
check("empty: futures", len(empty["futures"]), 0)
check("empty: portfolio_total", empty["portfolio_total"], 0.0)

print("\n" + "=" * 60)
print("VERIFICATION COMPLETE")
print("=" * 60)
