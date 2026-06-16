@echo off
chcp 65001 >nul
title ViroFeed AI Personal
color 0B

echo ============================================================
echo    ViroFeed AI Personal
echo    Iniciando el programa...
echo    Se abrira solo en tu navegador (http://localhost:5000)
echo    Para CERRAR el programa, cierra esta ventana.
echo ============================================================
echo.

if not exist venv (
  echo  No encontre el entorno. Ejecuta primero  setup_windows.bat
  pause
  exit /b 1
)

if not exist .env (
  echo  No encontre el archivo .env. Ejecuta primero  setup_windows.bat
  echo  y pega tus claves de Groq y Pexels.
  pause
  exit /b 1
)

call venv\Scripts\activate.bat
python app.py

pause
