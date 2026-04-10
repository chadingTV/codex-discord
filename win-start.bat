@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "ENV_FILE=%SCRIPT_DIR%\.env"
set "TRAY_EXE=%SCRIPT_DIR%\tray\CodexBotTray.exe"
set "TRAY_SRC=%SCRIPT_DIR%\tray\CodexBotTray.cs"
set "BOT_EXE=%SCRIPT_DIR%\CodexBot.exe"
set "LOG_FILE=%SCRIPT_DIR%\bot.log"

where node >nul 2>&1
if errorlevel 1 (
    echo Node.js not found. Please run install.bat first.
    exit /b 1
)

call :prepare_bot_exe

if "%~1"=="--stop" (
    call :stop_bot
    echo Stopped.
    exit /b 0
)

if "%~1"=="--status" (
    call :is_running
    if errorlevel 1 (
        echo Stopped.
    ) else (
        echo Running.
    )
    exit /b 0
)

if "%~1"=="--fg" (
    cd /d "%SCRIPT_DIR%"
    call :build_if_needed
    call :ensure_sqlite
    call :stop_bot >nul 2>&1
    echo Starting in foreground...
    if exist "%BOT_EXE%" (
        "%BOT_EXE%" dist/index.js
    ) else (
        node dist/index.js
    )
    exit /b %errorlevel%
)

cd /d "%SCRIPT_DIR%"
call :build_if_needed
call :ensure_sqlite
call :stop_bot >nul 2>&1
call :build_tray_if_needed

if exist "%TRAY_EXE%" (
    taskkill /im CodexBotTray.exe /f >nul 2>&1
    start "" "%TRAY_EXE%" --show
)

if not exist "%ENV_FILE%" (
    echo .env not found. Please configure settings from the tray icon.
    echo Stop: win-start.bat --stop
    echo Status: win-start.bat --status
    echo Log: type bot.log
    exit /b 0
)

call :start_background
echo Bot started in background.
echo Stop: win-start.bat --stop
echo Status: win-start.bat --status
echo Log: type bot.log
exit /b 0

:prepare_bot_exe
set "NODE_EXE="
for /f "delims=" %%i in ('where node 2^>nul') do (
    if not defined NODE_EXE set "NODE_EXE=%%i"
)
if defined NODE_EXE (
    copy /y "%NODE_EXE%" "%BOT_EXE%" >nul 2>&1
)
exit /b 0

:build_if_needed
if not exist "%SCRIPT_DIR%\dist\index.js" (
    echo Building project...
    call npm.cmd run build
    exit /b %errorlevel%
)

for /f %%t in ('powershell -NoProfile -Command "(Get-ChildItem '%SCRIPT_DIR%\src' -Recurse -Filter *.ts | Sort-Object LastWriteTime -Descending | Select-Object -First 1).LastWriteTime.Ticks"') do set "SRC_TIME=%%t"
for /f %%t in ('powershell -NoProfile -Command "(Get-Item '%SCRIPT_DIR%\dist\index.js').LastWriteTime.Ticks"') do set "DIST_TIME=%%t"
if "!SRC_TIME!" gtr "!DIST_TIME!" (
    echo Source changed. Rebuilding...
    call npm.cmd run build
    exit /b %errorlevel%
)
exit /b 0

:ensure_sqlite
node -e "require('./node_modules/better-sqlite3/build/Release/better_sqlite3.node')" >nul 2>&1
if errorlevel 1 (
    echo Rebuilding better-sqlite3...
    call npm.cmd rebuild better-sqlite3
)
exit /b 0

:build_tray_if_needed
set "NEED_TRAY_BUILD=0"
if not exist "%TRAY_EXE%" (
    set "NEED_TRAY_BUILD=1"
) else (
    for /f %%a in ('powershell -NoProfile -Command "if ((Get-Item '%TRAY_SRC%').LastWriteTime -gt (Get-Item '%TRAY_EXE%').LastWriteTime) { '1' } else { '0' }"') do set "NEED_TRAY_BUILD=%%a"
)
if not "!NEED_TRAY_BUILD!"=="1" exit /b 0
if not exist "%TRAY_SRC%" exit /b 0

set "CSC="
for /f "delims=" %%i in ('dir /b /s "%WINDIR%\Microsoft.NET\Framework64\csc.exe" 2^>nul') do (
    if not defined CSC set "CSC=%%i"
)
if not defined CSC (
    for /f "delims=" %%i in ('dir /b /s "%WINDIR%\Microsoft.NET\Framework\csc.exe" 2^>nul') do (
        if not defined CSC set "CSC=%%i"
    )
)
if not defined CSC exit /b 0

"%CSC%" /nologo /target:winexe /out:"%TRAY_EXE%" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll "%TRAY_SRC%"
exit /b 0

:start_background
set "RUNNER=node"
if exist "%BOT_EXE%" set "RUNNER=%BOT_EXE%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$wd = '%SCRIPT_DIR%';" ^
    "$runner = '%RUNNER%';" ^
    "$cmd = 'cd /d ""' + $wd + '"" && ""' + $runner + '"" dist/index.js >> bot.log 2>&1';" ^
    "Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', $cmd -WorkingDirectory $wd -WindowStyle Hidden"
exit /b 0

:stop_bot
taskkill /im CodexBot.exe /f >nul 2>&1
taskkill /im node.exe /fi "WINDOWTITLE eq CodexDiscordBot" /f >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ws = [regex]::Escape('%SCRIPT_DIR%');" ^
    "$procs = Get-CimInstance Win32_Process | Where-Object {" ^
    "  ($_.Name -in @('node.exe','CodexBot.exe')) -and $_.CommandLine -and ($_.CommandLine -match $ws) -and ($_.CommandLine -like '*dist\\index.js*')" ^
    "};" ^
    "$procs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
del "%SCRIPT_DIR%\.bot.lock" >nul 2>&1
exit /b 0

:is_running
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ws = [regex]::Escape('%SCRIPT_DIR%');" ^
    "$procs = Get-CimInstance Win32_Process | Where-Object {" ^
    "  ($_.Name -in @('node.exe','CodexBot.exe')) -and $_.CommandLine -and ($_.CommandLine -match $ws) -and ($_.CommandLine -like '*dist\\index.js*')" ^
    "};" ^
    "if ($procs) { exit 0 } else { exit 1 }"
exit /b %errorlevel%
