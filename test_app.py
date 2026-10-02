"""
Тесты для парсера портфеля и расчёта ребалансировки.

Запуск: python test_app.py

Проверяет:
  1. Парсинг тестовых данных из test_portfolio.txt
  2. Корректность классификации активов
  3. Расчёт equity по формуле пользователя
  4. Отклонения и рекомендации
  5. Обработка пустого портфеля / секций
  6. Работа с targets.json
  7. Графики Plotly генерируются без ошибок
"""

import json
import os
import sys
from pathlib import Path

# Добавляем папку с приложением в PATH
APP_DIR = Path(__file__).parent
sys.path.insert(0, str(APP_DIR))

from app import (
    parse_portfolio,
    classify_asset,
    calc_portfolio,
    load_targets,
    save_targets,
    build_ticker_defaults_from_portfolio,
    fmt_pct,
    make_pie_chart,
    make_bar_deviations,
)
from app import TEST_DATA_FILE, PORTFOLIO_FILE, TARGETS_FILE


# ═══════════════════════════════════════════════════════════════════════════
# Утилиты тестирования
# ═══════════════════════════════════════════════════════════════════════════


def ok(msg):
    print(f"  [OK] {msg}")


def fail(msg, expected=None, actual=None):
    print(f"  [FAIL] {msg}")
    if expected is not None:
        print(f"       expected: {expected}")
    if actual is not None:
        print(f"       actual:   {actual}")
    return False


passed = 0
failed = 0


def assert_eq(name, exp, got, tol=0):
    global passed, failed
    if tol > 0:
        if abs(exp - got) < tol:
            ok(f"{name}: {got:.2f} ≈ {exp:.2f}")
            passed += 1
        else:
            fail(f"{name}", f"{exp:.2f} ±{tol}", f"{got:.2f}")
            failed += 1
    else:
        if exp == got:
            ok(f"{name}: {got}")
            passed += 1
        else:
            fail(f"{name}", repr(exp), repr(got))
            failed += 1


# ═══════════════════════════════════════════════════════════════════════════
# ТЕСТ 1: ПАРСЕР — ФОНДОВЫЙ РЫНОК
# ═══════════════════════════════════════════════════════════════════════════

print("=" * 70)
print("ТЕСТ 1: Парсер — фондовый рынок")
print("=" * 70)

if not TEST_DATA_FILE.exists():
    print("  ⚠️ Файл test_portfolio.txt не найден, пропуск.")
else:
    with open(TEST_DATA_FILE, encoding="utf-8") as f:
        text = f.read()

    data = parse_portfolio(text)

    assert_eq("Позиций найдено", 26, len(data["positions"]))
    assert_eq("fund_total", 1046822.65, data["fund_total"], tol=1.0)

    # Проверяем конкретные тикеры
    sec_codes = [p["sec_code"] for p in data["positions"]]
    assert_eq("LQDT есть в позициях", True, "LQDT" in sec_codes)
    assert_eq("SBER есть в позициях", True, "SBER" in sec_codes)
    assert_eq("SU26207RMFS9 есть", True, "SU26207RMFS9" in sec_codes)

    # LQDT должен быть TQBR class_code и ETF classification
    lqdt_pos = next((p for p in data["positions"] if p["sec_code"] == "LQDT"), None)
    assert_eq("LQDT class_code", "TQBR", lqdt_pos["class_code"] if lqdt_pos else None)
    if lqdt_pos:
        assert_eq("LQDT qty", 30001, lqdt_pos["qty"])
        assert_eq("LQDT value", 62741.09, lqdt_pos["value"], tol=1.0)

    # SBER
    sber_pos = next((p for p in data["positions"] if p["sec_code"] == "SBER"), None)
    assert_eq("SBER class_code", "TQBR", sber_pos["class_code"] if sber_pos else None)
    if sber_pos:
        assert_eq("SBER value", 280.57, sber_pos["value"], tol=0.1)

    # ОФЗ
    ofz = next((p for p in data["positions"] if p["sec_code"] == "SU26207RMFS9"), None)
    assert_eq("ОФЗ class_code", "TQOB", ofz["class_code"] if ofz else None)
    if ofz:
        assert_eq("ОФЗ qty", 190, ofz["qty"])
        assert_eq("ОФЗ value", 187037.90, ofz["value"], tol=1.0)

    # Корп облигации
    corp = next((p for p in data["positions"] if p["sec_code"] == "RU000A102556"), None)
    assert_eq("Корп об class_code", "TQCB", corp["class_code"] if corp else None)

    print()


