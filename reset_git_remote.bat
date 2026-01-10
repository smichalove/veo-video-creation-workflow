@echo off
cd /d %~dp0

echo ==========================================
echo  Reset Git Remote
echo ==========================================
echo.
echo Current remote 'origin':
git remote get-url origin
echo.

set /p CONFIRM="Are you sure you want to remove this remote? (Y/N): "
if /i "%CONFIRM%" neq "Y" goto :EOF

echo.
echo Removing remote 'origin'...
git remote remove origin

echo.
echo Done. You can now run push_to_github.bat again.
pause