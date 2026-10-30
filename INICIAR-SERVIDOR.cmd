@echo off
setlocal
pushd "%~dp0"
if not exist "data\rooms.json" python server.py init-room
if errorlevel 1 goto error
python server.py serve
if errorlevel 1 goto error
popd
exit /b 0
:error
echo No se pudo iniciar. Revisa que Python 3.10 o superior este instalado.
pause
popd
exit /b 1