# ═══════════════════════════════════════════════════════════════════════════
# ТЕСТ 2: ПАРСЕР — СВОБОДНЫЕ СРЕДСТВА
# ═══════════════════════════════════════════════════════════════════════════

print("=" * 70)
print("ТЕСТ 2: Парсер — свободные средства")
print("=" * 70)

data = parse_portfolio(text)

gold_items = [c for c in data["free_cash"] if c["type"] == "gold"]
sur_items = [c for c in data["free_cash"] if c["type"] == "cash"]

assert_eq("Золото items", 1, len(gold_items))
if gold_items:
    assert_eq("Золото граммы", 1.0, gold_items[0]["grams"], tol=0.01)
    assert_eq("Золото цена/г", 11717.00, gold_items[0]["price_per_g"], tol=0.01)
    assert_eq("Золото RUB", 11717.00, gold_items[0]["value_rub"], tol=0.01)

assert_eq("SUR items", 1, len(sur_items))
if sur_items:
    assert_eq("SUR amount", 377112.78, sur_items[0]["amount"], tol=0.01)

assert_eq("cash_total (Итого)", 388829.78, data["cash_total"], tol=0.01)

print()


# ═══════════════════════════════════════════════════════════════════════════
# ТЕСТ 3: ПАРСЕР — ФЬЮЧЕРСЫ
# ═══════════════════════════════════════════════════════════════════════════

print("=" * 70)
print("ТЕСТ 3: Парсер — фьючерсы")
print("=" * 70)

fut_data = data["futures"]
assert_eq("Фьючерсов", 1, len(fut_data))
if fut_data:
    assert_eq("NGV6 ticker", "NGV6", fut_data[0]["sec_code"])
    assert_eq("NGV6 qty", 9, fut_data[0]["qty"])
    assert_eq("NGV6 notional", 231220.30, fut_data[0]["notional"], tol=0.01)
    assert_eq("NGV6 go", 62451.54, fut_data[0]["go"], tol=0.01)

assert_eq("notional_total", 231220.30, data["notional_total"], tol=0.01)
assert_eq("go_total", 62451.54, data["go_total"], tol=0.01)
assert_eq("portfolio_total", 1435652.43, data["portfolio_total"], tol=0.01)

print()


# ═══════════════════════════════════════════════════════════════════════════
# ТЕСТ 4: КЛАССИФИКАЦИЯ АКТИВОВ
# ═══════════════════════════════════════════════════════════════════════════

print("=" * 70)
print("ТЕСТ 4: Классификация активов")
print("=" * 70)

assert_eq("classify TQOB", "ОФЗ", classify_asset("TQOB", "SU26207RMFS9"))
assert_eq("classify TQCB", "Корп. облигации", classify_asset("TQCB", "RU000A102556"))
assert_eq("classify TQBR+SBER", "Акции РФ", classify_asset("TQBR", "SBER"))
assert_eq("classify TQBR+LQDT(ETF)", "ETF", classify_asset("TQBR", "LQDT"))
assert_eq("classify TQTF", "ETF", classify_asset("TQTF", "TMUB"))
assert_eq("classify unknown", "UNKNOWN", classify_asset("UNKNOWN", "XXXX"))
assert_eq("classify empty", "Другое", classify_asset("", "SBER"))

print()


# ═══════════════════════════════════════════════════════════════════════════
# ТЕСТ 5: РАСЧЁТ ПОРТФЕЛЯ
# ═══════════════════════════════════════════════════════════════════════════

