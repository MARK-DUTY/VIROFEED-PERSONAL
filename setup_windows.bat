@echo off
chcp 65001 >nul
title ViroFeed AI Personal - Instalacion
color 0B

echo ============================================================
echo    ViroFeed AI Personal - INSTALACION (solo una vez)
echo ============================================================
echo.

REM --- 1) Comprobar Python ---------------------------------------------
echo [1/5] Comprobando Python...
python --version >nul 2>&1
if errorlevel 1 (
  echo.
  echo  ERROR: No tienes Python instalado.
  echo  Descargalo aqui: https://www.python.org/downloads/
  echo  IMPORTANTE: al instalar, marca la casilla "Add Python to PATH".
  echo.
  pause
  exit /b 1
)
python --version
echo.

REM --- 2) Comprobar FFmpeg ---------------------------------------------
echo [2/5] Comprobando FFmpeg...
ffmpeg -version >nul 2>&1
if errorlevel 1 (
  echo.
  echo  AVISO: No encontre FFmpeg en el sistema.
  echo  Intentare instalarlo con winget...
  winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
  echo.
  echo  Si winget fallo, instala FFmpeg manualmente:
  echo  https://www.gyan.dev/ffmpeg/builds/  (ffmpeg-release-essentials.zip)
  echo  y agrega su carpeta "bin" al PATH. Luego vuelve a ejecutar este instalador.
  echo.
) else (
  echo FFmpeg encontrado. OK.
)
echo.

REM --- 3) Crear entorno virtual ----------------------------------------
echo [3/5] Creando entorno de Python (carpeta venv)...
if not exist venv (
  python -m venv venv
)
echo OK.
echo.

REM --- 4) Instalar dependencias ----------------------------------------
echo [4/5] Instalando librerias (puede tardar unos minutos)...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo  ERROR instalando librerias. Revisa tu conexion a internet.
  pause
  exit /b 1
)
echo.

REM --- 5) Crear archivo de configuracion .env --------------------------
echo [5/5] Preparando el archivo de configuracion...
if not exist .env (
  copy config.example.env .env >nul
  echo.
  echo  Se creo el archivo .env
  echo  AHORA debes abrirlo con el Bloc de notas y pegar tus claves de
  echo  Groq y Pexels. Luego guarda el archivo.
) else (
  echo  Ya existe un archivo .env (no lo toco).
)
echo.
echo ============================================================
echo    INSTALACION TERMINADA
echo.
echo    Siguiente paso:
echo    1) Abre el archivo  .env  y pega tus claves (Groq y Pexels)
echo    2) Haz doble clic en  run_windows.bat  para usar el programa
echo ============================================================
echo.
pause
