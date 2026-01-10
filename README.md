# Veo Video Generation Project

This project automates the generation of cinematic video scenes using Google's **Veo** model via the **Vertex AI** SDK.

## Features

*   **Batch Generation**: Automates the creation of multiple scenes defined in an external storyboard file.
*   **Dynamic Cast & Storyboard**: Reads character descriptions and scene prompts from `cast.md` and `storyboard.md`.
*   **Vertex AI Integration**: Uses the Google Gen AI SDK with Vertex AI for asynchronous video generation.
*   **Cost Optimization**: Configured to disable audio generation (`generate_audio=False`) to reduce API costs.
*   **Cloud Storage**: Automatically downloads generated videos from a Google Cloud Storage bucket.
*   **Robust Error Handling**: Includes retry logic for quotas and specific handling for safety filters or API limitations.

## Prerequisites

1.  **Google Cloud SDK**: Installed and available in your PATH.
2.  **Python 3.10+**: Recommended environment.
3.  **Google Cloud Project**: A GCP project with the Vertex AI API enabled.
4.  **Google Cloud Storage Bucket**: A bucket to store the output videos (e.g., `gs://your-bucket-name`).

## Google Cloud Setup

Run the following commands in your terminal to configure your project from scratch:

1.  **Login to Google Cloud:**
    ```bash
    gcloud auth login
    ```

2.  **Set your Project ID:**
    ```bash
    gcloud config set project YOUR_PROJECT_ID
    ```

3.  **Enable Required APIs (Vertex AI & Storage):**
    ```bash
    gcloud services enable aiplatform.googleapis.com storage.googleapis.com
    ```

4.  **Create a Storage Bucket:**
    ```bash
    gcloud storage buckets create gs://YOUR_BUCKET_NAME --location=us-central1
    ```

5.  **Authenticate for Python SDK:**
    ```bash
    gcloud auth application-default login
    ```

## Configuration

The main configuration settings are located in `generate_veo_video_v2.py`:

*   `PROJECT_ID`: Your Google Cloud Project ID.
*   `LOCATION`: Region (e.g., `us-central1`).
*   `GCS_BUCKET_URI`: The URI of your output bucket.

### Content Configuration (V2)
*   `cast.md`: Define character descriptions here (e.g., `LEAH_DESC: ...`).
*   `storyboard.md`: Define scenes here using markdown lists. Use placeholders like `{LEAH_DESC}` to reference cast members.

## Usage

To start the generation process, run the batch file:

```bash
create_veo_video.bat
```

This script will:
1.  Activate the Python virtual environment.
2.  Install/Update required dependencies.
3.  Iterate through the defined scenes in the storyboard.
4.  Generate each video and download it to the local folder.

## File Structure

*   `create_veo_video.bat`: Main entry point. Orchestrates the environment and loop.
*   `generate_veo_video_ext.py`: Python script that interfaces with the Vertex AI API.
*   `init_git_repo.bat`: Helper to initialize the local Git repository.
*   `push_to_github.bat`: Helper to push changes to a remote GitHub repository.
*   `README.md`: Project documentation.

## Cross-Platform Support
The python scripts in this project are compatible with the following operating systems:
- macOS
- Windows