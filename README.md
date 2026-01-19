# Veo Batch Video Generation Workflow

`generate_veo_videos.py` is a powerful, command-line Python script designed to automate the batch generation of cinematic video scenes using Google's Veo model via the Vertex AI SDK. It streamlines the creative workflow by reading scene descriptions and character details from simple markdown files, managing the entire generation process, and organizing the output.

This repository provides a template for setting up your own automated video creation pipeline.

## Features

*   **Storyboard-Driven Generation**: Define all your scenes in a simple `storyboard.md` file.
*   **Dynamic Cast Templating**: Create a `cast.md` file to define characters. Use placeholders like `{CHARACTER_NAME}` in your storyboard for easy substitution.
*   **Reference Image Support**: Use a global reference image for all scenes or specify a unique image for each scene directly in the storyboard using `[IMAGE: path/to/image.jpg]`.
*   **AI-Powered Filenaming**: Automatically generates descriptive, editor-friendly filenames (e.g., `MYPROJ_010_ACTION_CAST.mp4`) by using a Gemini model to analyze each scene's prompt.
*   **Flexible Execution Modes**:
    *   `--run-all`: Generate all scenes sequentially.
    *   `--scene-number <N>`: Generate only a single, specific scene.
    *   `--list-scenes`: Preview all parsed scenes without generating.
*   **Robust Error Handling**: Includes retries for network issues, graceful handling of content safety filter blocks, and clear error messages.
*   **Dynamic Reloading**: When using `--run-all`, the script reloads the storyboard and cast files before each scene, allowing you to make on-the-fly edits.
*   **Cost Optimization**: Configured by default to disable audio generation (`generate_audio=False`).
*   **Cloud Storage Integration**: Automatically downloads generated videos from a specified Google Cloud Storage bucket.

## Prerequisites

*   **Python 3.10+**
*   **Google Cloud SDK**: Installed and available in your system's PATH.
*   **Google Cloud Project**: A GCP project with the Vertex AI API enabled.
*   **Google Cloud Storage Bucket**: A bucket to store the output videos.
*   **Required Python Packages**: See `requirements.txt`. Install them using:
    ```bash
    pip install -r requirements.txt
    ```

## Google Cloud Setup

Run the following commands in your terminal to configure your project:

1.  **Login to Google Cloud**:
    ```bash
    gcloud auth login
    ```

2.  **Set your Project ID**:
    ```bash
    gcloud config set project YOUR_PROJECT_ID
    ```

3.  **Enable Required APIs (Vertex AI & Storage)**:
    ```bash
    gcloud services enable aiplatform.googleapis.com storage.googleapis.com
    ```

4.  **Create a Storage Bucket**:
    ```bash
    gcloud storage buckets create gs://YOUR_BUCKET_NAME --location=us-central1
    ```

5.  **Authenticate for Python SDK**:
    ```bash
    gcloud auth application-default login
    ```

## Configuration

The script is configured through a combination of environment variables and command-line arguments.

### Environment Variables
Set these in your shell before running the script.
*   `GOOGLE_CLOUD_PROJECT`: (Required) Your Google Cloud Project ID.
*   `GCS_BUCKET_URI`: (Required) The URI of your output bucket (e.g., `gs://your-bucket-name`).

### Input File Formats
Simple example files (`example_cast.md` and `example_storyboard.md`) are included in this repository.

#### `cast.md`
Define character descriptions using a `KEY: Description` format.
```markdown
# --- Main Characters ---
JESSE_DESC: Jesse "Jess" Sinclair, 28 years old female...
CODY_DESC: Cody "The Bull" Maverick, 32 years old male...
```

#### `storyboard.md`
List each scene with a leading `-`. Use `{KEYS}` from your cast file. Specify reference images with `[IMAGE: "path"]`.
```markdown
# --- ACT 1 ---
# Scene 1
- {JESSE_DESC} bursts from the chute on her horse, racing against the clock...

# Scene 2
- [IMAGE: "path/to/ref.jpg"] At dusk, {MARIA_DESC} performs a daring trick...
```

## Usage

Run the script from your terminal using `python`.

```bash
python generate_veo_videos.py <mode> [options]
```

### Modes (Choose one)
*   `--run-all`: Run all scenes found in the storyboard.
*   `--scene-number <N>`: Run only the scene with the specified number.
*   `--list-scenes`: List all scenes and their details, then exit.

### Options
*   `--storyboard <path>`: Path to the storyboard file (defaults to `storyboard.md`).
*   `--cast <path>`: Path to the cast file (defaults to `cast.md`).
*   `--output-dir <dir>`: Directory to save rendered clips (defaults to `rendered_clips`).
*   `--reference-image <path>`: Path to a global reference image.
*   `--file-prefix <PREFIX>`: A short prefix for AI-generated filenames (defaults to `EVO`).
*   `--duration <seconds>`: Duration of the generated video in seconds (defaults to 8).
*   `--overwrite`: Overwrite existing video files.

### Examples
```bash
# List all scenes from the example storyboard
python generate_veo_videos.py --list-scenes --storyboard example_storyboard.md --cast example_cast.md

# Generate only scene 2 from the default files
python generate_veo_videos.py --scene-number 2

# Generate all scenes with a custom prefix, overwriting any existing files
python generate_veo_videos.py --run-all --overwrite --file-prefix "RODEO"
```