@echo off
:: iZACH Node Receiver — quick launcher
:: Uses pythonw so no console window appears; only tray icon shows.
cd /d "%~dp0"
pythonw receiver.py