print("=" * 70)
print("ТЕСТ 5: Расчёт портфеля")
print("=" * 70)

targets = {
    "classes": {
        "ОФЗ": 20.0,
        "Корп. облигации": 20.0,
        "Акции РФ": 5.0,
        "ETF": 5.0,
        "Золото": 10.0,
        "Фьючерсы": 15.0,
        "Денежные средства": 25.0,
    },
    "tickers": {
        "ОФЗ": {"SU26207RMFS9": 40, "SU26212RMFS9": 30, "SU26232RMFS7": 30},
        "Корп. облигации": {
            "RU000A102556": 10, "RU000A104A05": 10,
            "RU000A105M91": 10, "RU000A106UL6": 10,
            "RU000A1070A3": 10, "RU000A107217": 10,
            "RU000A107225": 10, "RU000A1075R6": 10,
        },
        "Акции РФ": {"SBER": 100},
        "ETF": {"LQDT": 100},
        "Фьючерсы": {"NGV6": 100},
    },
}

result = calc_portfolio(data, targets)

# equity = fund_total + gold_val + sur_val + go
expected_equity = data["fund_total"] + result["gold_val"] + result["sur_val"] + result["go"]
assert_eq("equity formula", expected_equity, result["equity"])
assert_eq("equity ~ 1435652.43", 1435652.43, result["equity"], tol=1.0)

# Проверка классов
ok(f"equity={result['equity']:,.2f}")
ok(f"gold_val={result['gold_val']:,.2f}")
ok(f"sur_val={result['sur_val']:,.2f}")
ok(f"notional={result['notional']:,.2f}")
ok(f"go={result['go']:,.2f}")

# Веса классов должны суммироваться примерно до 100%
weights_sum = sum(result["class_weights"].values())
assert_eq("Сумма весов классов %", 100.0, weights_sum, tol=0.5)

# Должны быть предупреждения о корпоративных облигациях без целей
warn_count = len(result["warnings"])
assert_eq("Предупреждения (корп облигации)", 16, warn_count)

print()


# ═══════════════════════════════════════════════════════════════════════════
# ТЕСТ 6: ДЕТАЛИЗАЦИЯ ПО ТИКЕРАМ
# ═══════════════════════════════════════════════════════════════════════════

print("=" * 70)
print("ТЕСТ 6: Детализация по тикерам")
print("=" * 70)

ticker_devs = result["ticker_devs"]
skipped = result["skipped"]

# Золото должно быть skipped
assert_eq("GLD skipped", True, ("Золото", "GLD") in skipped)

# SUR должен быть skipped
assert_eq("SUR skipped", True, ("Денежные средства", "SUR") in skipped)

# ОФЗ должны быть в ticker_devs
for oof_of in ["SU26207RMFS9", "SU26212RMFS9", "SU26232RMFS7"]:
    key = ("ОФЗ", oof_of)
    assert_eq(f"ОФЗ {oof_of} в ticker_devs", True, key in ticker_devs,
              actual=key in ticker_devs)
    if key in ticker_devs:
        td = ticker_devs[key]
        assert_eq(f"ОФЗ {oof_of} action", "Покупка" if td["diff"] > 0.5 else ("Продажа" if td["diff"] < -0.5 else "Без изменений"), td["action"])

# Акции РФ
key = ("Акции РФ", "SBER")
if key in ticker_devs:
    sber_td = ticker_devs[key]
    assert_eq("SBER diff != 0", True, sber_td["diff"] != 0)
    ok(f"SBER dev_in_class: {sber_td['diff_wt']:+.2f}%")

# ETF
key = ("ETF", "LQDT")
if key in ticker_devs:
    lqdt_td = ticker_devs[key]
    assert_eq("LQDT weight_in_class", 100.0, lqdt_td["cur_wt"], tol=0.5)

# Корп облигации — все skipped
corp_skipped = {k: v for k, v in skipped.items() if k[0] == "Корп. облигации"}
assert_eq("Корп. облигации skipped", 16, len(corp_skipped))

