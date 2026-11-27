@echo off
setlocal
cd /d "%~dp0"
set "VENV=%~dp0.venv_run"
set "MARCA=%VENV%\requisitos_instalados.txt"
if exist "%VENV%\Scripts\pythonw.exe" goto CONFERIR
echo Preparando o RDF pela primeira vez ^(pode levar alguns minutos^)...
set "CRIADO="
rem Prefere versoes estaveis: as bibliotecas fixadas ainda nao existem para Python muito novo.
for %%V in (3.13 3.12 3.11) do (
    if not defined CRIADO (
        py -%%V -m venv "%VENV%" >nul 2>&1
        if not errorlevel 1 set "CRIADO=1"
    )
)
if not defined CRIADO python -m venv "%VENV%"
if errorlevel 1 goto ERRO
:CONFERIR
rem A marca so e gravada depois que o pip termina bem: uma instalacao que falhou no meio e refeita na
rem proxima vez, e uma versao nova do RDF com outras bibliotecas instala o que falta.
fc /b "requirements.txt" "%MARCA%" >nul 2>&1
if not errorlevel 1 goto ABRIR
echo Instalando as bibliotecas do RDF...
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip
"%VENV%\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto ERRO
copy /y "requirements.txt" "%MARCA%" >nul
:ABRIR
start "" "%VENV%\Scripts\pythonw.exe" rdf_app.py
exit /b 0
:ERRO
echo.
echo Nao foi possivel preparar o RDF. Confira se o Python 3.11+ esta instalado e se ha acesso a internet.
pause
exit /b 1
