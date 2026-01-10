#!/bin/bash

# Ensure the script is run from its own directory
cd "$(dirname "$0")"

echo ""
echo "================================================================="
echo " Veo Video Generation Script (V2 - Standalone Scenes)"
echo "================================================================="
echo ""
echo "This script will use the Google Gen AI SDK (Vertex AI) to generate videos."
echo "Video extension logic has been removed for this version."
echo ""

# 0. Load Configuration
if [ -f "config.sh" ]; then
    source config.sh
else
    echo "⚠️  config.sh not found. Please create it with your PROJECT_ID and GCS_BUCKET_URI."
fi

# 1. Activate Python Environment
echo ""
echo "--- Activating Python Virtual Environment ---"
source venv-wan/Scripts/activate

# 2. Install Google Cloud SDK for Python (Ensure dependencies)
echo ""
echo "Checking dependencies..."
pip install -U -q "google-genai>=1.44.0" google-cloud-storage

# 3. Configure API Key (Not needed for Vertex AI, but keeping structure)
echo ""
echo "================================================================="
echo " Vertex AI Configuration"
echo "================================================================="
echo ""
echo "--- Using Vertex AI (gcloud credentials). Proceeding to scene generation. ---"

# 5. Pause so you can see the results
echo ""
echo "--- Starting Scene Generation Loop ---"

# Run all scenes defined in the Python script
python generate_veo_video_v2.py --run-all --duration 8

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Script exited with error."
    exit 1
fi

echo ""
echo "✅ All scenes processed. Script finished."
