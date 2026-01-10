@echo off
setlocal enabledelayedexpansion
cd /d %~dp0

echo ==========================================
echo  Pushing to GitHub
echo ==========================================
echo.

:: 1. Ensure all files are tracked and committed
echo Staging and committing changes...
git add .
git commit -m "Update project files" >nul 2>&1

:: 2. Check if remote is configured
git remote get-url origin >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Remote 'origin' is not configured.
    echo.
    set REPO_URL=https://github.com/smichalove/WAN_Project.git
    echo Setting remote origin to %REPO_URL%...
    echo (Ensure you have created the empty repository 'WAN_Project' on GitHub!)
    
    git remote add origin %REPO_URL%
) else (
    echo Remote 'origin' is already configured:
    git remote get-url origin
)

:: 3. Push to main
echo.
echo Pushing to main branch...
git branch -M main
git push -u origin main

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ⚠️ Push failed. Attempting to pull remote changes...
    echo (This is necessary if you initialized the repo with a README or License)
    git pull origin main --allow-unrelated-histories --no-edit
    echo Retrying push...
    git push -u origin main
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ❌ Push failed!
    echo.
    echo The repository URL is currently set to:
    git remote get-url origin
    echo.
    
    set /p CHANGE_URL="Did you create the repo with a different name? Update URL? (Y/N): "
    if /i "!CHANGE_URL!"=="Y" (
        set /p NEW_URL="Enter the new GitHub Repository URL: "
        git remote set-url origin !NEW_URL!
        echo.
        echo Retrying push...
        git push -u origin main
        if !ERRORLEVEL! NEQ 0 exit /b
    ) else (
        echo Opening GitHub creation page...
        start https://github.com/new
        pause
        exit /b
    )
)

echo.
echo ✅ Push complete!
pause