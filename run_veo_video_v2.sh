#!/bin/bash

# =================================================================
#  Veo Video Generation Script (V2 - Standalone Scenes)
#  Ported for macOS / Linux
# =================================================================

# Ensure we are in the script's directory
cd "$(dirname "$0")"

echo ""
echo "================================================================="
echo " Veo Video Generation Script (V2)"
echo "================================================================="
echo ""

# 1. Activate/Create Python Virtual Environment
if [ ! -d "venv-wan" ]; then
    echo "Creating Python Virtual Environment (venv-wan)..."
    python3 -m venv venv-wan
fi

echo "--- Activating Python Virtual Environment ---"
source venv-wan/bin/activate

# 2. Install Dependencies
echo ""
echo "Checking dependencies..."
pip install -U -q "google-genai>=1.44.0" google-cloud-storage

# 3. Run Scenes
echo ""
echo "--- Starting Scene Generation Loop ---"

# Run all scenes defined in the Python script
python3 generate_veo_video_v2.py --run-all --duration 8

EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "❌ Script exited with error."
    exit 1
fi

echo ""
echo "✅ All scenes processed. Script finished."