@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0.."
set "ROOT=%CD%\"
title RDF Package Builder

set "PYTHON_MODE="
set "PYTHON_EXE="
set "PYTHON_COMMAND="

rem Prefer the Python launcher, then search common commands and installation paths.
where py.exe >nul 2>&1
if not errorlevel 1 (
    for %%V in (3.13 3.14 3.12 3.11 3.10 3) do (
        if not defined PYTHON_MODE (
            py -%%V --version >nul 2>&1
            if not errorlevel 1 (
                set "PYTHON_MODE=LAUNCHER"
                set "PYTHON_COMMAND=py -%%V"
            )
        )
    )
)

if not defined PYTHON_MODE (
    for %%P in (python3.14.exe python3.13.exe python3.12.exe python3.11.exe python3.10.exe python3.exe python.exe) do (
        if not defined PYTHON_MODE (
            where %%P >nul 2>&1
            if not errorlevel 1 (
                %%P --version >nul 2>&1
                if not errorlevel 1 (
                    set "PYTHON_MODE=EXECUTABLE"
                    set "PYTHON_EXE=%%P"
                )
            )
        )
    )
)

if not defined PYTHON_MODE (
    for /d %%D in ("%LocalAppData%\Programs\Python\Python*") do (
        if not defined PYTHON_MODE if exist "%%~fD\python.exe" (
            set "PYTHON_MODE=EXECUTABLE"
            set "PYTHON_EXE=%%~fD\python.exe"
        )
    )
)

if not defined PYTHON_MODE (
    for %%P in (python3.14.exe python3.13.exe python3.12.exe python3.11.exe python3.10.exe python3.exe python.exe) do (
        if not defined PYTHON_MODE if exist "%LocalAppData%\Microsoft\WindowsApps\%%P" (
            "%LocalAppData%\Microsoft\WindowsApps\%%P" --version >nul 2>&1
            if not errorlevel 1 (
                set "PYTHON_MODE=EXECUTABLE"
                set "PYTHON_EXE=%LocalAppData%\Microsoft\WindowsApps\%%P"
            )
        )
    )
)

if not defined PYTHON_MODE goto PYTHON_NOT_FOUND

if "%PYTHON_MODE%"=="LAUNCHER" (
    echo Python found through: %PYTHON_COMMAND%
) else (
    echo Python found at: %PYTHON_EXE%
)

for /f "tokens=2 delims== " %%V in ('findstr /r /c:"APP_VERSION =" "%ROOT%rdf\__init__.py"') do set "APP_VERSION=%%~V"
set "APP_VERSION=%APP_VERSION:"=%"
if not defined APP_VERSION goto VERSION_NOT_FOUND
echo Application version: %APP_VERSION%

set "DELIVERY=%ROOT%RDF_DELIVERY_PACKAGE"
if exist "%DELIVERY%" goto DELIVERY_EXISTS

set "TESSERACT_EXE="
set "SEARCH_RESULT=%TEMP%\rdf_tesseract_path.txt"
if exist "%SEARCH_RESULT%" del /q "%SEARCH_RESULT%" >nul 2>&1

echo Searching for Tesseract OCR...
if exist "%ROOT%vendor\Tesseract-OCR\tesseract.exe" set "TESSERACT_EXE=%ROOT%vendor\Tesseract-OCR\tesseract.exe"
if not defined TESSERACT_EXE for /f "delims=" %%T in ('where tesseract.exe 2^>nul') do if not defined TESSERACT_EXE set "TESSERACT_EXE=%%T"
if not defined TESSERACT_EXE if exist "%ProgramFiles%\Tesseract-OCR\tesseract.exe" set "TESSERACT_EXE=%ProgramFiles%\Tesseract-OCR\tesseract.exe"
if not defined TESSERACT_EXE if defined ProgramFiles(x86) if exist "%ProgramFiles(x86)%\Tesseract-OCR\tesseract.exe" set "TESSERACT_EXE=%ProgramFiles(x86)%\Tesseract-OCR\tesseract.exe"
if not defined TESSERACT_EXE if exist "%LocalAppData%\Programs\Tesseract-OCR\tesseract.exe" set "TESSERACT_EXE=%LocalAppData%\Programs\Tesseract-OCR\tesseract.exe"
if not defined TESSERACT_EXE if exist "%UserProfile%\scoop\apps\tesseract\current\tesseract.exe" set "TESSERACT_EXE=%UserProfile%\scoop\apps\tesseract\current\tesseract.exe"
if not defined TESSERACT_EXE if exist "%ProgramData%\chocolatey\bin\tesseract.exe" set "TESSERACT_EXE=%ProgramData%\chocolatey\bin\tesseract.exe"

