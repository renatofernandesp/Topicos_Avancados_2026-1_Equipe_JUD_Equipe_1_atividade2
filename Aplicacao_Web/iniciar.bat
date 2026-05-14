@echo off
echo.
echo Iniciando Streamlit...
echo O túnel SSH será criado automaticamente pela aplicação.
echo.
start "Streamlit" cmd /k python -m streamlit run "%~dp0app.py"
echo.
echo Tudo iniciado! Acesse http://localhost:8501
pause
