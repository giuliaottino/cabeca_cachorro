@echo off
start cmd /k "cd /d C:\repos\cabeca_cachorro\backend ^&^& call .venv\Scripts\activate ^&^& python -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
start cmd /k "cd /d C:\repos\cabeca_cachorro ^&^& python -m http.server 5500 --directory docs"
timeout /t 2 >nul
start http://127.0.0.1:5500/ferramentas/validador-herbario/