# Фьючерсы
key = ("Фьючерсы", "NGV6")
assert_eq("NGV6 в ticker_devs", True, key in ticker_devs, actual=key in ticker_devs)

print()


# ═══════════════════════════════════════════════════════════════════════════
# ТЕСТ 7: ПУСТОЙ / НЕПОЛНЫЙ ПОРТФЕЛЬ
# ═══════════════════════════════════════════════════════════════════════════

print("=" * 70)
print("ТЕСТ 7: Пустой / неполный портфель")
print("=" * 70)

empty_text = """
====================================================================================================
ФОНДОВЫЙ РЫНОК   Счёт: L01-00000F00   Фирма: MC0002500000   Лимит: T1
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

empty_data = parse_portfolio(empty_text)
assert_eq("Пустая: positions", 0, len(empty_data["positions"]))
assert_eq("Пустая: fund_total", 0.0, empty_data["fund_total"])
assert_eq("Пустая: portfolio_total", 0.0, empty_data["portfolio_total"])
assert_eq("Пустая: cash_total", 0.0, empty_data["cash_total"])

# Без фьючерсов
assert_eq("Пустая: futures", 0, len(empty_data["futures"]))
assert_eq("Пустая: notional_total", 0.0, empty_data["notional_total"])
assert_eq("Пустая: go_total", 0.0, empty_data["go_total"])

# Расчёт с нулевым equity
empty_result = calc_portfolio(empty_data, targets)
assert_eq("Пустой: equity", 0.0, empty_result["equity"])

print()


# ═══════════════════════════════════════════════════════════════════════════
# ТЕСТ 8: БИТЫ ЦЕЛЕВЫХ ВЕСОВ (targets.json)
# ═══════════════════════════════════════════════════════════════════════════

print("=" * 70)
print("ТЕСТ 8: targets.json загрузка / сохранение")
print("=" * 70)

# Сохраняем тестовый файл
test_tgt = {"classes": {"ОФЗ": 50.0, "РР": 50.0}, "tickers": {"ОФЗ": {"AAAA": 100}}}
save_targets(test_tgt)

loaded = load_targets()
assert_eq("load classes OK", dict, type(loaded.get("classes")))
assert_eq("load classes count", 2, len(loaded["classes"]))

# Генерация defaults
defaults = {
    "ОФЗ": 20.0, "Корп. облигации": 10.0, "Акции РФ": 5.0,
    "ETF": 5.0, "Золото": 10.0, "Фьючерсы": 15.0, "Денежные средства": 35.0,
}
sum_check = sum(defaults.values())
assert_eq("Default sum", 100.0, sum_check)

print()


# ═══════════════════════════════════════════════════════════════════════════
# ТЕСТ 9: ГЕНЕРАЦИЯ ДЕФОЛТОВ ТИКЕРОВ ИЗ ПОРТФЕЛЯ
# ═══════════════════════════════════════════════════════════════════════════

print("=" * 70)
print("ТЕСТ 9: Генерация тикеров из портфеля")
print("=" * 70)

# Восстанавливаем стандартный targets.json
_ = load_targets()  # загружаем дефолты

new_targets = build_ticker_defaults_from_portfolio(data)
ticker_dict = new_targets.get("tickers", {})

# ОФЗ должны появиться
assert_eq("ОФЗ в tickers", True, "ОФЗ" in ticker_dict)
if "ОФЗ" in ticker_dict:
    oof_keys = list(ticker_dict["ОФЗ"].keys())
    assert_eq("ОФЗ тикеров 3", 3, len(oof_keys))
    sum_oof = sum(ticker_dict["ОФЗ"].values())
    assert_eq("ОФЗ сумма", 100.0, sum_oof, tol=0.01)

# Фьючерсы должны появиться
assert_eq("Фьючерсы в tickers", True, "Фьючерсы" in ticker_dict)

# Акции РФ должны содержать SBER
if "Акции РФ" in ticker_dict:
    sber_found = "SBER" in ticker_dict["Акции РФ"]
    assert_eq("SBER в акции РФ", True, sber_found)

# Корп облигации появились
if "Корп. облигации" in ticker_dict:
    n_corp = len(ticker_dict["Корп. облигации"])
    assert_eq("Корп. облигации кол-во", 18, n_corp)
    sum_corp = sum(ticker_dict["Корп. облигации"].values())
    assert_eq("Корп. облигации сумма", 100.0, sum_corp, tol=0.01)

print()


# ═══════════════════════════════════════════════════════════════════════════
# ТЕСТ 10: УТИЛИТЫ ФОРМАТИРОВАНИЯ
# ═══════════════════════════════════════════════════════════════════════════

print("=" * 70)
print("ТЕСТ 10: Утилиты форматирования")
print("=" * 70)

assert_eq("fmt_rub positive", "      1234.56 ₽", fmt_rub(1234.56))
assert_eq("fmt_rub negative", "−     1234.56 ₽", fmt_rub(-1234.56))
assert_eq("fmt_pct positive", "+5.30%", fmt_pct(5.3))
assert_eq("fmt_pct negative", "-3.70%", fmt_pct(-3.7))

print()


# ═══════════════════════════════════════════════════════════════════════════
# ТЕСТ 11: PLOTLY ГРАФИКИ — БЕЗ ОШИБОК
# ═══════════════════════════════════════════════════════════════════════════

print("=" * 70)
print("ТЕСТ 11: Plotly графики генерируются")
print("=" * 70)

try:
    fig = make_pie_chart([100, 200, 300], ["A", "B", "C"], "Test pie")
    assert_eq("Pie chart created", True, hasattr(fig, 'to_json'))

    fig2 = make_bar_deviations(result)
    assert_eq("Bar deviations created", True, hasattr(fig2, 'to_json'))

    # Empty inputs
    fig_empty = make_pie_chart([], [], "Empty")
    ok("Empty pie chart handled")

    result_empty = {"class_devs": {}, "all_classes": []}
    fig_bar_empty = make_bar_deviations(result_empty)
    ok("Empty bar chart handled")

except Exception as e:
    fail("Plotly error", None, str(e))
    failed += 1

print()


# ═══════════════════════════════════════════════════════════════════════════
# ТЕСТ 12: ЭКСТРА ТЕСТИРОВАНИЕ — РЕГРЕССИЯ НА ORIGINAL DATA
# ═══════════════════════════════════════════════════════════════════════════

print("=" * 70)
print("ТЕСТ 12: Регрессия на original data")
print("=" * 70)

if PORTFOLIO_FILE.exists():
    with open(str(PORTFOLIO_FILE), encoding="utf-8") as f:
        orig_text = f.read()

    orig_data = parse_portfolio(orig_text)
    if orig_data["portfolio_total"] > 0:
        ok(f"Original portfolio parsed: {orig_data['portfolio_total']:,.2f} руб.")
        orig_result = calc_portfolio(orig_data, targets)
        ok(f"Original equity: {orig_result['equity']:,.2f} руб.")
        assert_eq("Original has positions", True, len(orig_data["positions"]) > 0)
    else:
        ok("Original file exists but has no data (QUIK not connected)")
else:
    ok("No original portfolio file found (QUIK not needed)")

print()


# ═══════════════════════════════════════════════════════════════════════════
# РЕЗУЛЬТАТЫ
# ═══════════════════════════════════════════════════════════════════════════

print("=" * 70)
print(f"РЕЗУЛЬТАТЫ: {passed} passed, {failed} failed")
print("=" * 70)

# Возвращаем стандартный targets.json
_default_tgt = {"classes": {"ОФЗ": 20.0, "Корп. облигации": 10.0, "Акции РФ": 5.0,
                            "ETF": 5.0, "Золото": 10.0, "Фьючерсы": 15.0, "Денежные средства": 35.0},
                "tickers": {}}
save_targets(_default_tgt)

sys.exit(1 if failed > 0 else 0)