if not defined TESSERACT_EXE powershell -NoProfile -ExecutionPolicy Bypass -Command "$out=Join-Path $env:TEMP 'rdf_tesseract_path.txt'; $roots=@($env:ProgramFiles,${env:ProgramFiles(x86)},$env:LOCALAPPDATA+'\Programs',$env:LOCALAPPDATA+'\Microsoft\WinGet\Packages',$env:ProgramData+'\chocolatey',$env:USERPROFILE+'\scoop\apps') | Where-Object {$_ -and (Test-Path $_)} | Select-Object -Unique; foreach($r in $roots){$f=Get-ChildItem -LiteralPath $r -Filter tesseract.exe -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1; if($f){[IO.File]::WriteAllText($out,$f.FullName); exit 0}}" >nul 2>&1
if not defined TESSERACT_EXE if exist "%SEARCH_RESULT%" set /p TESSERACT_EXE=<"%SEARCH_RESULT%"
if exist "%SEARCH_RESULT%" del /q "%SEARCH_RESULT%" >nul 2>&1

if not defined TESSERACT_EXE goto TESSERACT_NOT_FOUND
if not exist "%TESSERACT_EXE%" goto TESSERACT_NOT_FOUND
"%TESSERACT_EXE%" --version >nul 2>&1
if errorlevel 1 goto TESSERACT_NOT_FOUND
for %%D in ("%TESSERACT_EXE%") do set "TESSERACT_DIR=%%~dpD"
if "%TESSERACT_DIR:~-1%"=="\" set "TESSERACT_DIR=%TESSERACT_DIR:~0,-1%"
echo Tesseract OCR found at: %TESSERACT_EXE%
if not exist "%TESSERACT_DIR%\tessdata\por.traineddata" goto TESSDATA_MISSING
if not exist "%TESSERACT_DIR%\tessdata\eng.traineddata" goto TESSDATA_MISSING

set "INNO_COMPILER="
set "SEARCH_RESULT=%TEMP%\rdf_inno_path.txt"
if exist "%SEARCH_RESULT%" del /q "%SEARCH_RESULT%" >nul 2>&1

echo Searching for Inno Setup...
for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do if not defined INNO_COMPILER set "INNO_COMPILER=%%I"
if not defined INNO_COMPILER for /d %%D in ("%ProgramFiles(x86)%\Inno Setup *") do if exist "%%~fD\ISCC.exe" set "INNO_COMPILER=%%~fD\ISCC.exe"
if not defined INNO_COMPILER for /d %%D in ("%ProgramFiles%\Inno Setup *") do if exist "%%~fD\ISCC.exe" set "INNO_COMPILER=%%~fD\ISCC.exe"
if not defined INNO_COMPILER for /d %%D in ("%LocalAppData%\Programs\Inno Setup *") do if exist "%%~fD\ISCC.exe" set "INNO_COMPILER=%%~fD\ISCC.exe"

if not defined INNO_COMPILER powershell -NoProfile -ExecutionPolicy Bypass -Command "$out=Join-Path $env:TEMP 'rdf_inno_path.txt'; $roots=@($env:ProgramFiles,${env:ProgramFiles(x86)},$env:LOCALAPPDATA+'\Programs',$env:LOCALAPPDATA+'\Microsoft\WinGet\Packages',$env:ProgramData+'\chocolatey',$env:USERPROFILE+'\scoop\apps') | Where-Object {$_ -and (Test-Path $_)} | Select-Object -Unique; foreach($r in $roots){$f=Get-ChildItem -LiteralPath $r -Filter ISCC.exe -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1; if($f){[IO.File]::WriteAllText($out,$f.FullName); exit 0}}" >nul 2>&1
if not defined INNO_COMPILER if exist "%SEARCH_RESULT%" set /p INNO_COMPILER=<"%SEARCH_RESULT%"
if exist "%SEARCH_RESULT%" del /q "%SEARCH_RESULT%" >nul 2>&1

if not defined INNO_COMPILER goto INNO_NOT_FOUND
if not exist "%INNO_COMPILER%" goto INNO_NOT_FOUND
echo Inno Setup found at: %INNO_COMPILER%

