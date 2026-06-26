@echo off
cd /d C:\repos\cabeca_cachorro\backend
call .venv\Scripts\activate
python -m py_compile app\main.py app\routes\validator.py app\services\spreadsheet_reader.py
echo Sintaxe Python ok.
echo Abra http://127.0.0.1:5500/ferramentas/validador-herbario/ depois de rodar start_validator_dev.cmd
