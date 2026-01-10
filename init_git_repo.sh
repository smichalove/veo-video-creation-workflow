#!/bin/bash

cd "$(dirname "$0")"

echo "=========================================="
echo " Initializing Git Repository"
echo "=========================================="
echo ""

echo "1. Running git init..."
git init

echo "2. Creating .gitignore file..."
cat > .gitignore << EOF
venv-wan/
__pycache__/
*.mp4
*.jpg
*.png
*.legacy
temp_clip_*.mp4
auth/
.vscode/
EOF

echo "3. Staging files..."
git add .

echo "4. Creating initial commit..."
git commit -m "Initial commit of Veo video generation project"

echo "5. Setting branch to main..."
git branch -M main

echo ""
echo "✅ Repository initialized successfully!"
read -p "Press enter to continue..."
