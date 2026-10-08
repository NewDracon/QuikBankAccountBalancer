"""
Анализ инвестиционного портфеля QUIK
=====================================
Две страницы: 📊 Анализ  и  🎯 Редактор целей.

Запуск:   run_app.bat          # рекомендуемый способ
Тест:     python test_app.py
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# ── Автоактивация .venv при запуске напрямую ────────────────────────────────
_APP_DIR = Path(__file__).parent
_VENV_SITE = _APP_DIR / ".venv" / "Lib" / "site-packages"

if not any(str(_VENV_SITE).replace("\\", "/") in p.replace("\\", "/") for p in sys.path):
    if _VENV_SITE.exists():
        sys.path.insert(0, str(_VENV_SITE))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from typing import Optional, Tuple
try:
    from QuikPy import QuikPy
except ImportError:
    QuikPy = None

# set_page_config должен быть ПЕРВОЙ streamlit-командой
st.set_page_config(page_title="QUIK Portfolio Balancer", layout="wide")

# ════════════════════════════════════════════════════════════════════════════
# КОНСТАНТЫ И ПУТИ
# ════════════════════════════════════════════════════════════════════════════

PORTFOLIO_FILE = _APP_DIR / "portfolio_viewer.txt"
TARGETS_FILE = _APP_DIR / "targets.json"
TEST_DATA_FILE = _APP_DIR / "test_portfolio.txt"

CLASS_CODE_MAP = {
    "TQOB": "ОФЗ", "TQCB": "Корп. облигации",
    "TQTF": "ETF", "TQIF": "ETF",
}
ETF_TICKERS = {"LQDT", "TMUB", "MVIX", "VGTR", "ALFA", "SBMX",
    "AKMC", "CNYM", "SBCB"}

BUY_COLOR = "#27ae60"
SELL_COLOR = "#e74c3c"
MAIN_BLUE = "#2980b9"
CHART_COLORS = [
    "#2980b9", "#e74c3c", "#27ae60", "#f39c12", "#8e44ad",
    "#1abc9c", "#d35400", "#34495e", "#16a085", "#c0392b",
]
OVERLAY_DEFAULT_CLASSES = ["ОФЗ", "Корп. облигации", "ETF"]

DEFAULT_FUTURES_BUFFER_PCT = 15.0

MAIN_ACCOUNT = 'L01-00000F00'
LIMIT_KIND = 1
PRIORITY_CLASSES = [
    'TQBR', 'TQOB', 'TQCB', 'TQIF', 'TQTF', 'TQRD', 'TQOY',
    'PSBB', 'PSAU', 'PSYO', 'PSSU',
    'SMAL', 'FQBR',
    'BQBPIF', 'BQOPIF', 'BQZPIF', 'BQST', 'BQLB', 'BQSBP',
    'BQBPIFSPR', 'BQOPIFSPR', 'BQZPIFSPR', 'BQSBSPR', 'BQSTSPR',
    'BQLBQI', 'BQLBQISPR',
    'MPBB', 'MTQR', 'MPAU', 'MPTR',
    'SPBFUT', 'SPBOPT',
    'CETS', 'CETS_SU', 'CETS_MTL',
]

DIRECT_DATA_FILE = _APP_DIR / "direct_portfolio.txt"

# ════════════════════════════════════════════════════════════════════════════
# УТИЛИТЫ QUIK (если запущено с QuikPy)
# ════════════════════════════════════════════════════════════════════════════

def classify_asset(class_code: str, sec_code: str) -> str:
    sc = sec_code.upper()
    cc = (class_code or "").upper()
    if sc in ETF_TICKERS:
        return "ETF"
    if cc in CLASS_CODE_MAP:
        return CLASS_CODE_MAP[cc]
    if cc == "TQBR":
        return "Акции РФ"
    return class_code if class_code else "Другое"


def find_price(qp, sec_code: str, user_classes: set) -> Tuple[Optional[str], float]:
    candidates = [c for c in PRIORITY_CLASSES if c in user_classes]
    for c in user_classes:
        if c and 'INFO' not in c and c != 'INDX' and c not in candidates:
            candidates.append(c)
    for cc in candidates:
        try:
            raw = qp.get_param_ex(cc, sec_code, 'LAST')['data']['param_value']
            if raw in (None, '', '0', '0.0', '0.00', 0): continue
            val = float(raw)
            if val > 0: return cc, val
        except Exception: continue
    return None, 0.0


def get_futures_contract_value(qp_provider, sec_code: str, class_code: str = 'SPBFUT') -> float:
    """Возвращает стоимость одного фьючерсного контракта в рублях (номинал базового актива) или 0.0, если не удалось получить."""
    try:
        si = qp_provider.get_symbol_info(class_code, sec_code)
        if not si:
            return 0.0
        min_price_step = float(si.get('min_price_step', 0))
        if min_price_step <= 0:
            return 0.0

        last_price_resp = qp_provider.get_param_ex(class_code, sec_code, 'LAST')
        step_price_resp = qp_provider.get_param_ex(class_code, sec_code, 'STEPPRICE')
        
        if not (last_price_resp and 'data' in last_price_resp and step_price_resp and 'data' in step_price_resp):
            return 0.0
            
        last_price = float(last_price_resp['data'].get('param_value', 0))
        step_price = float(step_price_resp['data'].get('param_value', 0))

        if last_price > 0 and step_price > 0:
            # Стоимость одного контракта в рублях
            return last_price / min_price_step * step_price
    except Exception:
        pass
    return 0.0


def get_futures_go(qp_provider, sec_code: str, class_code: str = 'SPBFUT'):
    go_buy = go_sell = None
    for pn in ('BUYDEPO', 'buydepo'):
        try:
            resp = qp_provider.get_param_ex(class_code, sec_code, pn)
            if resp and 'data' in resp:
                val = resp['data'].get('param_value')
                if val not in (None, '', '0', '0.0'):
                    go_buy = float(val); break
        except Exception: pass
    for pn in ('SELLDEPO', 'selldepo'):
        try:
            resp = qp_provider.get_param_ex(class_code, sec_code, pn)
            if resp and 'data' in resp:
                val = resp['data'].get('param_value')
                if val not in (None, '', '0', '0.0'):
                    go_sell = float(val); break
        except Exception: pass
    return go_buy, go_sell


def fetch_portfolio_directly(qp_provider, account='L01-00000F00', limit_kind=1):
    """Выполняет запросы к QUIK и сохраняет форматированный результат."""
    trade_accounts = qp_provider.get_trade_accounts()['data']
    main_acc = next((a for a in trade_accounts if a['trdaccid'] == account), None)
    if not main_acc: return None

    firm_id_main = main_acc['firmid']
    class_codes_str = qp_provider.get_classes_list()['data']
    user_classes = set(c for c in class_codes_str.split(',') if c)

    depo_limits = qp_provider.get_all_depo_limits()['data']
    positions = []
    seen = set()
    for dl in depo_limits:
        if (dl['firmid'] == firm_id_main and dl['limit_kind'] == limit_kind
                and dl['currentbal'] != 0 and dl['sec_code'] not in seen):
            seen.add(dl['sec_code'])
            positions.append(dl)

    money_limits = qp_provider.get_money_limits()['data']
    firm_mls = [ml for ml in money_limits
                if ml['firmid'] == firm_id_main and ml['limit_kind'] == limit_kind]

    gold_price = None
    try:
        gr = qp_provider.get_param_ex('CETS_MTL', 'GLDRUB_TOM', 'LAST')
        if gr and 'data' in gr and gr['data'].get('result') == '1':
            gold_price = float(gr['data']['param_value'])
    except Exception: pass

    futures_holdings_all = qp_provider.get_futures_holdings()['data']

    output_lines = []
    output_lines.append('=' * 100)
    output_lines.append(f'ФОНДОВЫЙ РЫНОК   Счёт: {account}   Фирма: {firm_id_main}   Лимит: T{limit_kind}')
    output_lines.append('=' * 100)
    output_lines.append(f'{"Тикер":<14} {"Класс":<10} {"Название":<28} {"Кол-во":>10} {"Цена":>14} {"Сумма":>16}')
    output_lines.append('-' * 100)

    total_assets = 0.0
    cash_total = 0.0

    for p in positions:
        sec_code = p['sec_code']
        qty = int(p['currentbal'])
        price_class, raw_price = find_price(qp_provider, sec_code, user_classes)
        if price_class:
            try: price = qp_provider.quik_price_to_price(price_class, sec_code, raw_price)
            except Exception: price = raw_price
            try: short_name = qp_provider.get_symbol_info(price_class, sec_code).get('short_name', sec_code)
            except Exception: short_name = sec_code
        else:
            price = 0.0; short_name = sec_code

        value = qty * price
        total_assets += value
        output_lines.append(
            f'{sec_code:<14} {price_class or "?":<10} {short_name[:28]:<28} '
            f'{qty:>10} {price:>14.4f} {value:>16.2f}')

    if positions:
        output_lines.append('-' * 100)
        output_lines.append(f'{"Итого по активам:":<80} {total_assets:>16.2f}')

    output_lines.append(f'\nСвободные средства (T{limit_kind}):')
    for ml in firm_mls:
        currency, amount = ml['currcode'], float(ml['currentbal'])
        if currency == 'GLD':
            if gold_price:
                rub_v = amount * gold_price
                output_lines.append(f'  {amount:>14.2f} GLD  ×  {gold_price:.2f} ₽/г  =  {rub_v:>14.2f} RUB')
                cash_total += rub_v
            else:
                output_lines.append(f'  {amount:>14.2f} GLD  (цена не получена)')
        else:
            cash_total += amount
            output_lines.append(f'  {amount:>14.2f} {currency}')
    output_lines.append(f'  Итого: {cash_total:.2f} RUB')

    output_lines.append('\n' + '=' * 100)
    output_lines.append('СРОЧНЫЙ РЫНОК (фьючерсы)')
    output_lines.append('=' * 100)

    total_futures_nom = total_futures_go_val = 0.0
    FUTURES_FIRM_ID = 'SPBFUT'
    FUTURES_CURRENCY = 'SUR'

    for acc in trade_accounts:
        trdaccid = acc['trdaccid']
        holdings = [h for h in futures_holdings_all
                     if h.get('trdaccid') == trdaccid and h.get('totalnet', 0) != 0]
        if not holdings: continue

        output_lines.append(f'\nСчёт: {trdaccid}')
        output_lines.append(f'{"Тикер":<14} {"Название":<24} {"Кол-во":>8} {"Цена":>10} '
                             f'{"1 контр.":>12} {"Номинал":>16} {"ГО":>12}')
        output_lines.append('-' * 100)

        for h in holdings:
            sec = h['sec_code']
            n = int(h.get('totalnet', 0))

            # Название
            try:
                si = qp_provider.get_symbol_info(FUTURES_FIRM_ID, sec)
                nm = si.get('short_name', sec)[:24] if si else sec[:24]
            except Exception:
                nm = sec[:24]

            # Последняя цена через get_param_ex (как в portfolio_viewer.py)
            try:
                pr = float(qp_provider.get_param_ex(FUTURES_FIRM_ID, sec, 'LAST')['data']['param_value'])
            except Exception:
                pr = 0.0

            # Стоимость контракта и ГО через функции
            cv = get_futures_contract_value(qp_provider, sec, FUTURES_FIRM_ID)
            go_buy, go_sell = get_futures_go(qp_provider, sec, FUTURES_FIRM_ID)
            if n > 0:
                go_per = go_buy or 0.0
            elif n < 0:
                go_per = go_sell or 0.0
            else:
                go_per = 0.0

            nom = abs(n) * cv
            g = abs(n) * go_per

            total_futures_nom += nom
            total_futures_go_val += g

            output_lines.append(f'{sec:<14} {nm:<24} {n:>8} {pr:>10.4f} {cv:>12.2f} {nom:>16.2f} {g:>12.2f}')

    output_lines.append('-' * 100)
    output_lines.append(f'Итого номинал базового актива: {total_futures_nom:>16.2f} RUB')
    output_lines.append(f'Итого заблокировано ГО:         {total_futures_go_val:>16.2f} RUB')
    output_lines.append(f'\nВсего заблокировано ГО по фьючерсам: {total_futures_go_val:.2f} RUB')

    output_lines.append('\n' + '#' * 100)
    output_lines.append(f'ИТОГО портфель (фондовый рынок): {total_assets + cash_total:>16.2f} RUB')
    output_lines.append('#' * 100)

    out_path = DIRECT_DATA_FILE
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(output_lines))
    return out_path


# ════════════════════════════════════════════════════════════════════════════
# ПАРСЕР ПОРТФЕЛЯ
# ════════════════════════════════════════════════════════════════════════════

def parse_portfolio(text: str) -> dict:
    raw_lines = text.split('\n')
    lines = []
    for ln in raw_lines:
        s = ln.strip()
        if not s: continue
        if re.match(r'^\d{2}\.\d{2}\.\d{4}', s): continue
        if re.match(r'^[=\-#]+$', s): continue
        lines.append(re.sub(r'\s+', ' ', s))
    joined = '\n'.join(lines)

    positions, free_cash, futures_list = [], [], []
    fund_total = cash_total = notional_total = go_total = portfolio_total = 0.0

    def _num(v):
        try: return float(v.replace(',', '.'))
        except (ValueError, TypeError): return None

    # ── Фондовый рынок ──
    for line in joined.split('\n'):
        parts = line.split()
        if len(parts) < 5: continue
        cc = parts[1]
        if not re.match(r'^TQ[A-Z]{2}$', cc): continue
        ticker = parts[0]
        if ticker == 'Итого': continue
        val_f, pr_f = _num(parts[-1]), _num(parts[-2])
        try: q_i = int(parts[-3])
        except ValueError: continue
        if val_f is None or pr_f is None: continue
        name = ' '.join(parts[2:-3])
        positions.append({"sec_code": ticker, "class_code": cc, "name": name,
                          "qty": q_i, "price": pr_f, "value": val_f})

    m = re.search(r'Итого\s+по\s+активам[^:]*:\s*([\d.,]+)', joined)
    if m: fund_total = float(m.group(1).replace(',', '.'))

    # ── Золото ──
    for m in re.finditer(r'([\d.,]+)\s+GLD\s*[×x]\s*([\d.,]+)[^=]*?=\s*([\d.,]+)\s*(?:RUB|$)', joined):
        grams = float(m.group(1).replace(',', '.'))
        gold_price_g = float(m.group(2).replace(',', '.'))
        value_rub = float(m.group(3).replace(',', '.'))
        free_cash.append({"type": "gold", "grams": grams,
                          "price_per_g": gold_price_g, "value_rub": value_rub})

    # ── SUR (между GLD и СРОЧНЫЙ) ──
    idx_srochny = joined.find('СРОЧНЫЙ')
    cash_section = ''
    if idx_srochny > 0:
        idx_gold = joined.rfind('GLD')
        if idx_gold > 0: cash_section = joined[idx_gold:idx_srochny]
    else: cash_section = joined

    for m in re.finditer(r'([\d.,]+)\s+SUR\b', cash_section):
        amount = float(m.group(1).replace(',', '.'))
        free_cash.append({"type": "cash", "currency": "SUR",
                          "amount": amount, "value_rub": amount})

    m = re.search(r'Итого:\s*([\d.,]+)\s*RUB', cash_section)
    if m: cash_total = float(m.group(1).replace(',', '.'))

    # ── Фьючерсы ──
    fut_section = ''
    if 'СРОЧНЫЙ' in joined:
        fut_section = joined[joined.find('СРОЧНЫЙ'):]
    elif 'фьючерс' in joined.lower():
        fut_section = joined

    for line in fut_section.split('\n'):
        parts = line.split()
        if len(parts) < 7: continue
        ticker = parts[0]
        if re.match(r'^[\-=]+$', ticker) or ticker in ('Тикер', 'Счёт:', 'Итого', 'Итого_номинал', 'Итого_заблокировано'): continue
        if not re.match(r'^[A-Za-z]', ticker): continue
        try: qty_i = int(parts[-5])
        except ValueError: continue
        price_f, cv_f = _num(parts[-4]), _num(parts[-3])
        not_f, go_f = _num(parts[-2]), _num(parts[-1])
        if any(v is None for v in [price_f, cv_f, not_f, go_f]): continue
        name_joined = ' '.join(parts[1:-5])
        futures_list.append({
            "sec_code": ticker, "name": name_joined, "qty": qty_i,
            "price": price_f, "contract_value": cv_f,
            "notional": not_f, "go": go_f,
        })

    m = re.search(r'Итого\s+номинал[^:]*:\s*([\d.,]+)\s*RUB', joined)
    if m: notional_total = float(m.group(1).replace(',', '.'))
    m = re.search(r'Итого\s+заблокировано\s+ГО[^:]*:\s*([\d.,]+)\s*RUB', joined)
    if m: go_total = float(m.group(1).replace(',', '.'))
    m = re.search(r'ИТОГО[^:]*:\s*([\d.,]+)\s*RUB', joined)
    if m: portfolio_total = float(m.group(1).replace(',', '.'))

    return {
        "positions": positions, "free_cash": free_cash, "futures": futures_list,
        "fund_total": fund_total, "cash_total": cash_total,
        "notional_total": notional_total, "go_total": go_total,
        "portfolio_total": portfolio_total,
    }


# ════════════════════════════════════════════════════════════════════════════
# РАСЧЁТ ПОРТФЕЛЯ (новая архитектура с фьючерсами)
# ════════════════════════════════════════════════════════════════════════════

def calc_portfolio(raw: dict, targets: dict) -> dict:
    """
    Расчёт портфеля с учётом фьючерсов как особого класса.

    Equity = фондовый_рынок + золото + свободные_средства + ГО
             = fund_total + gold_val + sur_val + go_total

    Номинал фьючерсов НЕ складывается в equity напрямую.
    Вместо этого:
      - ГО заблокировано (go_total)
      - Буфер от номинала фьючерсов (notional * buffer_pct / 100) замораживается
      - Всё это берётся из свободных средств
      - Если свободных > ГО+буфер, разница распределяется как overlay на заданные классы
    """
    classes_data = targets.get("classes", {})
    tickers_targets = targets.get("tickers", {})
    buffer_pct = float(targets.get("futures_buffer_pct", DEFAULT_FUTURES_BUFFER_PCT))
    overlay_cls = targets.get("futures_overlay_classes", OVERLAY_DEFAULT_CLASSES)

    fund_total = raw["fund_total"]
    gold_val = sum(i.get("value_rub", 0) for i in raw["free_cash"] if i["type"] == "gold")
    sur_val = sum(i.get("value_rub", 0) for i in raw["free_cash"] if i["type"] == "cash")
    notional = raw["notional_total"]
    go = raw["go_total"]

    # EQUITY = фондовый рынок + золото + свободные средства (SUR)
    # ГО (go) уже включено в sur_val (это заблокированные средства на счёте), не складываем дважды
    equity = fund_total + gold_val + sur_val

    # ── Фьючерсная логика ──
    total_fut_nominal = sum(f["notional"] for f in raw["futures"])
    total_fut_margin = sum(f["go"] for f in raw["futures"])
    if not total_fut_margin: total_fut_margin = go

    fut_buffer_amount = round(total_fut_nominal * buffer_pct / 100, 2)
    fut_required_liquidity = round(total_fut_margin + fut_buffer_amount, 2)

    # Сколько осталось для overlay после покрытия ГО+буфер
    remaining_for_overlay = round(sur_val - fut_required_liquidity, 2)
    if remaining_for_overlay < 0: remaining_for_overlay = 0.0

    # Распределяем remaining поверх классов по их текущим весам в фондовом рынке
    overlay_alloc = {}
    if overlay_cls and remaining_for_overlay > 0:
        class_store_raw = {}
        for p in raw["positions"]:
            cls = classify_asset(p["class_code"], p["sec_code"])
            if cls in overlay_cls:
                class_store_raw[cls] = class_store_raw.get(cls, 0) + p["value"]
        total_overlay_base = sum(class_store_raw.values()) or 1
        for cls_name in overlay_cls:
            cls_val = class_store_raw.get(cls_name, 0)
            ratio = cls_val / total_overlay_base
            overlay_alloc[cls_name] = round(remaining_for_overlay * ratio, 2)

    # ── Сбор позиций по классам ──
    class_store = {}
    ticker_class_map = {}
    warnings_list = []

    def add_ticker(cls_name, info):
        if cls_name not in class_store:
            class_store[cls_name] = {"total": 0.0, "tickers": {}}
        class_store[cls_name]["tickers"][info["sec"]] = info
        class_store[cls_name]["total"] += info["value"]

    # Фондовые позиции
    for p in raw["positions"]:
        cls = classify_asset(p["class_code"], p["sec_code"])
        ticker_class_map[p["sec_code"]] = cls
        add_ticker(cls, {"sec": p["sec_code"], "name": p["name"],
                         "qty": p["qty"], "price": p["price"], "value": p["value"]})

    # Золото
    if gold_val > 0:
        gp = next((i["price_per_g"] for i in raw["free_cash"] if i["type"] == "gold"), 0)
        add_ticker("Золото", {"sec": "GLD", "name": "Золото (GLD)",
            "qty": next((i["grams"] for i in raw["free_cash"] if i["type"] == "gold"), None),
            "price": gp, "unit": "г", "value": gold_val})

    # Ликвидность для фьючерсов — просто денежная ликвидность из отчета (SUR)
    # Заменяет собой особый расчет и класс "Фьючерсы" в левой диаграмме
    if sur_val > 0:
        add_ticker("Ликв. для фьючерсов", {"sec": "SUR", "name": "Ликвидность для фьючерсов",
            "qty": None, "price": 1.0, "value": sur_val})

    # Фьючерсы НЕ включаем в левую диаграмму "Текущее распределение"
    # (они будут в правой диаграмме целевом и в разделе фьючерсов)

    # Предупреждения
    for sec, cls in ticker_class_map.items():
        if cls in tickers_targets and tickers_targets[cls]:
            if sec not in tickers_targets[cls]:
                warnings_list.append(f"Тикер `{sec}` ({cls}) есть в портфеле, но нет цели")

    # ── Весовые доли ──
    class_weights = {}
    for cn, cd in class_store.items():
        class_weights[cn] = cd["total"] / equity * 100 if equity > 0 else 0.0

    all_classes = sorted(set(list(class_weights.keys()) + list(classes_data.keys())))

    class_devs = {}
    for cn in all_classes:
        cur = round(class_weights.get(cn, 0), 2)
        tgt = round(classes_data.get(cn, 0), 2)
        dev = round(cur - tgt, 2)
        act = "buy" if dev < -0.5 else ("sell" if dev > 0.5 else "hold")
        vol = round(abs(dev) / 100 * equity, 2) if dev != 0 else 0.0
        class_devs[cn] = {"current": cur, "target": tgt, "deviation": dev,
                          "action": act, "volume": vol}

    # ── Детализация по тикерам (только не-спецклассы) ──
    ticker_devs = {}
    skipped = {}

    for cn, cd in class_store.items():
        if cn in ("Ликвидность", "Фьючерсы", "Ликв. для фьючерсов"): continue
        tgt_cls_pct = classes_data.get(cn, 0)
        tgt_list = tickers_targets.get(cn, {})
        if not tgt_list:
            for t in cd["tickers"]:
                skipped[(cn, t)] = "Нет цели для класса"
            continue
        cls_total = cd["total"]
        for sec, info in cd["tickers"].items():
            if sec in tgt_list:
                tgt_tkr_pct = tgt_list[sec]
                target_val = (tgt_cls_pct / 100) * equity * (tgt_tkr_pct / 100)
                cur_val = info["value"]
                diff = target_val - cur_val
                act = "Покупка" if diff > 0.5 else ("Продажа" if diff < -0.5 else "Без изменений")
                cv = info.get("contract_value", 0)
                pr = info.get("price", 0)
                qty_ch = round(diff / cv) if cv and cv > 0 else (round(diff / pr) if pr and pr > 0 else 0)
                wc_in = cur_val / cls_total * 100 if cls_total > 0 else 0
                ticker_devs[(cn, sec)] = {
                    "cur_val": cur_val, "tgt_val": target_val, "diff": diff,
                    "action": act, "qty_change": qty_ch,
                    "cur_wt": round(wc_in, 2), "tgt_wt": round(tgt_tkr_pct, 2),
                    "diff_wt": round(wc_in - tgt_tkr_pct, 2)}
            else:
                skipped[(cn, sec)] = "Тикер отсутствует в цели"

    # ── Данные для фьючерсной диаграммы ──
    fut_chart_data = {
        "total_nominal": total_fut_nominal,
        "total_fut_margin": total_fut_margin,
        "total_margin": total_fut_margin,
        "buffer_amount": fut_buffer_amount,
        "required_liquidity": fut_required_liquidity,
        "sur_available": sur_val,
        "remaining_for_overlay": remaining_for_overlay,
        "overlay_alloc": overlay_alloc,
        "overlay_total": sum(overlay_alloc.values()),
        "per_future": [],
    }
    for fut in raw["futures"]:
        fut_chart_data["per_future"].append({
            "sec_code": fut["sec_code"], "name": fut["name"],
            "qty": fut["qty"], "notional": fut["notional"],
            "go": fut["go"], "margin_pct": round(fut["go"] / fut["notional"] * 100, 2) if fut["notional"] > 0 else 0,
        })

    return {
        "equity": equity, "fund_total": fund_total, "gold_val": gold_val,
        "sur_val": sur_val, "notional": notional, "go": go,
        "total_fut_nominal": total_fut_nominal, "total_fut_margin": total_fut_margin,
        "fut_buffer_amount": fut_buffer_amount, "fut_required_liquidity": fut_required_liquidity,
        "actual_sur_remainder": sur_val,
        "class_store": class_store, "class_weights": class_weights,
        "all_classes": all_classes, "class_devs": class_devs,
        "ticker_devs": ticker_devs, "skipped": skipped,
        "warnings": warnings_list, "classes_data": classes_data,
        "fut_chart_data": fut_chart_data, "overlay_alloc": overlay_alloc,
    }


# ════════════════════════════════════════════════════════════════════════════
# ЦЕЛЕВЫЕ ВЕСА
# ════════════════════════════════════════════════════════════════════════════

DEFAULT_CLASSES = {
    "ОФЗ": 20.0, "Корп. облигации": 10.0, "Акции РФ": 5.0,
    "ETF": 5.0, "Золото": 10.0, "Фьючерсы": 15.0, "Ликвидность": 35.0,
}

def load_targets() -> dict:
    if TARGETS_FILE.exists():
        try:
            with open(TARGETS_FILE, encoding="utf-8") as f:
                d = json.load(f)
            if "classes" not in d: d["classes"] = DEFAULT_CLASSES.copy()
            if "tickers" not in d: d["tickers"] = {}
            if "futures_overlay_classes" not in d: d["futures_overlay_classes"] = OVERLAY_DEFAULT_CLASSES[:]
            if "futures_buffer_pct" not in d: d["futures_buffer_pct"] = DEFAULT_FUTURES_BUFFER_PCT
            return d
        except Exception: pass
    return _default_targets()

def save_targets(d: dict) -> bool:
    try:
        # Добавим отладку
        print("DEBUG: Сохраняемые цели:", json.dumps(d, ensure_ascii=False, indent=2, default=str))
        with open(TARGETS_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2, default=str)
        print("DEBUG: Сохранение завершено успешно")
        return True
    except Exception as e:
        print(f"DEBUG: Ошибка сохранения целей: {e}")
        return False

def _default_targets() -> dict:
    d = {
        "classes": DEFAULT_CLASSES.copy(), "tickers": {},
        "futures_overlay_classes": OVERLAY_DEFAULT_CLASSES[:],
        "futures_buffer_pct": DEFAULT_FUTURES_BUFFER_PCT,
    }
    save_targets(d); return d

def build_ticker_defaults_from_portfolio(raw_data: dict) -> dict:
    tgts = load_targets()
    tgts.setdefault("tickers", {})
    for p in raw_data["positions"]:
        cls = classify_asset(p["class_code"], p["sec_code"])
        if cls not in ("Золото", "Ликвидность"):
            tgts["tickers"].setdefault(cls, {})
            if p["sec_code"] not in tgts["tickers"][cls]:
                tgts["tickers"][cls][p["sec_code"]] = 0
    for fut in raw_data.get("futures", []):
        tgts["tickers"].setdefault("Фьючерсы", {})
        if fut["sec_code"] not in tgts["tickers"]["Фьючерсы"]:
            tgts["tickers"]["Фьючерсы"][fut["sec_code"]] = 0
    for cls, tk_dict in tgts["tickers"].items():
        zero_keys = [k for k, v in tk_dict.items() if v == 0]
        n = len(zero_keys)
        if n == 0: continue
        w = round(100.0 / n, 2)
        diff = 100.0 - w * n
        for i, k in enumerate(zero_keys):
            tk_dict[k] = round(w + (diff if i == n - 1 else 0), 2)
    return tgts


# ════════════════════════════════════════════════════════════════════════════
# ВИЗУАЛИЗАЦИЯ PLOTLY
# ════════════════════════════════════════════════════════════════════════════

def make_pie_chart(values, labels, title, colors=None, hole=0.4):
    # Фильтруем синхронно: values, labels, colors
    filtered = [(v, l, c) for v, l, c in zip(values, labels, (colors or CHART_COLORS)) if v > 0]
    if not filtered:
        # Пустой график
        return go.Figure()
    positive_vals, pos_labels, pos_colors = zip(*filtered)
    fig = go.Figure([go.Pie(
        labels=pos_labels, values=positive_vals, hole=hole,
        marker=dict(colors=pos_colors),
        textposition="inside", textinfo="percent+label",
        hovertemplate="<b>%{label}</b><br>Стоимость: %{value:,.0f} ₽<br>Доля: %{percent}<extra></extra>",
        pull=[0.02 if v > sum(positive_vals) * 0.2 else 0 for v in positive_vals],
    )])
    fig.update_layout(title=dict(text=title, font=dict(size=16, color="#2c3e50"), x=0.5),
                      height=400, showlegend=True,
                      legend=dict(orientation="h", yanchor="bottom", y=-0.12, xanchor="center", x=0.5),
                      margin=dict(l=10, r=10, t=55, b=10))
    fig.update_traces(textfont_size=11); return fig

def make_bar_deviations(result):
    devs = result["class_devs"]
    classes = [c for c in result["all_classes"] if c in devs]
    if not classes: return go.Figure()
    cur = [devs[c]["current"] for c in classes]
    tgt = [devs[c]["target"] for c in classes]
    dev = [devs[c]["deviation"] for c in classes]
    dev_colors = [BUY_COLOR if d >= 0 else SELL_COLOR for d in dev]
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Отклонение %", x=classes, y=dev,
                         marker_color=dev_colors, text=[fmt_pct(d) for d in dev],
                         textposition="outside",
                         hovertemplate="<b>%{x}</b><br>Отклонение: %{y:.2f}%<extra></extra>"))
    fig.add_trace(go.Scatter(name="Цель (%)", x=classes, y=tgt, mode="lines+markers",
                              marker=dict(symbol="diamond", size=9, color=MAIN_BLUE),
                              line=dict(color=MAIN_BLUE, width=2, dash="dash")))
    fig.add_trace(go.Scatter(name="Текущее (%)", x=classes, y=cur, mode="lines+markers",
                              marker=dict(symbol="circle", size=9, color="#2c3e50"),
                              line=dict(color="#2c3e50", width=2)))
    fig.update_layout(title=dict(text="Распределение по классам vs Цель",
                                 font=dict(size=16, color="#2c3e50"), x=0.5),
                      xaxis_title="", yaxis_title="% портфеля", height=420,
                      barmode="group",
                      legend=dict(orientation="h", yanchor="bottom", y=-0.18, xanchor="center", x=0.5),
                      margin=dict(l=50, r=20, t=50, b=80))
    return fig

def make_futures_pie(current_values, current_labels, target_values, target_labels,
                     cu_colors, tu_colors):
    fig = go.Figure()
    fig.add_trace(go.Pie(values=current_values, labels=current_labels, hole=0.4,
                          name="Текущее", marker=dict(colors=cu_colors),
                          textposition="inside", textinfo="percent+label",
                          hovertemplate="<b>%{label}</b><br>Стоимость: %{value:,.0f} ₽<br>Доля: %{percent}<extra></extra>"))
    fig.add_trace(go.Pie(values=target_values, labels=target_labels, hole=0.4,
                          name="Целевое", marker=dict(colors=tu_colors),
                          textposition="inside", textinfo="percent+label",
                          hovertemplate="<b>%{label}</b><br>Стоимость: %{value:,.0f} ₽<br>Доля: %{percent}<extra></extra>"))
    fig.update_layout(title=dict(text="📊 Структура фьючерсов — Текущее vs Целевое",
                                 font=dict(size=15, color="#2c3e50"), x=0.5),
                      height=420, showlegend=True,
                      legend=dict(orientation="h", yanchor="top", y=-0.22, xanchor="center", x=0.5),
                      margin=dict(l=10, r=10, t=50, b=30))
    return fig

def fmt_pct(pct):
    sign = "+" if pct >= 0 else "-"
    return f"{sign}{abs(pct):.2f}%"


# ════════════════════════════════════════════════════════════════════════════
# HELPERS dataframe styling
# ════════════════════════════════════════════════════════════════════════════

def _row_action_style(val):
    if isinstance(val, str):
        if val == "BUY":
            return "background:#27ae60;color:#000000;font-weight:bold;border-radius:6px;padding:2px 10px;"
        if val == "SELL":
            return "background:#e74c3c;color:#000000;font-weight:bold;border-radius:6px;padding:2px 10px;"
    return ""

def _action_text_style(val):
    if val == "Покупка":
        return "background:#27ae60;color:#000000;font-weight:bold;"
    if val == "Продажа":
        return "background:#e74c3c;color:#000000;font-weight:bold;"
    return ""

# ════════════════════════════════════════════════════════════════════════════
# СТРАНИЦА 1: АНАЛИЗ ПОРТФЕЛЯ
# ════════════════════════════════════════════════════════════════════════════

def page_analysis():
    st.title("📊 Анализ инвестиционного портфеля QUIK")

    # ── Инициализация state ──
    if "raw_portfolio_text" not in st.session_state: st.session_state.raw_portfolio_text = None
    if "pending_portfolio_text" not in st.session_state: st.session_state.pending_portfolio_text = None
    if "targets" not in st.session_state: st.session_state.targets = load_targets()
    if "_needs_recalc" not in st.session_state: st.session_state._needs_recalc = False
    if "uploader_key" not in st.session_state: st.session_state.uploader_key = 0

    targets = st.session_state.targets

    # Парсим из сохранённого текста (если есть)
    parsed = parse_portfolio(st.session_state.raw_portfolio_text) if st.session_state.raw_portfolio_text else None

    # ── Sidebar: загрузка данных ──
    with st.sidebar:
        st.header("📥 Данные")

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("⚡ Из QUIK", use_container_width=True):
                if QuikPy is None:
                    st.error("QuikPy не установлен")
                else:
                    st.info("Загрузка из QUIK...")
                    try:
                        with QuikPy() as qp:
                            result = fetch_portfolio_directly(qp)
                            st.info(f"Функция вернула: {result}")
                            st.info(f"Путь к файлу: {DIRECT_DATA_FILE}")
                            st.info(f"Файл существует: {os.path.exists(DIRECT_DATA_FILE)}")
                            if os.path.exists(DIRECT_DATA_FILE):
                                with open(DIRECT_DATA_FILE, 'r', encoding='utf-8') as f:
                                    text = f.read()
                                st.info(f"Читаем файл, размер: {len(text)} символов")
                                st.session_state.raw_portfolio_text = text
                                st.session_state.targets = load_targets()
                                st.success("✅ Данные из QUIК загружены!")
                            else:
                                st.error("Не удалось получить данные из QUIК")
                                # Проверим, существует ли директория
                                if DIRECT_DATA_FILE.parent.exists():
                                    st.info(f"Директория существует: {DIRECT_DATA_FILE.parent}")
                                else:
                                    st.error(f"Директория не существует: {DIRECT_DATA_FILE.parent}")
                    except Exception as e:
                        st.error(f"Ошибка: {e}")
                        import traceback
                        st.error(f"Трассировка: {traceback.format_exc()}")
                    st.rerun()

        with col_b:
            # Ключ меняется при сбросе, чтобы заставить uploader сбросить значение
            upl = st.file_uploader("Или .txt", type=["txt"], key=f"upl_file_{st.session_state.uploader_key}")
            if upl is not None:
                # Читаем файл в pending — ждём нажатия кнопки
                text = upl.getvalue().decode("utf-8")
                with open(str(PORTFOLIO_FILE), "wb") as f: f.write(upl.getvalue())
                st.session_state.pending_portfolio_text = text
                st.info(f"Файл готов: {upl.name} ({len(text):,} символов)")

            # Кнопка загрузки выбранного файла
            if st.session_state.pending_portfolio_text:
                if st.button("📥 Загрузить отчёт", use_container_width=True, type="primary"):
                    st.session_state.raw_portfolio_text = st.session_state.pending_portfolio_text
                    st.session_state.pending_portfolio_text = None
                    st.session_state.targets = load_targets()
                    st.rerun()

        if DIRECT_DATA_FILE.exists():
            if st.button("Последние данные из QUIK", use_container_width=True):
                with open(DIRECT_DATA_FILE, encoding="utf-8") as f:
                    text = f.read()
                st.session_state.raw_portfolio_text = text
                st.session_state.targets = load_targets()
                st.rerun()

        if TEST_DATA_FILE.exists():
            if st.button("🧪 Тестовые данные", use_container_width=True):
                with open(TEST_DATA_FILE, encoding="utf-8") as f:
                    text = f.read()
                st.session_state.raw_portfolio_text = text
                st.session_state.targets = load_targets()
                st.rerun()

        # Кнопка очистки загруженных данных
        if parsed:
            if st.button("🗑 Очистить данные", use_container_width=True):
                st.session_state.raw_portfolio_text = None
                st.session_state.uploader_key += 1  # сбрасываем uploader
                st.rerun()

        if parsed:
            p = parsed
            st.markdown(
                f"**Статус:** OK  \n"
                f"- Позиций: **{len(p['positions'])}**  \n"
                f"- Фьючерсов: **{len(p['futures'])}**  \n"
                f"- Свободные: **{p['cash_total']:,.2f} руб.**  \n"
                f"- Итого: **{p['portfolio_total']:,.2f} руб.**")

        if parsed and targets.get("tickers"):
            empty = any(len(v or {}) == 0 for v in targets["tickers"].values())
            if empty:
                if st.button("📋 Заполнить цели тикеров", use_container_width=True):
                    new = build_ticker_defaults_from_portfolio(parsed)
                    st.session_state.targets = new; st.rerun()

        st.divider()
        st.caption("🎯 Редактировать цели → меню слева")

    # ── Нет данных ──
    if parsed is None:
        st.info("Загрузите данные или нажмите **«🧪 Тестовые данные»**.")
        if TEST_DATA_FILE.exists():
            st.divider()
            with st.expander("Образец test_portfolio.txt"):
                with open(TEST_DATA_FILE, encoding="utf-8") as f:
                    st.code(f.read(), language="text")
        return

    needs_recalc = st.session_state.pop("_needs_recalc", False)
    if needs_recalc:
        saved = load_targets()
        if saved != targets:
            targets = saved

    result = calc_portfolio(parsed, targets)

    if result["warnings"]:
        with st.expander("⚠️ Предупреждения"):
            for w in result["warnings"]: st.warning(w)

    # ═══════════════════════════════════════════════════════════════
    # СВОДКА
    # ═══════════════════════════════════════════════════════════════
    st.header("📋 Сводка")

    left, right = st.columns([1, 4])
    with left:
        st.metric("💰 Общий капитал (equity)",
                  f"{result['equity']:,.2f} руб.")

    with right:
        cl = result["all_classes"]
        cw = result["class_weights"]
        n_cols = min(len(cl), 5)
        cols_sum = st.columns(n_cols)
        for i, c in enumerate(cl):
            dv = result["class_devs"].get(c, {}).get("deviation", 0)
            cols_sum[i % n_cols].metric(
                c, f"{cw.get(c, 0):.1f}%",
                delta=f"{dv:+.1f}%" if abs(dv) > 0.05 else None,
                delta_color="normal" if dv <= 0 else "inverse")

    # Информация по фьючерсам
    fc = result["fut_chart_data"]
    if fc["total_nominal"] > 0:
        st.divider()
        st.subheader("📜 Фьючерсы — справка")
        col_f1, col_f2, col_f3, col_f4 = st.columns(4)
        buf = float(targets.get("futures_buffer_pct", DEFAULT_FUTURES_BUFFER_PCT))
        col_f1.metric("📐 Номинал", f"{fc['total_nominal']:,.2f} ₽")
        col_f2.metric("🔒 ГО", f"{fc['total_fut_margin']:,.2f} ₽")
        col_f3.metric(f"🛡 Буфер ({buf}%)", f"{fc['buffer_amount']:,.2f} ₽")
        col_f4.metric("💳 Нужная ликвидность", f"{fc['required_liquidity']:,.2f} ₽")

        overlay_sum = fc["overlay_total"]
        avail = fc["sur_available"]
        rem = fc["remaining_for_overlay"]
        if overlay_sum > 0:
            st.caption(f"→ Остаток ликвидности: {rem:,.2f} ₽ → распределён по overlay на {', '.join(fc['overlay_alloc'].keys())}")
        elif avail > fc["required_liquidity"]:
            st.caption(f"→ Свободная ликвидность: {rem:,.2f} ₽ (не распределена)")

    # ═══════════════════════════════════════════════════════════════
    # ГЛАВНЫЕ ГРАФИКИ РАСПРЕДЕЛЕНИЯ — СТАБИЛЬНЫЕ ЦВЕТА + ЛЕГЕНДА ₽
    # ═══════════════════════════════════════════════════════════════
    st.divider()

    # ── Стабильная карта цветов: один и тот же ключ → всегда один цвет ──
    _GLOBAL_CLASS_PALETTE = [
        "#2980b9",       # синий
        "#e74c3c",       # красный
        "#27ae60",       # зелёный
        "#f39c12",       # жёлтый
        "#8e44ad",       # фиолетовый
        "#1abc9c",       # бирюзовый
        "#d35400",       # оранжевый
        "#34495e",       # тёмно-серый
        "#16a085",       # светло-зелёный
        "#c0392b",       # тёмно-красный
    ]
    _CLASS_COLOR_MAP = {cn: _GLOBAL_CLASS_PALETTE[i % len(_GLOBAL_CLASS_PALETTE)] for i, cn in enumerate(cl)}

    def _stable_colors(label_list):
        """Строгие цвета по порядку label_list."""
        return [_CLASS_COLOR_MAP.get(l, "#999") for l in label_list]

    st.subheader("📈 Распределение по классам")
    gcol1, gcol2 = st.columns(2)

    with gcol1:
        vals = [result["class_store"].get(c, {}).get("total", 0) for c in cl]
        colors_cur = _stable_colors(cl)
        st.plotly_chart(make_pie_chart(vals, cl, "📊 Текущее распределение", colors_cur),
                        use_container_width=True)
    with gcol2:
        tgt_vals = [result["classes_data"].get(c, 0) / 100 * result["equity"] for c in cl]
        colors_tgt = _stable_colors(cl)
        st.plotly_chart(make_pie_chart(tgt_vals, cl, "🎯 Целевое распределение", colors_tgt),
                        use_container_width=True)

    # ── Легенда с рублями для основных диаграмм ──
    rub_col1, rub_col2 = st.columns(2)
    with rub_col1:
        st.markdown(f"<div style='border:1px solid #ddd;border-radius:8px;padding:10px;margin-top:4px;background:#fafafa'>"
                     f"<b>📊 Текущее (₽)</b>", unsafe_allow_html=True)
        for ci, c in enumerate(cl):
            v = vals[ci]
            if v <= 0: continue
            color = _CLASS_COLOR_MAP[c]
            st.markdown(
                f"• <span style='color:{color}'>●</span> **{c}**: {v:,.0f} ₽ ({v/result['equity']*100:.1f}%)",
                unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with rub_col2:
        st.markdown(f"<div style='border:1px solid #ddd;border-radius:8px;padding:10px;margin-top:4px;background:#fafafa'>"
                     f"<b>🎯 Целевое (₽)</b>", unsafe_allow_html=True)
        for ci, c in enumerate(cl):
            v = tgt_vals[ci]
            if v <= 0: continue
            color = _CLASS_COLOR_MAP[c]
            st.markdown(
                f"• <span style='color:{color}'>●</span> **{c}**: {v:,.0f} ₽ ({tgt_vals[ci]/result['equity']*100:.1f}%)",
                unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    st.subheader("📉 Отклонения от цели")
    st.plotly_chart(make_bar_deviations(result), use_container_width=True)

    # ═══════════════════════════════════════════════════════════════
    # ФЬЮЧЕРСНАЯ ДИАГРАММА — легенда ₽ всегда, правильная математика
    # ═══════════════════════════════════════════════════════════════
    if fc["total_nominal"] > 0:
        st.divider()

        st.subheader("📊 Фьючерсы — структура обеспечения")

        # ── Математика ─────────────────────────────────────────────
        # ТЕКУЩАЯ структура обеспечения:
        #   - Номинал = Номинал из отчета (total_fut_nominal)
        #   - ГО = ГО из QUIK-отчета (total_fut_margin)
        #   - Буфер текущий = Номинал × buffer_pct% (настройка, по умолчанию 15%)
        #   - Распределённая ликвидность = Номинал - ГО - Буфер текущий
        #
        # ЦЕЛЕВАЯ структура обеспечения:
        #   - Номинал = значение "Фьючерсы" из целевого распределения (futures_target_value)
        #   - Буфер целевой = Номинал × buffer_pct% (настройка)
        #   - Номинал 1 контракта = total_fut_nominal / total_qty (из отчета)
        #   - ГО 1 контракта = total_fut_margin / total_qty (из отчета)
        #   - Целевое кол-во контрактов = Номинал (целевой) / Номинал 1 контракта
        #   - Целевое ГО = Целевое кол-во контрактов × ГО 1 контракта
        #   - Распределённая ликвидность = Номинал - Целевое ГО - Буфер целевой
        #   - Если целевое кол-во ≠ кол-во по отчету → рекомендовать сделку
        # ────────────────────────────────────────────────────────────

        buffer_pct = float(targets.get("futures_buffer_pct", DEFAULT_FUTURES_BUFFER_PCT))

        # --- Расчет на 1 контракт (из отчета) ---
        total_qty = sum(abs(f["qty"]) for f in fc["per_future"])
        if total_qty > 0:
            nominal_per_contract = fc["total_nominal"] / total_qty
            go_per_contract = fc["total_fut_margin"] / total_qty
        else:
            nominal_per_contract = 0
            go_per_contract = 0

        # --- ТЕКУЩАЯ структура ---
        cur_nominal = fc["total_nominal"]
        cur_go = fc["total_fut_margin"]
        cur_buffer = round(cur_nominal * buffer_pct / 100.0, 2)
        cur_distributed = round(cur_nominal - cur_go - cur_buffer, 2)
        if cur_distributed < 0:
            cur_distributed = 0.0
            cur_buffer = round(cur_nominal - cur_go, 2)

        # --- ЦЕЛЕВАЯ структура ---
        tgt_nominal = cur_nominal  # default
        futures_class_index = None
        try:
            futures_class_index = cl.index("Фьючерсы")
            if futures_class_index is not None and futures_class_index < len(cl):
                futures_target_value = tgt_vals[futures_class_index]
                if futures_target_value > 0:
                    tgt_nominal = futures_target_value
        except (ValueError, IndexError):
            pass

        tgt_buffer = round(tgt_nominal * buffer_pct / 100.0, 2)

        # Целевое количество контрактов (с округлением вниз, так как контракты целые)
        if nominal_per_contract > 0:
            target_contracts = int(tgt_nominal / nominal_per_contract)
        else:
            target_contracts = 0

        # Целевое ГО = целевое кол-во контрактов × ГО на 1 контракт
        tgt_go = round(target_contracts * go_per_contract, 2)

        tgt_distributed = round(tgt_nominal - tgt_go - tgt_buffer, 2)
        if tgt_distributed < 0:
            tgt_distributed = 0.0
            tgt_buffer = round(tgt_nominal - tgt_go, 2)

        # --- Рекомендации по фьючерсам ---
        # Если целевое кол-во контрактов отличается от фактического — рекомендуем сделку
        futures_recs = []
        if total_qty > 0 and target_contracts != total_qty:
            diff_contracts = target_contracts - total_qty
            action = "Покупка" if diff_contracts > 0 else "Продажа"
            # Распределяем по тикерам (если один тикер — весь объем на него)
            if len(fc["per_future"]) == 1:
                sec_code = fc["per_future"][0]["sec_code"]
                futures_recs.append({
                    "sec_code": sec_code,
                    "action": action,
                    "qty_change": abs(diff_contracts),
                    "current_qty": total_qty,
                    "target_qty": target_contracts
                })
            else:
                # Пороговые изменения пропорционально текущим позициям
                for fut in fc["per_future"]:
                    prop = abs(fut["qty"]) / total_qty if total_qty > 0 else 0
                    chg = int(round(diff_contracts * prop))
                    if chg != 0:
                        act = "Покупка" if chg > 0 else "Продажа"
                        futures_recs.append({
                            "sec_code": fut["sec_code"],
                            "action": act,
                            "qty_change": abs(chg),
                            "current_qty": int(abs(fut["qty"])),
                            "target_qty": int(abs(fut["qty"])) + chg
                        })

        cur_labels = ["ГО (из QUIK)", "Буфер текущий", "Распределённая ликвидность"]
        cur_values = [round(cur_go, 2), round(cur_buffer, 2), round(cur_distributed, 2)]
        tgt_labels = ["ГО (рассчитанное)", "Буфер целевой", "Распределённая ликвидность"]
        tgt_values = [round(tgt_go, 2), round(tgt_buffer, 2), round(tgt_distributed, 2)]

        sector_colors_map = {
            "ГО (из QUIK)": "#d35400",
            "Буфер текущий": "#f39c12",
            "Распределённая ликвидность": "#2ecc71",
            "Буфер целевой": "#f39c12",
            "ГО (рассчитанное)": "#d35400",
        }
        cu_colors = [sector_colors_map[l] for l in cur_labels]
        tu_colors = [sector_colors_map[l] for l in tgt_labels]

        fig_cur = go.Figure([go.Pie(
            labels=cur_labels, values=cur_values, hole=0.4,
            marker=dict(colors=cu_colors),
            textposition="inside", textinfo="percent+label",
            hovertemplate="<b>%{label}</b><br>"
                          "<i>₽:</i> %{value:,.0f} ₽<br>"
                          "<i>%:</i> %{percent}<extra></extra>",
            pull=[0.04],
        )])
        fig_cur.update_layout(
            title={"text": "Текущая структура обеспечения", "font": {"size": 15}, "x": 0.5},
            height=400, showlegend=False, margin=dict(l=10, r=10, t=50, b=70))
        fig_cur.update_traces(textfont_size=11)

        fig_tgt = go.Figure([go.Pie(
            labels=tgt_labels, values=tgt_values, hole=0.4,
            marker=dict(colors=tu_colors),
            textposition="inside", textinfo="percent+label",
            hovertemplate="<b>%{label}</b><br>"
                          "<i>₽:</i> %{value:,.0f} ₽<br>"
                          "<i>%:</i> %{percent}<extra></extra>",
            pull=[0.04],
        )])
        fig_tgt.update_layout(
            title={"text": "Целевая структура обеспечения", "font": {"size": 15}, "x": 0.5},
            height=400, showlegend=False, margin=dict(l=10, r=10, t=50, b=70))
        fig_tgt.update_traces(textfont_size=11)

        c1, c2 = st.columns(2)
        with c1: st.plotly_chart(fig_cur, use_container_width=True)
        with c2: st.plotly_chart(fig_tgt, use_container_width=True)

        # ── Легенда с рублями (всегда видна) ──
        lcol1, lcol2 = st.columns(2)
        with lcol1:
            st.markdown(
                f"<div style='border:1px solid #ddd;border-radius:8px;"
                f"padding:10px;margin-top:8px;background:#fafafa'>"
                f"<b>📊 Текущая (₽)</b><br>"
                f"Номинал: <b>{cur_nominal:,.2f} ₽</b><br>"
                f"• ГО (QUIK): <span style='color:#d35400'>●</span> "
                f"{cur_go:,.2f} ₽ ({cur_go/cur_nominal*100:.1f}%)<br>"
                f"• Буфер ({buffer_pct:.0f}%): <span style='color:#f39c12'>●</span> "
                f"{cur_buffer:,.2f} ₽ ({cur_buffer/cur_nominal*100:.1f}%)<br>"
                f"• Ликвидность: <span style='color:#2ecc71'>●</span> "
                f"{cur_distributed:,.2f} ₽ ({cur_distributed/cur_nominal*100:.1f}%)</div>",
                unsafe_allow_html=True)
        with lcol2:
            st.markdown(
                f"<div style='border:1px solid #ddd;border-radius:8px;"
                f"padding:10px;margin-top:8px;background:#fafafa'>"
                f"<b>🎯 Целевая (₽)</b><br>"
                f"Номинал: <b>{tgt_nominal:,.2f} ₽</b><br>"
                f"• ГО ({target_contracts} конт. × {go_per_contract:,.2f}): "
                f"<span style='color:#d35400'>●</span> "
                f"{tgt_go:,.2f} ₽ ({tgt_go/tgt_nominal*100:.1f}%)<br>"
                f"• Буфер ({buffer_pct:.0f}%): "
                f"<span style='color:#f39c12'>●</span> {tgt_buffer:,.2f} ₽ "
                f"({tgt_buffer/tgt_nominal*100:.1f}%)<br>"
                f"• Ликвидность: <span style='color:#2ecc71'>●</span> "
                f"{tgt_distributed:,.2f} ₽ "
                f"({tgt_distributed/tgt_nominal*100:.1f}%)</div>",
                unsafe_allow_html=True)

        # ── Рекомендуемые сделки по фьючерсам ──
        if futures_recs:
            st.markdown("### 📋 Рекомендуемые сделки по фьючерсам")
            rec_rows = []
            for rec in futures_recs:
                rec_rows.append({
                    "Тикер": rec["sec_code"],
                    "Текущее кол-во": rec["current_qty"],
                    "Целевое кол-во": rec["target_qty"],
                    "Действие": rec["action"],
                    "Изменение контрактов": rec["qty_change"]
                })
            df_rec = pd.DataFrame(rec_rows)
            st.dataframe(df_rec.style.map(
                lambda v: "background:#27ae60;color:#000000;font-weight:bold;" if v == "Покупка" else
                ("background:#e74c3c;color:#000000;font-weight:bold;" if v == "Продажа" else ""),
                subset=["Действие"]),
                use_container_width=True, hide_index=True)

    # ═══════════════════════════════════════════════════════════════
    # СВОДНАЯ ТАБЛИЦА ПО КЛАССАМ
    # ═══════════════════════════════════════════════════════════════
    st.divider()
    st.subheader("📊 Сводная таблица по классам")

    rows = []
    for c in cl:
        d = result["class_devs"].get(c, {})
        cs = result["class_store"].get(c, {})
        # Стоимость — уже число, формируем строку
        val_str = f"{cs.get('total', 0):,.2f}"
        action = d.get("action", "")
        # Преобразуем buy/sell в цветные BYE/SELL (стиль применяется через style.map)
        if action == "buy":
            action_display = "BUY"
        elif action == "sell":
            action_display = "SELL"
        else:
            action_display = ""
        rows.append({"Класс": c,
                     "Стоимость (руб.)": val_str,
                     "Текущий %": f"{cw.get(c, 0):.2f}",
                     "Целевой %": f"{result['classes_data'].get(c, 0):.2f}",
                     "Отклонение": f"{d.get('deviation', 0):+.2f}",
                     "Объём сделки (руб.)": f"{d.get('volume', 0):,.2f}",
                     "Действие": action_display})
    df_cl = pd.DataFrame(rows)
    st.dataframe(df_cl.style.map(_row_action_style, subset=["Действие"]),
                 use_container_width=True, hide_index=True, height=300)

    # ═══════════════════════════════════════════════════════════════
    # ДЕТАЛИЗАЦИЯ ПО КЛАССАМ
    # ═══════════════════════════════════════════════════════════════
    st.divider()
    st.subheader("🔍 Детализация по классам")

    for c in cl:
        cs = result["class_store"].get(c, {})
        if not cs.get("tickers"): continue
        td = {(kc, k): v for (kc, k), v in result["ticker_devs"].items() if kc == c}
        sk_items = [(kc, k) for (kc, k) in result["skipped"].keys() if kc == c]

        buys = sum(1 for v in td.values() if v["action"] == "Покупка")
        sells = sum(1 for v in td.values() if v["action"] == "Продажа")
        exp_label = f"**{c}** — {cs.get('total', 0):,.0f} руб. "
        if td:
            exp_label += f"[{buys} <span style='color:#27ae60;font-weight:bold;'>BYE</span> / {sells} <span style='color:#e74c3c;font-weight:bold;'>SELL</span>]"
        exp_label += f" ({len(cs['tickers'])} тикеров)"

        # Используем markdown для заголовка с HTML, затем expander для контента
        st.markdown(exp_label, unsafe_allow_html=True)
        with st.expander("Детали", expanded=False):
            if td:
                trows = []
                for (_, tkr), dv in td.items():
                    info = cs["tickers"].get(tkr, {})
                    qty, unit = info.get("qty", ""), info.get("unit", "")
                    price = info.get("price", 0)
                    trows.append({
                        "Тикер": tkr, "Название": info.get("name", "-"),
                        "Кол-во": f"{qty:,} {unit}" if qty is not None else "-",
                        "Цена": f"{price:,.2f}" if price > 0 else "-",
                        "Стоимость": f"{dv['cur_val']:,.2f}",
                        "Вес в классе": f"{dv['cur_wt']:.2f}%",
                        "Целевой вес": f"{dv['tgt_wt']:.2f}%",
                        "Откл.": f"{dv['diff_wt']:+.2f}",
                        "Сделка": dv["action"],
                        "Кол-во к сделке": dv["qty_change"] if dv["qty_change"] != 0 else "—"})
                df_t = pd.DataFrame(trows)
                st.dataframe(
                    df_t.style.map(_action_text_style, subset=["Сделка"]),
                    use_container_width=True, hide_index=True)
            if sk_items:
                ticker_names = [f"[{k[0]}, {k[1]}]" for k in sk_items]
                st.warning(f"Пропущены (нет целей): {', '.join(ticker_names)}")

    # ═══════════════════════════════════════════════════════════════
    # РЕКОМЕНДАЦИИ
    # ═══════════════════════════════════════════════════════════════
    st.divider()
    st.subheader("💡 Рекомендуемые сделки")

    buy_rows, sell_rows = [], []
    for (cn, tkr), dv in result["ticker_devs"].items():
        if dv["action"] == "Покупка":
            buy_rows.append({"Тикер": tkr, "Класс": cn,
                             "Действие": "ПОКУПКА BYE",
                             "Разница (руб.)": f"{abs(dv['diff']):,.2f}",
                             "Кол-во": dv["qty_change"]})
        elif dv["action"] == "Продажа":
            sell_rows.append({"Тикер": tkr, "Класс": cn,
                              "Действие": "ПРОДАЖА SELL",
                              "Разница (руб.)": f"{abs(dv['diff']):,.2f}",
                              "Кол-во": dv["qty_change"]})

    if buy_rows:
        st.markdown("##### <span style='color:#27ae60;font-weight:bold;'>BYE</span> Покупка", unsafe_allow_html=True)
        st.dataframe(pd.DataFrame(buy_rows).style.map(
            lambda val: "background:#27ae60;color:#000000;font-weight:bold;" if val == "ПОКУПКА BYE" else
            ("background:#27ae60;color:#000000;font-weight:bold;" if val == "BYE" else ""),
            subset=["Действие"]), use_container_width=True, hide_index=True,
            height=min(len(buy_rows) * 38 + 60, 250))
    if sell_rows:
        st.markdown("##### <span style='color:#e74c3c;font-weight:bold;'>SELL</span> Продажа", unsafe_allow_html=True)
        st.dataframe(pd.DataFrame(sell_rows).style.map(
            lambda val: "background:#e74c3c;color:#000000;font-weight:bold;" if val == "ПРОДАЖА SELL" else
            ("background:#e74c3c;color:#000000;font-weight:bold;" if val == "SELL" else ""),
            subset=["Действие"]), use_container_width=True, hide_index=True,
            height=min(len(sell_rows) * 38 + 60, 250))
    if not buy_rows and not sell_rows:
        st.info("Портфель сбалансирован. Изменений не требуется.")

    # Таблица фьючерсов
    if fc["per_future"]:
        st.divider()
        st.subheader("📋 Фьючерсы — детально")
        fut_rows = []
        for f in fc["per_future"]:
            buf_for_fut = round(f["notional"] * float(targets.get("futures_buffer_pct", DEFAULT_FUTURES_BUFFER_PCT)) / 100, 2)
            fut_rows.append({
                "Тикер": f["sec_code"], "Название": f["name"],
                "Кол-во": f["qty"], "Номинал": f"{f['notional']:,.2f} ₽",
                "ГО": f"{f['go']:,.2f} ₽", "ГО %": f"{f['margin_pct']:.1f}%",
                f"Буфер ({float(targets.get('futures_buffer_pct', DEFAULT_FUTURES_BUFFER_PCT))}%)" : f"{buf_for_fut:,.2f} ₽",
            })
        st.dataframe(pd.DataFrame(fut_rows), use_container_width=True, hide_index=True)


# ════════════════════════════════════════════════════════════════════════════
# СТРАНИЦА 2: РЕДАКТОР ЦЕЛЕЙ
# ════════════════════════════════════════════════════════════════════════════

def page_targets_editor():
    st.title("🎯 Редактор целевых весов")
    st.caption("Управление распределением по классам активов, инструментами и настройками фьючерсов.")

    if "targets" not in st.session_state: st.session_state.targets = load_targets()
    # Загрузка данных редактора
    if "parsed" not in st.session_state: st.session_state.parsed = None
    if "targets" not in st.session_state: st.session_state.targets = load_targets()
    
    # Инициализация состояния для отслеживания изменений
    if "targets_edited" not in st.session_state:
        st.session_state.targets_edited = False
    if "initial_targets" not in st.session_state:
        st.session_state.initial_targets = load_targets()

    tgt = st.session_state.targets
    parsed = st.session_state.parsed

    editor_classes = dict(tgt.get("classes", {}))
    editor_tickers = tgt.get("tickers", {}).copy()
    
    overlay_classes = tgt.get("futures_overlay_classes", OVERLAY_DEFAULT_CLASSES[:])
    buffer_pct = float(tgt.get("futures_buffer_pct", DEFAULT_FUTURES_BUFFER_PCT))

    # ── Секция 0: Параметры фьючерсов ──
    st.subheader("⚙️ Параметры фьючерсов")
    with st.expander("Настройки ГО и оверлея", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            buffer_pct = st.number_input(
                "🛡 Процент буфера от номинала (%)",
                min_value=0.0, max_value=50.0, value=buffer_pct, step=0.5,
                format="%.1f", key="edit_buf_pct",
                on_change=lambda: setattr(st.session_state, 'targets_edited', True))
        with c2:
            st.markdown("**Overlay-классы** (куда распределяется излишек ликвидности):")
            overlay_classes = st.multiselect(
                "", options=OVERLAY_DEFAULT_CLASSES,
                default=overlay_classes, key="edit_overlay_cls",
                on_change=lambda: setattr(st.session_state, 'targets_edited', True))
        with c3:
            st.empty()

    # ── Секция 1: Распределение по классам ──
    st.divider()
    st.subheader("1. Распределение по классам активов")
    st.caption("Сумма должна быть равна 100%")

    cols_c = st.columns(4)
    idx = 0
    for cls_name in sorted(editor_classes.keys()):
        ci = idx % 4
        val = cols_c[ci].number_input(
            f"{_get_class_icon(cls_name)} {cls_name}",
            min_value=0.0, max_value=100.0,
            value=float(editor_classes.get(cls_name, 0)), step=0.5,
            label_visibility="visible", key=f"tc_{cls_name}",
            on_change=lambda: setattr(st.session_state, 'targets_edited', True))
        editor_classes[cls_name] = val
        idx += 1

    # Добавить новый класс
    new_class_name = st.text_input("➕ Новый класс:", placeholder="Название нового класса", key="new_class_input")
    if new_class_name:
        if new_class_name not in editor_classes:
            st.session_state._pending_new_class = new_class_name

    class_sum = sum(editor_classes.values())
    status_msg = f"Сумма: **{class_sum:.1f}%**"
    if abs(class_sum - 100.0) <= 0.1:
        st.success(f"✅ {status_msg}")
    else:
        st.error(f"❌ {status_msg} — должно быть 100.0%")

    # Кнопки управления классами
    btn_row = st.columns(3)
    with btn_row[0]:
        if st.button("💾 Сохранить классы", use_container_width=True):
            if abs(class_sum - 100.0) <= 0.1:
                if hasattr(st.session_state, '_pending_new_class') and st.session_state._pending_new_class:
                    nc = st.session_state._pending_new_class
                    del st.session_state._pending_new_class
                    editor_classes[nc] = 0.0
                # Сохраняем классы, сохраняя тикеры из session_state
                current = load_targets()
                current["classes"] = editor_classes
                # Важно: сохраняем текущие тикеры из session_state, а не из файла
                current["tickers"] = st.session_state.targets.get("tickers", {})
                st.session_state.targets = current
                st.session_state.targets_edited = False  # Сброс флага изменений
                save_targets(current); st.rerun()
    with btn_row[1]:
        if st.button("🔄 Сбросить к дефолту", use_container_width=True):
            _default_targets(); st.rerun()

    # ── Секция 2: Инструменты внутри классов ──
    st.divider()
    st.subheader("2. Инструменты внутри классов")
    st.caption("Укажите тикеры и их вес в % внутри класса. Если список пуст — класс проверяется целиком без детализации.")

    for cls_name in sorted(editor_classes.keys()):
        ct = editor_tickers.get(cls_name, {})
        has_tickers = bool(ct)

        with st.expander(f"{_get_class_icon(cls_name)} {cls_name} ({sum(ct.values()):.0f}%)", expanded=not has_tickers):
            keys = sorted(ct.keys())
            if keys:
                st.markdown("**Текущие инструменты:**")
                for tk in keys:
                    row = st.columns(4)
                    with row[0]:
                        if st.button("🗑", key=f"del_{cls_name}_{tk}"):
                            del editor_tickers.setdefault(cls_name, {})[tk]
                            st.session_state.targets["tickers"] = editor_tickers
                            st.rerun()
                    with row[1]:
                        st.write(tk)
                    with row[2]:
                        rename_ok = False
                        nn = st.text_input("", value=tk, key=f"rename_{cls_name}_{tk}",
                                           label_visibility="collapsed", max_chars=20)
                        if nn and nn != tk:
                            editor_tickers[cls_name][nn] = editor_tickers[cls_name].pop(tk)
                            st.session_state.targets["tickers"] = editor_tickers
                            st.rerun()
                    with row[3]:
                        tv = st.number_input(
                            "", min_value=0.0, max_value=100.0,
                            value=float(ct[tk]), step=0.5, format="%.1f",
                            key=f"tc_tick_{cls_name}_{tk}", label_visibility="visible")
                        # Обновляем данные в session_state, чтобы они сохранялись
                        editor_tickers[cls_name][tk] = tv
                        st.session_state.targets["tickers"] = editor_tickers

                s = sum(editor_tickers[cls_name].values())
                if abs(s - 100.0) > 0.1:
                    st.warning(f"Сумма: {s:.1f}% → авто-нормализуется при сохранении")
            else:
                st.info("Нет заданных инструментов. Класс проверяется по общему весу без детализации.")

            # Добавление нового инструмента
            st.markdown("**Добавить инструмент:**")
            inp_row = st.columns(4)
            with inp_row[0]:
                new_tk = st.text_input("Тикер", placeholder="SU26207RMFS9",
                                       label_visibility="visible", key=f"add_tk_{cls_name}")
            with inp_row[1]:
                new_nm = st.text_input("Название", placeholder="ОФЗ 26207",
                                       label_visibility="visible", key=f"add_nm_{cls_name}")
            with inp_row[2]:
                new_wt = st.number_input("Вес %", min_value=0.0, max_value=100.0,
                                         value=0.0, step=0.5, key=f"add_wt_{cls_name}",
                                         format="%.1f")
            with inp_row[3]:
                if st.button("<- Добавить введенное", use_container_width=True, key=f"add_btn_{cls_name}"):
                    if new_tk:
                        if cls_name not in editor_tickers: editor_tickers[cls_name] = {}
                        editor_tickers[cls_name][new_tk] = new_wt
                        st.session_state.targets["tickers"] = editor_tickers
                        st.rerun()

            # Подтяжка из портфеля
            if parsed:
                port_tickers = [p["sec_code"] for p in parsed["positions"]
                                if classify_asset(p["class_code"], p["sec_code"]) == cls_name]
                fut_tickers = [f["sec_code"] for f in parsed["futures"]]
                available = list(dict.fromkeys(port_tickers + fut_tickers))
                if available and any(t not in ct for t in available):
                    st.caption(f"Из портфеля доступны: {', '.join(available)}")
                    if st.button("📥 Подтянуть из портфеля", use_container_width=True, key=f"fetch_{cls_name}"):
                        existing = set(editor_tickers.setdefault(cls_name, {}).keys())
                        for t in available:
                            if t not in existing:
                                editor_tickers[cls_name][t] = 0.0
                                existing.add(t)
                        st.session_state.targets["tickers"] = editor_tickers
                        st.rerun()

    # ── Кнопки сохранения всей секции B ──
    st.divider()
    btn_cols = st.columns(4)
    with btn_cols[0]:
        if st.button("💾 Сохранить все цели", use_container_width=True):
            # Используем введённые пользователем веса, нормализуя только если сумма ≠ 100%
            final_tickers = {}
            for cn, td in editor_tickers.items():
                if not td:
                    continue
                # Считаем сумму текущих весов
                total = sum(td.values())
                if abs(total - 100.0) > 0.01:
                    # Нормализуем пропорционально введённым весам
                    factor = 100.0 / total
                    final_tickers[cn] = {k: round(v * factor, 2) for k, v in td.items()}
                    # Корректируем последний, чтобы сумма была ровно 100%
                    ks = list(final_tickers[cn].keys())
                    diff = 100.0 - sum(final_tickers[cn].values())
                    if ks:
                        final_tickers[cn][ks[-1]] = round(final_tickers[cn][ks[-1]] + diff, 2)
                else:
                    # Веса уже в сумме дают 100% — оставляем как есть
                    final_tickers[cn] = {k: round(v, 2) for k, v in td.items()}

            final_tgt = {
                "classes": editor_classes,
                "tickers": final_tickers,
                "futures_overlay_classes": overlay_classes,
                "futures_buffer_pct": buffer_pct,
            }
            st.session_state.targets = final_tgt
            if save_targets(final_tgt):
                st.success("✅ Все цели сохранены! Перейдите на страницу Анализ.")
                st.session_state.targets_edited = False  # Сброс флага изменений
                st.session_state._needs_recalc = True
                st.rerun()
    with btn_cols[1]:
        if st.button("📂 Загрузить targets.json", use_container_width=True):
            loaded = load_targets()
            st.session_state.targets = loaded; st.rerun()
    with btn_cols[2]:
        if st.button("📥 Подтянуть ВСЕ из портфеля", use_container_width=True):
            new = build_ticker_defaults_from_portfolio(parsed if parsed else {})
            st.session_state.targets = new; st.rerun()
    with btn_cols[3]:
        if st.button("📤 Экспорт targets.json", use_container_width=True):
            d = st.download_button(
                label="Скачать JSON",
                data=json.dumps(st.session_state.targets, ensure_ascii=False, indent=2, default=str).encode(),
                file_name="targets.json",
                mime="application/json")


# ── helpers ──
_CLASS_ICONS = {
    "ОФЗ": "🏛️", "Корп. облигации": "🏢", "Акции РФ": "📈",
    "ETF": "💎", "Золото": "🥇", "Фьючерсы": "📊",
    "Ликвидность": "💵", "Ликв. для фьючерсов": "📊",
}

def _get_class_icon(cls_name):
    if cls_name in _CLASS_ICONS:
        return _CLASS_ICONS[cls_name]
    return "📦"


def _targets_equal(targets1, targets2):
    """Сравнивает два набора целей на равенство"""
    if not targets1 or not targets2:
        return targets1 == targets2
    
    # Сравниваем классы
    classes1 = targets1.get("classes", {})
    classes2 = targets2.get("classes", {})
    if classes1 != classes2:
        return False
    
    # Сравниваем тикеры
    tickers1 = targets1.get("tickers", {})
    tickers2 = targets2.get("tickers", {})
    if tickers1 != tickers2:
        return False
    
    # Сравниваем параметры фьючерсов
    futures_overlay1 = targets1.get("futures_overlay_classes", [])
    futures_overlay2 = targets2.get("futures_overlay_classes", [])
    if futures_overlay1 != futures_overlay2:
        return False
    
    buffer1 = targets1.get("futures_buffer_pct", DEFAULT_FUTURES_BUFFER_PCT)
    buffer2 = targets2.get("futures_buffer_pct", DEFAULT_FUTURES_BUFFER_PCT)
    if buffer1 != buffer2:
        return False
    
    return True

# ════════════════════════════════════════════════════════════════════════════
# MAIN — навигация
# ════════════════════════════════════════════════════════════════════════════

page_names = {"Анализ": page_analysis, "Редактор целей": page_targets_editor}
pages = {name: fn for name, fn in page_names.items()}

# ════════════════════════════════════════════════════════════════════════════
# MAIN — навигация
# ════════════════════════════════════════════════════════════════════════════

page_names = {"Анализ": page_analysis, "Редактор целей": page_targets_editor}
pages = {name: fn for name, fn in page_names.items()}

def app():
    # Инициализация состояния
    if "initial_targets" not in st.session_state:
        st.session_state.initial_targets = load_targets()
    if "targets" not in st.session_state:
        st.session_state.targets = load_targets()
    if "targets_edited" not in st.session_state:
        st.session_state.targets_edited = False
    
    nav_choice = st.sidebar.radio(
        "📑 Навигация",
        options=list(pages.keys()),
        index=0,
        help="Выберите страницу")
    
    # Проверяем, если пользователь пытается перейти с редактора целей на анализ
    # и есть несохраненные изменения
    if (nav_choice == "Анализ" and
        st.session_state.targets_edited):
        # Показываем предупреждение
        st.warning("У вас есть несохраненные изменения в редакторе целей!")
        st.info("Пожалуйста, сохраните изменения нажав кнопку 'Сохранить все цели' или отмените изменения.")
        
        # Кнопки для подтверждения перехода
        col1, col2 = st.columns(2)
        with col1:
            if st.button("❌ Отменить изменения"):
                st.session_state.targets = st.session_state.initial_targets.copy()
                st.session_state.targets_edited = False
                st.rerun()
        with col2:
            if st.button("✅ Продолжить без сохранения"):
                st.session_state.targets = st.session_state.initial_targets.copy()
                st.session_state.targets_edited = False
                pages[nav_choice]()
                return
    else:
        pages[nav_choice]()

if __name__ == "__main__":
    app()
