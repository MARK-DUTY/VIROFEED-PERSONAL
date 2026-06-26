@echo off
chcp 65001 >nul
title ViroFeed AI Personal - Actualizar
color 0B

echo ============================================================
echo    ViroFeed AI Personal - ACTUALIZAR
echo    Descarga la ULTIMA version del codigo desde GitHub.
echo    (No toca tu archivo .env ni tus videos)
echo ============================================================
echo.

set BASE=https://raw.githubusercontent.com/MARK-DUTY/VIROFEED-PERSONAL/main
set FALLOS=0

echo Actualizando archivos (forzando la ultima version)...
echo.

call :baja app.py
call :baja requirements.txt
call :baja run_windows.bat
call :baja setup_windows.bat
call :baja pipeline/article.py
call :baja pipeline/assemble.py
call :baja pipeline/avatar.py
call :baja pipeline/config.py
call :baja pipeline/images.py
call :baja pipeline/music.py
call :baja pipeline/runner.py
call :baja pipeline/script_gen.py
call :baja pipeline/subtitles.py
call :baja pipeline/voice.py
call :baja pipeline/youtube.py
call :baja templates/index.html
call :baja static/app.js
call :baja static/style.css

echo.
echo ============================================================
if "%FALLOS%"=="0" (
  echo    ACTUALIZACION TERMINADA - todos los archivos al dia.
) else (
  echo    ATENCION: %FALLOS% archivo^(s^) no se pudieron bajar.
  echo    Revisa tu internet y vuelve a ejecutar este actualizar.bat.
)
echo    Ahora cierra el programa ^(la ventana negra^) si esta abierto
echo    y vuelve a abrirlo con run_windows.bat
echo ============================================================
echo.
pause
exit /b

REM ---------------------------------------------------------------
REM  Subrutina que baja UN archivo, forzando version fresca (sin
REM  cache) y avisando si funciono [OK] o fallo [FALLO].
REM ---------------------------------------------------------------
:baja
set "rel=%~1"
set "dst=%rel:/=\%"
curl -fsS --retry 3 -H "Cache-Control: no-cache" -H "Pragma: no-cache" -o "%dst%" "%BASE%/%rel%?nocache=%RANDOM%%RANDOM%"
if errorlevel 1 (
  echo   [FALLO] %rel%
  set /a FALLOS+=1
) else (
  echo   [OK]    %rel%
)
goto :eof