set "VENV_DIR=%ROOT%.venv_build"
set "BUILD_PYTHON=%VENV_DIR%\Scripts\python.exe"
if not exist "%BUILD_PYTHON%" (
    echo Creating the build environment...
    if "%PYTHON_MODE%"=="LAUNCHER" (
        %PYTHON_COMMAND% -m venv "%VENV_DIR%"
    ) else (
        "%PYTHON_EXE%" -m venv "%VENV_DIR%"
    )
    if errorlevel 1 goto VENV_ERROR
)

"%BUILD_PYTHON%" --version >nul 2>&1
if errorlevel 1 goto VENV_ERROR

echo Installing build dependencies...
"%BUILD_PYTHON%" -m pip install --upgrade pip
if errorlevel 1 goto BUILD_ERROR
"%BUILD_PYTHON%" -m pip install -r "%ROOT%requirements.txt" -r "%ROOT%requirements-build.txt"
if errorlevel 1 goto BUILD_ERROR

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist RDF.spec del /q RDF.spec

rem The app uses Qt (PySide6): PyInstaller bundles it with its own hook. Tkinter is left out on purpose.

echo Building RDF.exe...
"%BUILD_PYTHON%" -m PyInstaller --noconfirm --clean --onefile --windowed --name RDF --exclude-module tkinter --exclude-module tkinterdnd2 --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick --exclude-module PySide6.QtQuickWidgets --exclude-module PySide6.QtSql --exclude-module PySide6.QtTest --exclude-module PySide6.QtPdf --exclude-module PySide6.QtPdfWidgets --collect-all cv2 --collect-all fitz --add-binary "%TESSERACT_DIR%;Tesseract-OCR" --add-data "%ROOT%assets\icone.ico;assets" --icon "%ROOT%assets\icone.ico" "%ROOT%rdf_app.py"
if errorlevel 1 goto BUILD_ERROR
if not exist "%ROOT%dist\RDF.exe" goto BUILD_ERROR

if not exist installer_output mkdir installer_output
echo Building the installer...
"%INNO_COMPILER%" /DMyAppVersion=%APP_VERSION% "%ROOT%packaging\installer.iss"
if errorlevel 1 goto BUILD_ERROR

set "INSTALLER=%ROOT%installer_output\RDF_Setup.exe"
if not exist "%INSTALLER%" goto BUILD_ERROR
mkdir "%DELIVERY%"
if errorlevel 1 goto BUILD_ERROR
copy /y "%INSTALLER%" "%DELIVERY%\RDF_Setup.exe" >nul
if errorlevel 1 goto BUILD_ERROR
if exist "%ROOT%docs\DELIVERY_GUIDE.md" copy /y "%ROOT%docs\DELIVERY_GUIDE.md" "%DELIVERY%\DELIVERY_GUIDE.md" >nul
if errorlevel 1 goto BUILD_ERROR
powershell -NoProfile -ExecutionPolicy Bypass -Command "$f=Join-Path $env:DELIVERY 'RDF_Setup.exe'; $h=(Get-FileHash -Algorithm SHA256 -LiteralPath $f).Hash.ToLower(); Set-Content -Encoding ASCII -LiteralPath ($f+'.sha256') -Value ($h+'  RDF_Setup.exe')"
if errorlevel 1 goto BUILD_ERROR

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist RDF.spec del /q RDF.spec

echo Package created successfully: %DELIVERY%
start "" "%DELIVERY%"
pause
exit /b 0

:PYTHON_NOT_FOUND
echo ERROR: A supported Python installation was not found.
echo Install Python 3.10 or newer and run this script again.
goto END

:TESSERACT_NOT_FOUND
echo ERROR: Tesseract OCR was not found.
echo Install Tesseract OCR and run this script again.
goto END

:TESSDATA_MISSING
echo ERROR: Tesseract at %TESSERACT_DIR% has no Portuguese and English language data.
echo Install the "por" and "eng" languages in Tesseract (tessdata\por.traineddata and eng.traineddata).
goto END

:INNO_NOT_FOUND
echo ERROR: The Inno Setup compiler ^(ISCC.exe^) was not found.
echo Install any supported Inno Setup version and run this script again.
goto END

:VERSION_NOT_FOUND
echo ERROR: APP_VERSION could not be read from rdf\__init__.py.
goto END

:DELIVERY_EXISTS
echo ERROR: The delivery folder already exists: %DELIVERY%
echo Move or rename it before creating another package. Existing files were not changed.
goto END

:VENV_ERROR
echo ERROR: The build environment could not be created or used.
echo Delete the .venv_build directory and run this script again.
goto END

:BUILD_ERROR
echo ERROR: The package build failed. Review the messages above.

:END
pause
exit /b 1
