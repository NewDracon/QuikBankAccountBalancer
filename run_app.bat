@echo off
REM ═══════════════════════════════════════════════════════════════════════════════
REM Запуск app.py через uv (авто-установка Python 3.12 + зависимости)
REM Использовать: run_app.bat  (двойной клик или из cmd)
REM ═══════════════════════════════════════════════════════════════════════════════

cd /d "%~dp0"

REM Проверяем/ставим uv
where uv >nul 2>nul || (
    echo [*] uv не найден. Устанавливаем...
    pip install uv --quiet
)

REM Создаём/обновляем .venv на Python 3.12 и ставим зависимости
if not exist ".venv\Scripts\python.exe" (
    echo [*] Создаём виртуальное окружение на Python 3.12...
    uv venv --python 3.12 --clear
)

echo [*] Устанавливаем зависимости...
uv pip install -r requirements.txt --quiet

REM Запускаем streamlit напрямую из .venv
echo [*] Запуск Streamlit...
.venv\Scripts\streamlit.exe run app.py %*