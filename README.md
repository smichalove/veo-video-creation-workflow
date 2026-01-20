# Veo Batch Video Generation Workflow

`generate_veo_video_v3.py` is a powerful, command-line Python script designed to automate the batch generation of cinematic video scenes using Google's Veo model via the Vertex AI SDK. It streamlines the creative workflow by reading scene descriptions and character details from simple markdown files, managing the entire generation process, and organizing the output.

This repository provides a template for setting up your own automated video creation pipeline.

## Which Script to Use?

This repository contains several versions of the generation script, showing the evolution of the workflow. For new projects, you should almost always use `generate_veo_video_v3.py`.

*   **`generate_veo_video_v3.py` (Recommended)**: The primary, most advanced script. It supports reference images, AI-powered filenaming (with a hardcoded `EVO_` prefix), dynamic reloading, and is fully configurable via the command line. **The rest of this README focuses on this script.**

*   **`generate_veo_video_v2.py` (Legacy)**: A simpler version that reads external `storyboard.md` and `cast.md` files but lacks support for reference images and advanced filenaming. It outputs files like `veo_scene_1.mp4`.

*   **`generate_veo_videos.py` (Legacy)**: An earlier version of the script, similar in function to `v2`. It reads from external markdown files but lacks the more advanced features of `v3` like reference images and AI-powered filenaming.

*   **`generate_veo_video_ext.py` (Legacy Example)**: A very basic script with hardcoded scenes inside the `.py` file. Its main purpose is to serve as a simple example of how the video *extension* feature (passing a video to generate a continuation) was used.

## Key Improvements

This script (`generate_veo_video_v3.py`) represents a significant upgrade over previous versions, focusing on flexibility, automation, and a more professional workflow. Key enhancements include:

*   **Reference Image Support**: Guide the AI with a starting image for better consistency and control, specified either globally (`--reference-image`) or per-scene (`[IMAGE: path]`).
*   **AI-Powered Filenaming**: Instead of generic `scene_1.mp4` files, the script now uses Gemini to generate descriptive, editor-friendly filenames like `EVO_010_ACTION_CAST.mp4`.
*   **Dynamic Reloading**: When using `--run-all`, the script reloads the storyboard and cast files before each scene. This allows you to make on-the-fly edits to your project without stopping the generation process.
*   **Enhanced Flexibility**: All major configurations (file paths, output directory, duration) are now controlled via command-line arguments, removing the need to edit the script itself.
*   **Greater Robustness**: Improved error handling for API issues, content safety filters, and file-not-found errors, with a detailed summary at the end of each run.

## Features

*   **Storyboard-Driven Generation**: Define all your scenes in a simple `storyboard.md` file.
*   **Dynamic Cast Templating**: Create a `cast.md` file to define characters. Use placeholders like `{CHARACTER_NAME}` in your storyboard for easy substitution.
*   **Reference Image Support**: Use a global reference image for all scenes or specify a unique image for each scene directly in the storyboard using `[IMAGE: path/to/image.jpg]`.
*   **AI-Powered Filenaming**: Automatically generates descriptive, editor-friendly filenames (e.g., `EVO_010_ACTION_CAST.mp4`) by using a Gemini model to analyze each scene's prompt.
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
- [IMAGE: path/to/ref.jpg] At dusk, {MARIA_DESC} performs a daring trick...
```

## Usage

Run the script from your terminal using `python`.

```bash
python generate_veo_video_v3.py <mode> [options]
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
*   `--duration <seconds>`: Duration of the generated video in seconds (defaults to 8).
*   `--overwrite`: Overwrite existing video files.

### Examples
```bash
# List all scenes from the example storyboard
python generate_veo_video_v3.py --list-scenes --storyboard example_storyboard.md --cast example_cast.md

# Generate only scene 2 from the default files
python generate_veo_video_v3.py --scene-number 2

# Generate all scenes, overwriting any existing files
python generate_veo_video_v3.py --run-all --overwrite
```

## Customizing Your Project

While the script is powerful out-of-the-box, you can easily tailor it to your specific creative needs. Here are the most common customizations for `generate_veo_video_v3.py`:

### 1. Create Your Own Storyboard and Cast

The easiest way to start your own project is to:
1.  Copy `example_cast.md` to `my_cast.md`.
2.  Copy `example_storyboard.md` to `my_storyboard.md`.
3.  Edit these new files with your own characters and scene descriptions.
4.  Run the script pointing to your new files:
    ```bash
    python generate_veo_video_v3.py --run-all --cast my_cast.md --storyboard my_storyboard.md
    ```
    

### 2. Change the Filename Prefix

The script uses an AI model to generate descriptive filenames, which are prefixed with `EVO_` by default. If you want to change this prefix (e.g., to `MYPROJ_`), you'll need to make a small edit to the script's `generate_scene_filename()` function. Look for the `system_prompt` and the line `if not filename.startswith("EVO_"):` and replace `EVO` with your desired prefix.

### 3. Adjust the Negative Prompt

The script includes a strong negative prompt to prevent the AI from adding unwanted transitions or artifacts. You can customize this in the `generate_scene_with_veo()` function by finding the `negative_prompt` variable and adding or removing terms.

### 4. Update the Veo Model

As Google releases new versions of Veo, you can update the script to use them by modifying the `VEO_MODEL_NAME` constant at the top of the file.
```


## Keywords

Google Veo, Veo Workflow, AI Video Generation, Vertex AI, Batch Video Creation, Python Script, Automated Video Production, Filmmaking AI, Generative AI, Google Cloud Platform.
```