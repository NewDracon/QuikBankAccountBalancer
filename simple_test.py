#!/usr/bin/env python3
"""
Простой тест для проверки структуры кода
"""
import sys
from pathlib import Path

# Добавим путь к проекту
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Проверим существование ключевых файлов
print("Проверка файлов:")
direct_file = project_root / "direct_portfolio.txt"
portfolio_file = project_root / "portfolio_viewer.txt"
test_file = project_root / "test_data.txt"

print(f"direct_portfolio.txt существует: {direct_file.exists()}")
print(f"portfolio_viewer.txt существует: {portfolio_file.exists()}")
print(f"test_data.txt существует: {test_file.exists()}")

# Проверим определение констант
try:
    import app
    print("Константы:")
    print(f"DIRECT_DATA_FILE: {app.DIRECT_DATA_FILE}")
    print(f"PORTFOLIO_FILE: {app.PORTFOLIO_FILE}")
    print(f"TEST_DATA_FILE: {app.TEST_DATA_FILE}")
    print("✓ Модуль импортировался успешно")
except Exception as e:
    print(f"Ошибка импорта: {e}")
    import traceback
    traceback.print_exc()