@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

:: Codex Discord Bot - Windows Auto-update & Start Script
:: 사용법:
::   win-start.bat          → 백그라운드 실행 + 트레이 앱 시작
::   win-start.bat --fg     → 포그라운드 실행 (디버깅용)
::   win-start.bat --stop   → 중지
::   win-start.bat --status → 상태 확인

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "ENV_FILE=%SCRIPT_DIR%\.env"
set "TRAY_EXE=%SCRIPT_DIR%\tray\CodexBotTray.exe"
set "TRAY_SRC=%SCRIPT_DIR%\tray\CodexBotTray.cs"

:: node 경로 확인
where node >nul 2>&1
if errorlevel 1 (
    echo Node.js not found. Please run install.bat first.
    pause
    exit /b 1
)

:: --stop: 중지
if "%~1"=="--stop" (
    :: 봇 프로세스 종료
    for /f "tokens=2" %%a in ('tasklist /fi "windowtitle eq CodexDiscordBot" /fo list 2^>nul ^| findstr "PID"') do (
        taskkill /pid %%a /f >nul 2>&1
    )
    :: node 프로세스 중 봇 관련 종료
    wmic process where "commandline like '%%dist/index.js%%' and name='node.exe'" call terminate >nul 2>&1
    :: lock 파일 삭제
    del "%SCRIPT_DIR%\.bot.lock" >nul 2>&1
    :: 트레이 앱 종료
    taskkill /im CodexBotTray.exe /f >nul 2>&1
    echo 🔴 봇 중지됨
    exit /b 0
)

:: --status: 상태 확인
if "%~1"=="--status" (
    if exist "%SCRIPT_DIR%\.bot.lock" (
        echo 🟢 봇 실행 중
    ) else (
        echo 🔴 봇 중지됨
    )
    exit /b 0
)

:: --fg: 포그라운드 실행
if "%~1"=="--fg" (
    cd /d "%SCRIPT_DIR%"

    for /f %%i in ('git describe --tags --always 2^>nul') do set "VERSION=%%i"
    if "!VERSION!"=="" set "VERSION=unknown"
    echo [codex-bot] 현재 버전: !VERSION!
    echo [codex-bot] Git 업데이트 확인 중...
    git fetch origin main >nul 2>&1

    for /f %%i in ('git rev-parse HEAD 2^>nul') do set "LOCAL=%%i"
    for /f %%i in ('git rev-parse origin/main 2^>nul') do set "REMOTE=%%i"

    if not "!LOCAL!"=="!REMOTE!" (
        if not "!LOCAL!"=="" (
            if not "!REMOTE!"=="" (
                echo [codex-bot] 업데이트가 있습니다 ^(트레이에서 업데이트 가능^)
            )
        )
    ) else (
        echo [codex-bot] 최신 버전입니다
    )

    if not exist "dist" (
        echo [codex-bot] 빌드 파일 없음, 빌드 중...
        call npm run build
    ) else (
        for /f %%t in ('powershell -NoProfile -Command "(Get-ChildItem src -Recurse -Filter *.ts | Sort-Object LastWriteTime -Descending | Select-Object -First 1).LastWriteTime.Ticks"') do set "SRC_TIME=%%t"
        for /f %%t in ('powershell -NoProfile -Command "(Get-Item dist\index.js).LastWriteTime.Ticks"') do set "DIST_TIME=%%t"
        if !SRC_TIME! gtr !DIST_TIME! (
            echo [codex-bot] 소스 변경 감지, 다시 빌드 중...
            call npm run build
        )
    )

    node -e "require('./node_modules/better-sqlite3/build/Release/better_sqlite3.node')" 2>nul
    if errorlevel 1 (
        echo [codex-bot] 네이티브 모듈 호환성 문제 감지, 재빌드 중...
        call npm rebuild better-sqlite3
    )

    echo [codex-bot] 봇 시작 ^(포그라운드^)...
    node dist/index.js
    exit /b 0
)

:: 기본: 백그라운드 실행
cd /d "%SCRIPT_DIR%"

:: 이미 실행 중이면 종료 후 재시작
if exist "%SCRIPT_DIR%\.bot.lock" (
    echo 🔄 기존 봇 종료 중...
    for /f "tokens=2" %%a in ('tasklist /fi "windowtitle eq CodexDiscordBot" /fo list 2^>nul ^| findstr "PID"') do (
        taskkill /pid %%a /f >nul 2>&1
    )
    wmic process where "commandline like '%%dist/index.js%%' and name='node.exe'" call terminate >nul 2>&1
    del "%SCRIPT_DIR%\.bot.lock" >nul 2>&1
    timeout /t 2 /nobreak >nul
)

