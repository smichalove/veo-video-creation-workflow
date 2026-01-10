@echo off
H:
cd \WAN_Project

echo.
echo =================================================================
echo  Veo Video Generation Script (V2 - Standalone Scenes)
echo =================================================================
echo.
echo This script will use the Google Gen AI SDK (Vertex AI) to generate videos.
echo Video extension logic has been removed for this version.
echo.

:: 0. Load Configuration
if exist config.bat (
    call config.bat
) else (
    echo ⚠️  config.bat not found. Please create it with your PROJECT_ID and GCS_BUCKET_URI.
)

:: 1. Activate Python Environment
echo.
echo --- Activating Python Virtual Environment ---
call venv-wan\Scripts\activate.bat

:: 2. Install Google Cloud SDK for Python (Ensure dependencies)
echo.
echo Checking dependencies...
pip install -U -q "google-genai>=1.44.0" google-cloud-storage

:: 3. Configure API Key (Not needed for Vertex AI, but keeping structure)
echo.
echo =================================================================
echo  Vertex AI Configuration
echo =================================================================
echo.
echo --- Using Vertex AI (gcloud credentials). Proceeding to scene generation. ---

:: 5. Pause so you can see the results
echo.
echo --- Starting Scene Generation Loop ---
setlocal enabledelayedexpansion

:: Run all scenes defined in the Python script
python generate_veo_video_v2.py --run-all --duration 8

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ❌ Script exited with error.
    exit /b 1
)

endlocal
echo.
echo ✅ All scenes processed. Script finished.