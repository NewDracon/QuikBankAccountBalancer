#!/usr/bin/env python3
"""
Тест для понимания проблемы с session_state
"""
import json

# Имитация session_state
session_state = {
    "targets": {
        "classes": {
            "Фьючерсы": 30.0,
            "Акции": 70.0
        },
        "tickers": {},
        "futures_overlay_classes": [],
        "futures_buffer_pct": 15.0
    }
}

def test_session_state_behavior():
    print("=== Тест поведения session_state ===")
    
    # Имитируем загрузку из session_state
    tgt = session_state["targets"]
    editor_tickers = tgt.get("tickers", {}).copy()
    
    print(f"1. Исходный editor_tickers: {editor_tickers}")
    
    # Имитируем добавление тикера
    if "Фьючерсы" not in editor_tickers:
        editor_tickers["Фьючерсы"] = {}
    editor_tickers["Фьючерсы"]["SIH2"] = 50.0
    editor_tickers["Фьючерсы"]["SII2"] = 50.0
    
    print(f"2. После добавления тикеров: {editor_tickers}")
    
    # Имитируем обработку для сохранения
    final_tickers = {}
    for cn, td in editor_tickers.items():
        if not td: 
            continue
        ks = sorted(td.keys())
        n = len(ks)
        w = round(100.0 / n, 2)
        diff = 100.0 - w * n
        final_tickers[cn] = {}
        for i, k in enumerate(ks):
            final_tickers[cn][k] = round(w + (diff if i == n - 1 else 0), 2)
    
    print(f"3. final_tickers после нормализации: {final_tickers}")
    
    # Формируем финальный словарь
    final_tgt = {
        "classes": tgt.get("classes", {}),
        "tickers": final_tickers,
        "futures_overlay_classes": tgt.get("futures_overlay_classes", []),
        "futures_buffer_pct": tgt.get("futures_buffer_pct", 15.0),
    }
    
    print(f"4. Финальные цели: {json.dumps(final_tgt, ensure_ascii=False, indent=2)}")
    
    # Имитируем сохранение в session_state
    session_state["targets"] = final_tgt
    print(f"5. session_state.targets после сохранения: {session_state['targets']}")
    
    return final_tgt

if __name__ == "__main__":
    test_session_state_behavior()