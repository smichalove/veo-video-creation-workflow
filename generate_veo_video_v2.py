"""
Generates video scenes using Google's Veo model via the Google Gen AI SDK (Vertex AI).
Version 2: Standalone Text-to-Video (No Video Extension).
Supports 'generate_audio=False' to save costs.

Setup:
1. Requires 'gcloud auth application-default login' to be run once.
2. Requires a GCS bucket.
"""

import os
import argparse
import time
import sys
import subprocess
import shutil
import platform
import google.genai as genai
from google.genai import types

# --- Configuration ---
VEO_MODEL_NAME = "veo-3.1-fast-generate-preview"
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

# !!! YOUR BUCKET URI !!!
GCS_BUCKET_URI = os.environ.get("GCS_BUCKET_URI")

def load_cast(filename="cast.md"):
    """Reads the cast markdown file and parses character descriptions."""
    cast = {}
    if not os.path.exists(filename):
        print(f"⚠️  Cast file '{filename}' not found. Using empty cast.")
        return cast

    with open(filename, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            
            # Expecting format KEY: Description
            parts = line.split(":", 1)
            if len(parts) == 2:
                key = parts[0].strip()
                value = parts[1].strip()
                cast[key] = value
    return cast

# Load characters
CHARACTERS = load_cast()

def load_storyboard(filename="storyboard.md"):
    """Reads the storyboard markdown file and parses scenes."""
    groups = []
    current_group = []
    
    if not os.path.exists(filename):
        print(f"⚠️  Storyboard file '{filename}' not found. Using empty list.")
        return []

    with open(filename, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            
            if line.startswith("#"):
                if current_group:
                    groups.append(current_group)
                    current_group = []
            elif line.startswith("-"):
                raw_prompt = line[1:].strip()
                # Replace placeholders with actual character descriptions
                try:
                    prompt = raw_prompt.format(**CHARACTERS)
                except Exception as e:
                    print(f"⚠️  Formatting error in storyboard line: {line}\n    Error: {e}")
                    prompt = raw_prompt
                current_group.append({"prompt": prompt})
    
    if current_group:
        groups.append(current_group)
    
    return groups

# Load scenes from the markdown file
SCENE_GROUPS = load_storyboard()

def generate_scene_with_veo(prompt: str, duration_seconds: int = 8) -> bytes:
    """Generates a video using Veo on Vertex AI and downloads it from GCS."""
    if not PROJECT_ID or not GCS_BUCKET_URI:
        raise ValueError("Missing configuration. Ensure GOOGLE_CLOUD_PROJECT and GCS_BUCKET_URI are set.")

    print(f"    - Initializing Gemini client for Vertex AI...")
    client = genai.Client(
        vertexai=True,
        project=PROJECT_ID,
        location=LOCATION
    )

    generation_kwargs = {
        "model": VEO_MODEL_NAME,
        "prompt": prompt,
    }

    print("    - Configuring video generation request...")
    print(f"      - Duration: {duration_seconds}s")
    config = types.GenerateVideosConfig(
        duration_seconds=duration_seconds,
        aspect_ratio="16:9",
        resolution="720p",
        generate_audio=False,          # COST SAVING: No Audio (~33% off)
        output_gcs_uri=GCS_BUCKET_URI, # Required for Vertex AI
        number_of_videos=1             # COST SAVING: Forces 1 video instead of default 4
    )
    generation_kwargs["config"] = config

    print("    - Sending prompt to the Veo API...")
    
    # 1. Start the operation
    try:
        operation = client.models.generate_videos(**generation_kwargs)
    except Exception as e:
        print(f"\n❌ API Call Failed: {e}")
        # Check for common Vertex AI auth issues
        if "403" in str(e):
             print("\n⚠️  Permission Error: Run 'gcloud auth application-default login' in your terminal.")
        raise e
    
    print("    - Operation started. Waiting for video generation (this will take ~60-90 seconds)...")

    # 2. Polling loop
    while not operation.done:
        time.sleep(10)
        print("      ...still generating...")
        operation = client.operations.get(operation)

    print("    - Video generation call complete.")

    # --- Handle Error as Dictionary or Object ---
    if operation.error:
        print(f"\n❌ VIDEO GENERATION FAILED.")
        
        # Helper to safely get data whether it's a dict or an object
        err = operation.error
        if isinstance(err, dict):
            code = err.get('code', 'Unknown')
            message = err.get('message', 'Unknown')
        else:
            code = getattr(err, 'code', 'Unknown')
            message = getattr(err, 'message', 'Unknown')
            
        print(f"   Error Code: {code}")
        print(f"   Error Message: {message}")
        raise RuntimeError(f"Vertex AI Error: {message}")

    # Retrieve the GCS URI from the result
    if operation.result and hasattr(operation.result, 'generated_videos'):
         gcs_uri = operation.result.generated_videos[0].video.uri
    else:
        # If we get here, it's a very strange edge case (no error, but no result)
        print(f"DEBUG DUMP: {operation}")
        raise RuntimeError("Video generated, but could not retrieve GCS URI (Result was empty).")

    print(f"    - Video generated at: {gcs_uri}")
    print("    - Downloading video from Cloud Storage...")

    # Detect OS and find gcloud executable
    current_os = platform.system()
    gcloud_exec = shutil.which("gcloud")
    if not gcloud_exec:
        gcloud_exec = "gcloud" # Fallback to system PATH lookup
    
    print(f"      - Detected OS: {current_os}")

    # 4. Download using gcloud
    local_filename = "temp_download.mp4" 
    try:
        subprocess.run(
            [gcloud_exec, "storage", "cp", gcs_uri, local_filename],
            check=True,
            shell=True if os.name == 'nt' else False 
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to download file from GCS: {e}")

    # Read the downloaded file into bytes
    with open(local_filename, "rb") as f:
        final_bytes = f.read()
    
    # Cleanup temp file
    if os.path.exists(local_filename):
        os.remove(local_filename)

    return final_bytes

def main():
    """Parses arguments and orchestrates the video generation for a single scene."""
    parser = argparse.ArgumentParser(description="Generate a video scene using the Veo API (V2 - No Extension).")
    parser.add_argument("--scene-number", type=str, help="The specific scene number to generate (optional).")
    parser.add_argument("--run-all", action="store_true", help="Run all scenes sequentially.")
    parser.add_argument("--list-scenes", action="store_true", help="List all scenes and exit.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing video files.")
    parser.add_argument("--duration", type=int, default=8, help="Duration of the generated video in seconds.")
    parser.add_argument("--resolution", type=str, default="720p", help="Resolution (ignored, always 720p).")
    args = parser.parse_args()

    # Flatten the list of lists into a single list of (scene_num, prompt) tuples
    all_scenes = []
    counter = 1
    for group in SCENE_GROUPS:
        for scene_data in group:
            all_scenes.append((str(counter), scene_data["prompt"]))
            counter += 1

    # Determine which scenes to run
    scenes_to_run = []
    if args.list_scenes:
        print(f"--- Scene List ({len(all_scenes)} total) ---")
        for num, prompt in all_scenes:
            print(f"Scene {num}: {prompt}")
        return
    elif args.run_all:
        scenes_to_run = all_scenes
    elif args.scene_number:
        # Find the specific scene
        found = next((s for s in all_scenes if s[0] == args.scene_number), None)
        if found:
            scenes_to_run = [found]
        else:
            print(f"❌ Error: Scene number '{args.scene_number}' not found. Valid numbers are 1 to {len(all_scenes)}.")
            return
    else:
        print("❌ Error: You must specify --scene-number <N>, --run-all, or --list-scenes")
        return

    print(f"--- Processing {len(scenes_to_run)} scenes ---")

    for scene_id, prompt in scenes_to_run:
        output_filename = f"veo_scene_{scene_id}.mp4"

        if os.path.exists(output_filename) and not args.overwrite:
            print(f"\n✅ File '{output_filename}' already exists. Skipping generation for Scene {scene_id}.")
            continue

        print(f"\n🎬 Generating Scene {scene_id}...")
        print(f"    - Prompt: \"{prompt}\"")
        print(f"    - Output file: {output_filename}")

        video_bytes = None
        try:
            video_bytes = generate_scene_with_veo(
                prompt,
                duration_seconds=args.duration
            )
        except Exception as e:
            print(f"\n❌ An error occurred during generation for Scene {scene_id}:")
            print(e)
            # In run-all mode, we might want to exit or continue. 
            # Exiting is safer to prevent quota waste on repeated errors.
            sys.exit(1)

        print(f"    - Saving video to '{output_filename}'...")
        with open(output_filename, "wb") as f:
            f.write(video_bytes)

        print(f"✅ Scene {scene_id} generated successfully!")
        
        # Cooldown if there are more scenes to run
        if args.run_all and scene_id != scenes_to_run[-1][0]:
             print("    - Cooling down for 60 seconds...")
             time.sleep(60)

if __name__ == "__main__":
    main()