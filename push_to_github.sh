#!/bin/bash
cd "$(dirname "$0")"

echo "=========================================="
echo " Pushing to GitHub"
echo "=========================================="
echo ""

# 1. Ensure all files are tracked and committed
echo "Staging and committing changes..."
git add .
# This will fail gracefully if there's nothing new to commit.
git commit -m "Update project files"

# 2. Check if remote is configured
if ! git remote get-url origin > /dev/null 2>&1; then
    echo "Remote 'origin' is not configured."
    echo ""
    REPO_URL="https://github.com/smichalove/WAN_Project.git"
    echo "Setting remote origin to $REPO_URL..."
    echo "(Ensure you have created the empty repository 'WAN_Project' on GitHub!)"
    
    git remote add origin "$REPO_URL"
else
    echo -n "Remote 'origin' is already configured: "
    git remote get-url origin
fi

# 3. Push to main
echo ""
echo "Pushing to main branch..."
git branch -M main
git push -u origin main

# Handle first push failure (e.g., remote has a README)
if [ $? -ne 0 ]; then
    echo ""
    echo "⚠️ Push failed. Attempting to pull remote changes..."
    echo "(This is necessary if you initialized the repo with a README or License)"
    git pull origin main --allow-unrelated-histories --no-edit
    echo "Retrying push..."
    git push -u origin main
fi

# Handle second push failure (e.g., wrong URL)
if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Push failed!"
    echo ""
    echo -n "The repository URL is currently set to: "
    git remote get-url origin
    echo ""
    
    read -p "Did you create the repo with a different name? Update URL? (y/n): " CHANGE_URL
    if [[ "${CHANGE_URL,,}" == "y" ]]; then
        read -p "Enter the new GitHub Repository URL: " NEW_URL
        git remote set-url origin "$NEW_URL"
        echo ""
        echo "Retrying push..."
        git push -u origin main
        if [ $? -ne 0 ]; then
          exit 1
        fi
    else
        echo "Please create the repository on GitHub: https://github.com/new"
        # For Git Bash on Windows, 'start' should open the URL in a browser.
        start https://github.com/new
        read -p "Press enter to exit."
        exit 1
    fi
fi

echo ""
echo "✅ Push complete!"
read -p "Press enter to continue..."
