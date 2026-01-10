@echo off
cd /d %~dp0

echo ==========================================
echo  Initializing Git Repository
echo ==========================================
echo.

echo 1. Running git init...
git init

echo 2. Creating .gitignore file...
(
echo venv-wan/
echo __pycache__/
echo *.mp4
echo *.jpg
echo *.png
echo *.legacy
echo temp_clip_*.mp4
echo auth/
echo .vscode/
) > .gitignore

echo 3. Staging files...
git add .

echo 4. Creating initial commit...
git commit -m "Initial commit of Veo video generation project"

echo 5. Setting branch to main...
git branch -M main

echo.
echo ✅ Repository initialized successfully!
pause