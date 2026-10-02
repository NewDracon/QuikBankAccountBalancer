# ════════════════════════════════════════════════════════════════════════════════
# Запуск app.py через uv (авто-установка Python 3.12 + зависимости)
# ════════════════════════════════════════════════════════════════════════════════

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $scriptDir

# Установка uv если нужно
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "[*] Устанавливаем uv..." -ForegroundColor Yellow
    pip install uv -q
}

# Создаём/обновляем .venv на Python 3.12
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "[*] Создаём виртуальное окружение на Python 3.12..." -ForegroundColor Cyan
    uv venv --python 3.12 --clear
}

Write-Host "[*] Устанавливаем зависимости..." -ForegroundColor Cyan
uv pip install -r requirements.txt -q

Write-Host "[*] Запуск Streamlit..." -ForegroundColor Green
.venv\Scripts\streamlit.exe run app.py @args

Pop-Location