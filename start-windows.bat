@echo off
setlocal

set APP_HOST=%APP_HOST%
if "%APP_HOST%"=="" set APP_HOST=127.0.0.1

set APP_PORT=%APP_PORT%
if "%APP_PORT%"=="" set APP_PORT=8010

set VENV_DIR=%VENV_DIR%
if "%VENV_DIR%"=="" set VENV_DIR=.venv

cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  set PYTHON_CMD=py -3
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python nao encontrado. Instale o Python 3.11 ou superior.
    exit /b 1
  )
  set PYTHON_CMD=python
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
  echo Criando ambiente virtual em %VENV_DIR%...
  %PYTHON_CMD% -m venv "%VENV_DIR%"
  if errorlevel 1 exit /b 1
)

call "%VENV_DIR%\Scripts\activate.bat"
if errorlevel 1 exit /b 1

echo Atualizando dependencias...
python -m pip install --upgrade pip
if errorlevel 1 exit /b 1

python -m pip install -e .
if errorlevel 1 exit /b 1

echo Garantindo navegador Chromium do Playwright...
python -m playwright install chromium
if errorlevel 1 exit /b 1

if "%APP_HOST%"=="0.0.0.0" (
  if "%RPA_HUB_API_KEY%"=="" (
    echo AVISO: APP_HOST=0.0.0.0 sem RPA_HUB_API_KEY definida.
    echo Acessos de outras maquinas serao bloqueados. Defina RPA_HUB_API_KEY para usar o Hub em rede.
    echo.
  )
)

echo.
echo HUB RPA iniciado em: http://%APP_HOST%:%APP_PORT%
echo Documentacao da API: http://%APP_HOST%:%APP_PORT%/docs
echo.

python -m uvicorn apps.api.rpa_hub_api.main:app --host %APP_HOST% --port %APP_PORT%
