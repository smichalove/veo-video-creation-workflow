@echo off
setlocal

echo This script will permanently remove a specific API key from your repository's history.
echo It uses 'git-filter-repo', which will be installed via pip if needed.
echo.
echo ===============================================================================
echo WARNING: This is a destructive operation that rewrites your project history.
echo It is highly recommended to have a backup of your repository before proceeding.
echo ===============================================================================
echo.
pause

echo.
echo --- Step 1: Installing git-filter-repo ---
pip install git-filter-repo
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Failed to install git-filter-repo.
    echo Please make sure you have Python and pip installed and available in your PATH.
    goto :eof
)
echo 'git-filter-repo' is available.

echo.
echo --- Step 2: Preparing for history rewrite ---
echo Creating a temporary file with the secret to remove...
(echo AIzaSyAuaPh8xWsx9Vr5IPA6pBW7sKUddhGgJBE==) > .secrets_to_remove.txt

echo.
echo --- Step 3: Rewriting repository history ---
echo This may take a while...
git-filter-repo --replace-text .secrets_to_remove.txt --force

if %errorlevel% neq 0 (
    echo.
    echo ERROR: 'git-filter-repo' failed. History was not rewritten.
    del .secrets_to_remove.txt
    goto :eof
)

echo.
echo --- Step 4: Cleaning up ---
del .secrets_to_remove.txt
echo History rewriting successful.

echo.
echo --- FINAL STEPS (REQUIRED) ---
echo The secret has been removed from your *local* repository's history.
echo You MUST now force push to update the remote repository on GitHub.
echo.
echo 1. Make sure your remote is set correctly. Check with:
echo    git remote -v
echo.
echo 2. Force push all branches and tags to overwrite the remote history:
echo    git push --all --force
echo    git push --tags --force
echo.
echo WARNING: Force pushing is a destructive action for the remote repository.
echo Ensure no one else is working on the repository, or coordinate with them.
echo.

:eof
endlocal
echo Done.
pause