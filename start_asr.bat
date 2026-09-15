@echo off
REM Start both ASR services (FastAPI + Cloudflare Tunnel)
REM Run this file to start the ASR service for production use

setlocal enabledelayedexpansion

REM Get the repo root directory
set "REPO_ROOT=%~dp0"
cd /d "%REPO_ROOT%"

echo.
echo ========================================
echo Starting SugboDoc ASR Service
echo ========================================
echo.
echo This will open two terminal windows:
echo   1. FastAPI server (localhost:8000)
echo   2. Cloudflare tunnel (public URL)
echo.
echo Keep both running for the service to stay live.
echo.
pause

REM Start FastAPI in a new window
echo Starting FastAPI server...
start "ASR FastAPI Server" cmd /k "cd deploy\asr-space && python app.py"

REM Wait a bit for the server to start
timeout /t 3 /nobreak

REM Start Cloudflare tunnel in another window
echo Starting Cloudflare tunnel...
start "ASR Cloudflare Tunnel" cmd /k "C:\Users\windows 10\cloudflared.exe tunnel --url http://localhost:8000"

echo.
echo Both services are starting. Check the terminal windows for output.
echo.