:: 업데이트 체크 (자동 업데이트 안 함, 트레이에서 수동)
echo [codex-bot] Git 업데이트 확인 중...
git fetch origin main >nul 2>&1
for /f %%i in ('git rev-parse HEAD 2^>nul') do set "LOCAL=%%i"
for /f %%i in ('git rev-parse origin/main 2^>nul') do set "REMOTE=%%i"

if not "!LOCAL!"=="!REMOTE!" (
    if not "!LOCAL!"=="" (
        if not "!REMOTE!"=="" (
            echo [codex-bot] 업데이트가 있습니다 ^(트레이에서 업데이트 가능^)
        )
    )
) else (
    echo [codex-bot] 최신 버전입니다
)

if not exist "dist" (
    echo [codex-bot] 빌드 파일 없음, 빌드 중...
    call npm run build
 ) else (
    for /f %%t in ('powershell -NoProfile -Command "(Get-ChildItem src -Recurse -Filter *.ts | Sort-Object LastWriteTime -Descending | Select-Object -First 1).LastWriteTime.Ticks"') do set "SRC_TIME=%%t"
    for /f %%t in ('powershell -NoProfile -Command "(Get-Item dist\index.js).LastWriteTime.Ticks"') do set "DIST_TIME=%%t"
    if !SRC_TIME! gtr !DIST_TIME! (
        echo [codex-bot] 소스 변경 감지, 다시 빌드 중...
        call npm run build
    )
)

node -e "require('./node_modules/better-sqlite3/build/Release/better_sqlite3.node')" 2>nul
if errorlevel 1 (
    echo [codex-bot] 네이티브 모듈 호환성 문제 감지, 재빌드 중...
    call npm rebuild better-sqlite3
)

:: 트레이 앱 컴파일 (exe 없거나 소스가 더 최신이면)
set "NEED_TRAY_BUILD=0"
if not exist "%TRAY_EXE%" (
    set "NEED_TRAY_BUILD=1"
) else (
    for /f %%a in ('powershell -NoProfile -Command "if ((Get-Item \"%TRAY_SRC%\").LastWriteTime -gt (Get-Item \"%TRAY_EXE%\").LastWriteTime) { echo 1 } else { echo 0 }"') do set "NEED_TRAY_BUILD=%%a"
)
if "!NEED_TRAY_BUILD!"=="1" (
    if exist "%TRAY_SRC%" (
        echo 🔨 트레이 앱 빌드 중...
        :: .NET Framework csc.exe 찾기
        set "CSC="
        for /f "delims=" %%i in ('dir /b /s "%WINDIR%\Microsoft.NET\Framework64\csc.exe" 2^>nul') do set "CSC=%%i"
        if "!CSC!"=="" (
            for /f "delims=" %%i in ('dir /b /s "%WINDIR%\Microsoft.NET\Framework\csc.exe" 2^>nul') do set "CSC=%%i"
        )
        if not "!CSC!"=="" (
            "!CSC!" /nologo /target:winexe /out:"%TRAY_EXE%" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll "%TRAY_SRC%"
            if not exist "%TRAY_EXE%" (
                echo ❌ 트레이 앱 빌드 실패
            )
        ) else (
            echo ❌ C# 컴파일러를 찾을 수 없습니다
        )
    )
)

:: 트레이 앱 실행 (--show로 컨트롤 패널 자동 열기)
if exist "%TRAY_EXE%" (
    taskkill /im CodexBotTray.exe /f >nul 2>&1
    start "" "%TRAY_EXE%" --show
)

:: .env 있으면 봇 시작, 없으면 트레이에서 설정하도록
if exist "%ENV_FILE%" (
    :: 봇 백그라운드 실행 (완전 숨김, lock 파일로 상태 관리)
    :: (자동 시작은 트레이 앱의 Registry 설정으로 관리)
    echo Set ws = CreateObject^("WScript.Shell"^) > "%SCRIPT_DIR%\.bot-run.vbs"
    echo ws.Run "cmd /c cd /d %SCRIPT_DIR% ^& echo running^> .bot.lock ^& node dist/index.js ^& del .bot.lock", 0, False >> "%SCRIPT_DIR%\.bot-run.vbs"
    wscript "%SCRIPT_DIR%\.bot-run.vbs"
    del "%SCRIPT_DIR%\.bot-run.vbs" >nul 2>&1
    echo 🟢 Bot started in background
) else (
    echo ⚙️ .env not found. Please configure settings from the tray icon.
)
echo    Stop: win-start.bat --stop
echo    Status: win-start.bat --status
echo    Log: type bot.log
