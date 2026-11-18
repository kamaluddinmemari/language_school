@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo ===============================================================
echo   آدرس سرور برای وارد کردن در اپ (یکی از این‌ها، معمولا اولی):
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do echo     http:%%a:8000
echo   در اپ: صفحه ورود ^> تنظیمات و تست اتصال به سرور
echo ===============================================================
echo.
python manage.py runserver 0.0.0.0:8000
pause
