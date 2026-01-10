#!/bin/bash
cd "$(dirname "$0")"

echo "=========================================="
echo " Reset Git Remote"
echo "=========================================="
echo ""

# Check if remote exists before trying to show it
if git remote get-url origin > /dev/null 2>&1; then
    echo -n "Current remote 'origin': "
    git remote get-url origin
    echo ""

    read -p "Are you sure you want to remove this remote? (y/n): " CONFIRM
    if [[ "${CONFIRM,,}" != "y" ]]; then
        echo "Cancelled."
        exit 0
    fi

    echo ""
    echo "Removing remote 'origin'..."
    git remote remove origin

    echo ""
    echo "Done. You can now run push_to_github.sh again."
else
    echo "Remote 'origin' is not configured. Nothing to do."
fi

read -p "Press enter to continue..."
