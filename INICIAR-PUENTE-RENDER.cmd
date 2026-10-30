@echo off
setlocal
pushd "%~dp0"
python -c "import websockets" >nul 2>&1
if errorlevel 1 python -m pip install -r requirements.txt
if errorlevel 1 goto error
python -c "from pathlib import Path; import subprocess,sys; p=Path('data/render-url.txt'); u=p.read_text().strip() if p.exists() else sys.exit('Falta configurar la URL del servidor Render'); subprocess.run([sys.executable,'bridge.py','--url',u],check=True)"
if errorlevel 1 goto error
popd
exit /b 0
:error
echo No se pudo iniciar el puente. Revisa el mensaje anterior.
pause
popd
exit /b 1
