"""
Generates video scenes using Google's Veo model via the Google Gen AI SDK (Vertex AI).
Now supports 'generate_audio=False' to save costs (~33%).

Setup:
1. Requires 'gcloud auth application-default login' to be run once.
2. Requires a GCS bucket (configured below).

How to run:
Use the `create_veo_video.bat` file.
"""

import os
import argparse
import time
import sys
import subprocess
import google.genai as genai
from google.genai import types

# --- Configuration ---
VEO_MODEL_NAME = "veo-3.1-fast-generate-preview"
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

# !!! YOUR BUCKET URI !!!
GCS_BUCKET_URI = os.environ.get("GCS_BUCKET_URI")

# --- Storyboard ---
FEMALE_CAST_MEMBER_DESC = "the female cast member; Beautiful white with fench facial features 25 years old, long brown straight hair to waist length, blue expressive eyes, wearing black European casual clothing , light makeup, natural look, slender physique, USUALLY WEARING ATHLETIC PANTS"

SCENES = {
    "1": {"prompt": f"{FEMALE_CAST_MEMBER_DESC} stands on a balcony overlooking a golden hour sunset over a vast ocean. She turns her head slowly to look back. The mood is heavy with hesitation. Cinematic lighting, realistic, 4k."},
    "2": {"prompt": f"{FEMALE_CAST_MEMBER_DESC} walking down a cobblestone street in an old European city at twilight. Street lamps are just turning on. She looks distant and thoughtful. The camera tracks her from the side. Melancholic wanderlust."},
    "3": {"prompt": f"On the shore, {FEMALE_CAST_MEMBER_DESC} watches the dark ocean waves. The last light of dusk reflects on the water's surface. The camera focuses on her, then gently drifts towards the waves. Serene, deep connection."},
    "4": {"prompt": f"A vast, moody ocean shoreline under a grey sky. {FEMALE_CAST_MEMBER_DESC} stands at the water's edge, the wind blowing her long hair. She stares out at the waves. The scene represents a deep, spiritual connection. Cinematic, slow motion."},
    "4a": {"prompt": f"{FEMALE_CAST_MEMBER_DESC} walks away from the camera wearing athletic pants, her face unseen. The scene is shot in the Central Plaza of Amsterdam with signs in Dutch in the background."},
    "5": {"prompt": "The sky is now a dark, starry night. The Milky Way is visible, reflected in the calm ocean. The scene is peaceful and eternal, a few shooting stars streak by. Magical, ethereal."},
    "6": {"prompt": f"Extreme close-up on {FEMALE_CAST_MEMBER_DESC}'s face, soft natural lighting. She looks down with a gentle, sad smile, remembering something. The background is a soft blur of sand and sea. Emotional, poignant, reflective."},
    "7": {"prompt": f"View from inside a moving car looking out the passenger window at the countryside passing by during a golden sunset. {FEMALE_CAST_MEMBER_DESC}'s reflection is faintly visible in the glass. The feeling of moving on and leaving things behind."},
    "8": {"prompt": "A dreamlike montage of clouds moving rapidly across a purple and orange sky. The camera flies forward through the mist. Ethereal, transcendent, time passing quickly."},
    "9": {"prompt": "The sky transitions to a deep, dark starry night over a calm ocean. The Milky Way is bright and visible. A few shooting stars streak across. The scene is peaceful, eternal, and final. Fade to black feel."}
}

def generate_scene_with_veo(prompt: str, duration_seconds: int = 8, input_video_path: str = None) -> bytes:
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

    if input_video_path:
        if "veo-3.0" in VEO_MODEL_NAME:
            print(f"    ⚠️  Model '{VEO_MODEL_NAME}' does not support video extension.")
        else:
            if not os.path.exists(input_video_path):
                raise FileNotFoundError(f"Input video file not found: {input_video_path}")

            print(f"    - Reading input video for extension: {input_video_path}")
            with open(input_video_path, "rb") as f:
                video_bytes = f.read()
            # Vertex AI expects the video bytes in the request
            generation_kwargs["video"] = types.Video(video_bytes=video_bytes, mime_type="video/mp4")
            
            # API Requirement: Video extension only supports 7 seconds
            if duration_seconds != 7:
                print(f"    ℹ️  Video extension detected. Overriding duration from {duration_seconds}s to 7s.")
                duration_seconds = 7

    print("    - Configuring video generation request...")
    print(f"      - Duration: {duration_seconds}s")
    config = types.GenerateVideosConfig(
        duration_seconds=duration_seconds,
        aspect_ratio="16:9",
        resolution="720p",
        generate_audio=False, # SAVES COST! Supported on Vertex AI.
        output_gcs_uri=GCS_BUCKET_URI, # Required for Vertex AI
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

    # --- CRITICAL FIX: Handle Error as Dictionary or Object ---
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

    # 4. Download using gcloud
    local_filename = "temp_download.mp4" 
    try:
        subprocess.run(
            ["gcloud", "storage", "cp", gcs_uri, local_filename],
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
    parser = argparse.ArgumentParser(description="Generate a video scene using the Veo API.")
    parser.add_argument("--scene-number", type=str, required=True, help="The scene number to generate.")
    parser.add_argument("--input-video", type=str, default=None, help="Path to an input video file to extend.")
    parser.add_argument("--duration", type=int, default=8, help="Duration of the generated video in seconds.")
    parser.add_argument("--resolution", type=str, default="720p", help="Resolution (ignored, always 720p).")
    args = parser.parse_args()

    scene_id = args.scene_number
    if scene_id not in SCENES:
        print(f"❌ Error: Scene number '{scene_id}' not found. Available scenes are: {list(SCENES.keys())}")
        return

    scene_info = SCENES[scene_id]
    prompt = scene_info["prompt"]
    output_filename = f"veo_scene_{scene_id}.mp4"

    if os.path.exists(output_filename):
        print(f"✅ File '{output_filename}' already exists. Skipping generation for Scene {scene_id}.")
        sys.exit(100)

    print(f"\n🎬 Generating Scene {scene_id} (Total scenes: {len(SCENES)})...")
    print(f"    - Prompt: \"{prompt[:80]}...\"")
    print(f"    - Output file: {output_filename}")

    video_bytes = None
    try:
        video_bytes = generate_scene_with_veo(
            prompt,
            duration_seconds=args.duration,
            input_video_path=args.input_video
        )
    except Exception as e:
        error_msg = str(e)
        if args.input_video and ("Input video must be a video that was generated by VEO" in error_msg or "Unsupported video height" in error_msg):
            print(f"\n⚠️  The input video '{args.input_video}' was rejected by the Veo API.")
            print(f"    Reason: {error_msg}")
            print("    🔄 Falling back to text-to-video generation (ignoring input video)...")
            try:
                video_bytes = generate_scene_with_veo(
                    prompt,
                    duration_seconds=args.duration,
                    input_video_path=None
                )
            except Exception as retry_e:
                print(f"\n❌ Fallback generation failed: {retry_e}")
                sys.exit(1)
        else:
            print(f"\n❌ An error occurred during generation for Scene {scene_id}:")
            print(e)
            sys.exit(1)

    print(f"    - Saving video to '{output_filename}'...")
    with open(output_filename, "wb") as f:
        f.write(video_bytes)

    print(f"✅ Scene {scene_id} generated successfully!")

if __name__ == "__main__":
    main()