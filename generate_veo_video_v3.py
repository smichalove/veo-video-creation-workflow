"""Generates video scenes using Google's Veo model via the Google Gen AI SDK (Vertex AI).
Version 3: Supports reference images, and specifying storyboard and cast files.
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
import re
import glob
from PIL import Image
import qrcode
import io
import google.genai as genai
from google.genai import types

# --- Configuration ---
VEO_MODEL_NAME = "veo-3.1-generate-preview" # Changed to higher-end model for commercial quality
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

# !!! YOUR BUCKET URI !!!
GCS_BUCKET_URI = os.environ.get("GCS_BUCKET_URI")

CAST_FILE = os.environ.get("CAST_FILE", "cast.md")
STORYBOARD_FILE = os.environ.get("STORYBOARD_FILE", "storyboard.md")

def _load_text_file_robustly(filename):
    """Loads a text file, attempting to decode with UTF-8 and falling back to UTF-16.

    This handles common text editor saving formats on Windows, including BOM.

    Args:
        filename (str): The path to the text file to load.

    Returns:
        list[str]: A list of lines from the file.

    Raises:
        IOError: If the file cannot be read or decoded.
    """
    try:
        # The most common and correct encoding. 'utf-8-sig' handles BOM.
        with open(filename, "r", encoding="utf-8-sig") as f:
            return f.readlines()
    except UnicodeDecodeError:
        # If the above fails, it's often because the file was saved as UTF-16.
        print(f"    - ⚠️  UTF-8 decoding failed for '{os.path.basename(filename)}'. Falling back to UTF-16.")
        try:
            with open(filename, "r", encoding="utf-16") as f:
                return f.readlines()
        except Exception as e:
            # If both fail, we raise an error.
            raise IOError(f"Could not decode file '{filename}' with UTF-8 or UTF-16.") from e
    except Exception as e:
        raise IOError(f"Could not read file '{filename}'.") from e

def load_cast(filename=CAST_FILE):
    """Reads a cast markdown file and parses character descriptions and associated images into a dictionary.

    The function expects a file where each line is in the format 'KEY: Description'.
    It ignores empty lines and lines starting with '#'.

    Args:
        filename (str): The path to the cast markdown file.

    Returns:
        dict: A dictionary mapping character keys to their descriptions and a list of image paths.
    """
    print(f"Loading cast from {filename}...")
    cast = {}
    if not os.path.exists(filename):
        print(f"⚠️  Cast file '{filename}' not found. Using empty cast.")
        return cast

    try:
        lines = _load_text_file_robustly(filename)
    except IOError as e:
        print(f"❌ Error loading cast file: {e}")
        return cast

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        
        # Expecting format KEY: Description
        parts = line.split(":", 1)
        if len(parts) == 2:
            key = parts[0].strip()
            value = parts[1].strip()
            char_data = {"description": value, "image_paths": []}

            # Extract all image tags from the cast description
            image_matches = re.findall(r'\[IMAGE:\s*(.*?)\]', value, re.IGNORECASE)
            if image_matches:
                char_data["image_paths"] = [match.strip().strip('"').strip("'") for match in image_matches]
                char_data["description"] = re.sub(r'\[IMAGE:\s*(.*?)\]', '', value, flags=re.IGNORECASE).strip()
                print(f"  - Found {len(char_data['image_paths'])} character images for {key}: {char_data['image_paths']}")

            cast[key] = char_data
    return cast

def load_storyboard(filename=STORYBOARD_FILE, characters={}):
    """Reads a storyboard markdown file and parses it into groups of scenes.

    The function processes a markdown file where scenes are listed with a '-' prefix.
    Lines starting with '#' are treated as group separators. It also handles
    in-line image references `[IMAGE: path]` and formats prompts using the
    provided characters dictionary.

    Args:
        filename (str): The path to the storyboard markdown file.
        characters (dict): A dictionary of character descriptions used to format
                           the prompts.

    Returns:
        list[list[dict]]: A list of scene groups. Each group is a list of scene
                          dictionaries.
    """
    print(f"Loading storyboard from {filename}...")
    groups = []
    current_group = []
    
    if not os.path.exists(filename):
        print(f"⚠️  Storyboard file '{filename}' not found. Using empty list.")
        return []

    try:
        lines = _load_text_file_robustly(filename)
    except IOError as e:
        print(f"❌ Error loading storyboard file: {e}")
        return []

    for line in lines:
        line = line.strip()
        if not line: continue
        
        if line.startswith("#"):
            if current_group:
                groups.append(current_group)
                current_group = []
        elif line.startswith("-"):
            raw_line = line[1:].strip()
            
            # Extract [IMAGE: path]
            image_path = None
            match = re.search(r'\[IMAGE:\s*(.*?)\]', raw_line, re.IGNORECASE)
            if match:
                image_path = match.group(1).strip().strip('"').strip("'")
                raw_line = raw_line.replace(match.group(0), "").strip()

            raw_prompt = raw_line
            # Replace placeholders with actual character descriptions
            # We'll do character substitution later in get_all_scenes to handle char images
            # For now, just store the raw prompt with placeholders
            prompt = raw_prompt 

            current_group.append({"prompt": prompt, "image": image_path, "raw_line": raw_line})
    
    if current_group:
        groups.append(current_group)
    
    return groups

def create_prompt_slug(prompt: str) -> str:
    """Creates a file-safe slug from the first few words of a prompt.

    This is used as a fallback for filename generation if the AI-based
    naming fails. It cleans the prompt, takes the first three words,
    and joins them with underscores.

    Args:
        prompt (str): The full prompt string for a scene.

    Returns:
        str: A short, file-safe slug (e.g., "a_cinematic_shot").
    """
    # Remove placeholders like {CHARACTER_DESC}
    cleaned_prompt = re.sub(r'\{.*?\}', '', prompt)
    # Remove non-alphanumeric characters (except spaces) and collapse whitespace
    cleaned_prompt = re.sub(r'[^a-zA-Z0-9\s]', '', cleaned_prompt).strip()
    cleaned_prompt = re.sub(r'\s+', ' ', cleaned_prompt)
    # Take the first three words, make them lowercase, and join with underscores
    words = cleaned_prompt.lower().split()
    slug = "_".join(words[:3])
    return slug

def generate_scene_filename(storyboard_line: str, scene_index: int, characters: dict) -> str:
    """Generates a structured, Resolve-friendly filename using an AI model.

    This function sends the raw storyboard line to a Gemini model to classify
    the scene and generate a filename in the format 'EVO_XXX_ACTION_CAST.mp4'.
    It includes robustness fixes to ensure the output is a valid filename.

    Args:
        storyboard_line (str): The raw, unprocessed line from the storyboard file.
        scene_index (int): The 1-based index of the scene.
        characters (dict): The dictionary of cast members to inform the AI.

    Returns:
        str | None: The generated filename as a string, or None if the AI call
                    fails or returns an invalid format.
    """
    # Add a small delay to avoid hitting API rate limits when running many scenes.
    time.sleep(2)

    print("    - Classifying scene for filename generation...")
    try:
        client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
        character_keys_str = ", ".join(characters.keys())

        system_prompt = f"""You are a film production assistant. Respond ONLY with a filename.
Format: EVO_XXX_ACTION_CAST.mp4
Characters: {character_keys_str}
- Use 3-letter initials (e.g., AEL, THA).
- Use 'GEN' if no characters are present.
- MUST end with '.mp4'."""

        scene_num_padded = str(scene_index * 10).zfill(3)
        user_prompt = f"Index: {scene_num_padded} | Line: '{storyboard_line}'"

        response = client.models.generate_content(
            model='gemini-2.0-flash-exp', 
            contents=f"{system_prompt}\n\n{user_prompt}",
            config={'temperature': 0.1}
        )
        
        filename = response.text.strip().replace(" ", "_")
        
        # --- ROBUSTNESS FIX ---
        # If the AI forgot the extension, add it.
        if not filename.lower().endswith(".mp4"):
            filename += ".mp4"
            
        # Ensure it starts with the project prefix
        if not filename.startswith("EVO_"):
            filename = f"EVO_{scene_num_padded}_{filename}"

        print(f"    - ✅ AI-generated filename: {filename}")
        return filename
    except Exception as e:
        print(f"    - ⚠️ AI filename generation failed: {e}. Falling back to slug.")
        return None

def preprocess_image(image_path):
    """Resizes an image to a standard 16:9 1080p format.

    This function opens an image, forces a resize to 1920x1080 (ignoring
    the original aspect ratio to prevent pillar/letterboxing), and returns
    the image data as bytes suitable for the API.

    Args:
        image_path (str): The file path to the image to be processed.

    Returns:
        bytes: The JPEG-encoded bytes of the resized image.
    """
    print(f"      - Resizing '{os.path.basename(image_path)}' to 1920x1080...")
    with Image.open(image_path) as img:
        # Force 16:9 1080p resize (ignores original aspect ratio to kill pillars)
        img_resized = img.resize((1920, 1080), Image.Resampling.LANCZOS)
        
        # Convert to bytes for the API
        img_byte_arr = io.BytesIO()
        img_resized.save(img_byte_arr, format='JPEG')
        return img_byte_arr.getvalue()


def generate_qr_code(url: str, output_path: str, box_size: int = 10, border: int = 4):
    """Generates a QR code image for a given URL and saves it to a file.

    Args:
        url (str): The URL to encode in the QR code.
        output_path (str): The full path where the QR code image will be saved.
        box_size (int): The size of each box (pixel) in the QR code.
        border (int): The thickness of the border around the QR code.

    Returns:
        None
    """
    qr = qrcode.QRCode(
        version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=box_size, border=border,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(output_path)

def get_all_scenes(cast_file, storyboard_file, global_cli_ref_image):
    """Loads and processes cast and storyboard files to return a flat list of scenes.

    This function orchestrates the loading of cast and storyboard data and then
    determines the "effective" reference image for each scene based on a
    hierarchy: an image specified on the scene line itself takes highest
    precedence, followed by the global reference image passed via the command line.

    Args:
        cast_file (str): Path to the cast markdown file.
        storyboard_file (str): Path to the storyboard markdown file.
        global_cli_ref_image (str | None): Path to the global reference image from CLI, if any.

    Returns:
        list[dict]: A flattened list of scene dictionaries, ready for generation.
    """
    characters = load_cast(cast_file)
    if not characters:
        print("⚠️ No characters loaded. Character placeholders will not be substituted.")

    scene_groups = load_storyboard(storyboard_file, characters)

    all_scenes = []
    counter = 1
    for group in scene_groups:
        for scene_data in group:
            # Substitute character descriptions into the prompt
            final_prompt = scene_data["prompt"]
            char_images_for_scene = []
            for char_key, char_info in characters.items():
                placeholder = f"{{{char_key}}}"
                if placeholder in final_prompt:
                    final_prompt = final_prompt.replace(placeholder, char_info["description"])
                    if char_info.get("image_paths"):
                        char_images_for_scene.extend(char_info["image_paths"])

            qr_code_image_path = None
            # Look for "qr code for https://..." in the prompt
            qr_match = re.search(r'qr code for (https?://[^\s]+)', final_prompt, re.IGNORECASE)
            if qr_match:
                qr_url = qr_match.group(1)
                qr_code_filename = f"qr_scene_{counter}.png"
                qr_code_output_dir = os.path.join(os.path.dirname(storyboard_file), "qr_codes") # Save QR codes next to storyboard
                os.makedirs(qr_code_output_dir, exist_ok=True)
                qr_code_image_path = os.path.join(qr_code_output_dir, qr_code_filename)
                
                try:
                    generate_qr_code(qr_url, qr_code_image_path)
                    print(f"  - Generated QR code for '{qr_url}' at '{qr_code_image_path}'")
                    final_prompt = final_prompt.replace(qr_match.group(0), "").strip() # Remove QR instruction from prompt
                except Exception as e:
                    print(f"  - ❌ Error generating QR code for '{qr_url}': {e}")
                    qr_code_image_path = None # Don't use if generation failed

            all_scenes.append({
                "id": str(counter), 
                "prompt": final_prompt,
                "storyboard_image": scene_data.get("image"), # Image explicitly on the storyboard line
                "character_images": char_images_for_scene,      # Images from a character definition
                "raw_line": scene_data.get("raw_line", "")    # Pass raw line for filename generation
            })
            if qr_code_image_path: all_scenes[-1]["qr_code_image"] = qr_code_image_path # Add QR image to scene data
            counter += 1

    # Determine the list of effective reference images for each scene
    for scene in all_scenes:
        effective_images = []

        # 1. Storyboard line image (highest precedence for location/backdrop)
        if scene["storyboard_image"]:
            effective_images.append(scene["storyboard_image"])
            
        # 2. QR Code image (if generated)
        if scene.get("qr_code_image"):
            effective_images.append(scene["qr_code_image"])
            
        # 2. Character images (for consistency)
        if scene["character_images"]:
            effective_images.extend(scene["character_images"])
            
        # 3. Global CLI reference image (lowest precedence)
        if not effective_images and global_cli_ref_image:
            effective_images.append(global_cli_ref_image)

        # Remove duplicates while preserving order
        seen = set()
        effective_images = [x for x in effective_images if not (x in seen or seen.add(x))]
        
        # Handle explicit 'none'
        if any(img.lower() in ['none', 'clear', 'null'] for img in effective_images):
            effective_images = []
            
        # Limit to 3 images (API limit for Veo 3.1)
        scene["effective_images"] = effective_images[:3]
    
    return all_scenes


def generate_scene_with_veo(prompt: str, duration_seconds: int = 8, reference_image_paths: list = None, generate_audio: bool = False) -> bytes:
    """Generates a single video scene using the Veo model on Vertex AI.

    This function handles the entire lifecycle of a single video generation request:
    1. Initializes the Vertex AI client.
    2. Constructs the API request with prompt, config, and optional reference image.
    3. Includes a retry mechanism for the initial API call to handle transient network issues.
    4. Polls the long-running operation until the video is complete.
    5. Handles API errors, including specific feedback for permission issues.
    6. Downloads the final video from the GCS bucket and returns it as bytes.

    Args:
        prompt (str): The text prompt for the video generation.
        duration_seconds (int): The desired duration of the video in seconds.
        reference_image_paths (list | None): A list of file paths to optional reference images.
        generate_audio (bool): Whether to generate audio for the video.

    Returns:
        bytes: The raw bytes of the generated MP4 video file.
    """
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
    
    # These are the ONLY supported configuration keys for Veo 3.1 in the current SDK
    config = types.GenerateVideosConfig(
        duration_seconds=duration_seconds,
        aspect_ratio="16:9",
        resolution="720p",
        generate_audio=generate_audio,
        output_gcs_uri=GCS_BUCKET_URI,
        number_of_videos=1,
        # THE 'RESTRICTION' LEVERS:
        person_generation="allow_adult",
        # Strict negative prompt to prevent internal edits
        negative_prompt="montage, split screen, glitch, transition, cuts, internal cuts, cross-fades, dissolves, morphing, scene changes, fade to black, oversized ears, giant ears, protruding ears, artifacts on frame edge, border, warping, low fidelity, blurry, text, watermark,animaion, cartoon, drawing, illustration,anema",
    )
    generation_kwargs["config"] = config

    # Handle multiple reference images if provided
    if reference_image_paths:
        ref_images_config = []
        for img_path in reference_image_paths:
            if not os.path.exists(img_path):
                raise FileNotFoundError(f"Reference image not found at: {img_path}")
            
            print(f"    - ✅ Using reference image: {os.path.basename(img_path)} (preprocessing to 1080p)...")
            image_bytes = preprocess_image(img_path)
            ref_images_config.append(
                types.VideoGenerationReferenceImage(
                    image=types.Image(image_bytes=image_bytes, mime_type="image/jpeg"),
                    reference_type="asset"
                )
            )
        config.reference_images = ref_images_config

    print("    - Sending prompt to the Veo API...")
    
    # 1. Start the operation
    operation = None
    for attempt in range(3):
        try:
            operation = client.models.generate_videos(**generation_kwargs)
            break
        except Exception as e:
            print(f"\n❌ API Call Failed (Attempt {attempt+1}/3): {e}")
            if "403" in str(e):
                 print("\n⚠️  Permission Error: Run 'gcloud auth application-default login' in your terminal.")
                 raise e
            if attempt < 2:
                print("    🔄 Connection issue. Retrying in 5 seconds...")
                time.sleep(5)
            else:
                raise e
    
    print("    - Operation started. Waiting for video generation (this will take ~60-90 seconds)...")

    # 2. Polling loop
    while not operation.done:
        time.sleep(10)
        print("      ...still generating...")
        try:
            operation = client.operations.get(operation)
        except Exception as e:
            print(f"      ⚠️  Warning: Connection issue while polling: {e}")
            print("      🔄 Retrying status check...")
            continue

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
    if operation.result and hasattr(operation.result, 'generated_videos') and operation.result.generated_videos:
         gcs_uri = operation.result.generated_videos[0].video.uri
    else:
        # If we get here, it's a very strange edge case (no error, but no result)
        print(f"⚠️  No video returned. The prompt likely triggered the 'Dangerous Content' safety filter, which cannot be disabled via the SDK currently.\nDEBUG DUMP: {operation}")
        raise RuntimeError("Video generation completed but returned no content (likely blocked).")

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
    """Main entry point for the script.

    Handles command-line argument parsing, determines which scenes to process
    (all, a single one, or list), and then iterates through the generation
    loop. It manages dynamic reloading of storyboards, robust file existence
    checks, AI-based filename generation, and final summary reporting.

    Args:
        None (Parses command-line arguments from sys.argv).

    Returns:
        None
    """
    # --- 1. Argument Parsing ---
    parser = argparse.ArgumentParser(description="Generate a video scene using the Veo API (V3 - With Reference Image).")
    parser.add_argument("--scene-number", type=str, help="The specific scene number to generate (optional).")
    parser.add_argument("--run-all", action="store_true", help="Run all scenes sequentially.")
    parser.add_argument("--list-scenes", action="store_true", help="List all scenes and exit.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing video files.")
    parser.add_argument("--generate-audio", action="store_true", help="Enable audio generation.")
    parser.add_argument("--duration", type=int, default=8, help="Duration of the generated video in seconds.")
    parser.add_argument("--resolution", type=str, default="720p", help="Resolution (ignored, always 720p).")
    parser.add_argument("--reference-image", type=str, help="Path to a reference image to use for the generation.")
    parser.add_argument("--storyboard", type=str, default=STORYBOARD_FILE, help="Path to the storyboard markdown file.")
    parser.add_argument("--cast", type=str, default=CAST_FILE, help="Path to the cast markdown file.")
    parser.add_argument("--output-dir", type=str, default="rendered_clips", help="Directory to save the rendered video clips.")
    args = parser.parse_args()

    # Load cast once to pass to filename generator, will be reloaded in loop if needed
    characters = load_cast(args.cast)

    # --- 2. Scene Discovery and Scoping ---
    # Initial load to determine the scope of the run and handle --list-scenes
    initial_scenes = get_all_scenes(args.cast, args.storyboard, args.reference_image)

    # Determine which scenes to run
    # This block handles the different run modes: --list-scenes, --run-all, or --scene-number.
    scenes_to_run = []
    if args.list_scenes: # This path is for listing only, not for actual generation
        print(f"--- Scene List ({len(initial_scenes)} total) ---")
        for scene in initial_scenes:
            img_info = f" [Refs: {', '.join(scene['effective_images'])}]" if scene['effective_images'] else ""
            print(f"Scene {scene['id']}: {scene['prompt']}{img_info}")
        return
    elif args.run_all:
        scenes_to_run = initial_scenes
    elif args.scene_number:
        # Find the specific scene
        found = next((s for s in initial_scenes if s["id"] == args.scene_number), None)
        if found:
            scenes_to_run = [found]
        else:
            print(f"❌ Error: Scene number '{args.scene_number}' not found. Valid numbers are 1 to {len(initial_scenes)}.")
            return
    else:
        print("❌ Error: You must specify --scene-number <N>, --run-all, or --list-scenes")
        return

    # Use the output directory from arguments and create it if it doesn't exist
    os.makedirs(args.output_dir, exist_ok=True)

    # --- 3. Main Generation Loop ---
    print(f"--- Processing {len(scenes_to_run)} scenes ---")
    
    # Initialize lists for tracking the outcome of the run for the final summary.
    successful_scenes = []
    skipped_scenes = []
    failed_file_not_found = []
    failed_safety_filter = []
    failed_other = []

    for initial_scene in scenes_to_run:
        # --- a. Dynamic Reload ---
        scene_id = initial_scene["id"]

        # --- DYNAMIC RELOAD ---
        # For run-all, reload the storyboard and cast to get the latest data for the current scene.
        # This allows for making changes to the .md files while the script is running.
        if args.run_all:
            print(f"\n🔄 Reloading storyboard and cast files for Scene {scene_id} (dynamic update)...")
            characters = load_cast(args.cast) # Reload cast for dynamic updates
        
        current_scene_list = get_all_scenes(args.cast, args.storyboard, args.reference_image)
        scene_data = next((s for s in current_scene_list if s["id"] == scene_id), None)

        if not scene_data:
            print(f"    - ⚠️ Scene {scene_id} no longer found in storyboard. Skipping.")
            skipped_scenes.append(scene_id)
            continue

        # --- b. Robust File Existence Check ---
        # Checks for existing files using a pattern to avoid re-rendering if the AI name changes slightly.
        if not args.overwrite:
            scene_num_padded = str(int(scene_id) * 10).zfill(3)
            
            # Check for new AI-named files using a pattern
            ai_pattern = os.path.join(args.output_dir, f"EVO_{scene_num_padded}_*.mp4")
            existing_ai_files = glob.glob(ai_pattern)

            # Check for old slug-based files
            slug = create_prompt_slug(scene_data["prompt"])
            slug_filename = os.path.join(args.output_dir, f"scene_{scene_id}_{slug}.mp4")
            
            all_existing = existing_ai_files
            if os.path.exists(slug_filename):
                all_existing.append(slug_filename)

            if all_existing:
                existing_file_basename = os.path.basename(all_existing[0])
                print(f"\n✅ File '{existing_file_basename}' already exists for Scene {scene_id}. Skipping generation.")
                skipped_scenes.append(scene_id)
                continue
        
        # --- c. Filename Generation (only if not skipping) ---
        # Calls the AI to generate a professional filename, with a fallback to a simple slug.
        prompt = scene_data["prompt"]
        ref_images = scene_data["effective_images"]
        raw_line = scene_data["raw_line"]

        ai_filename = generate_scene_filename(raw_line, int(scene_id), characters)
        
        if ai_filename:
            output_filename = os.path.join(args.output_dir, ai_filename)
        else:
            slug = create_prompt_slug(prompt)
            output_filename = os.path.join(args.output_dir, f"scene_{scene_id}_{slug}.mp4")
            print(f"    - Fallback slug filename: {os.path.basename(output_filename)}")
            
        print(f"\n🎬 Generating Scene {scene_id}...")
        print(f"    - Prompt: \"{prompt}\"")
        if ref_images:
            print(f"    - Reference Images: {', '.join([os.path.basename(img) for img in ref_images])}")
        print(f"    - Output file: {output_filename}")

        # --- d. Video Generation and Error Handling ---
        video_bytes = None
        try:
            video_bytes = generate_scene_with_veo(
                prompt,
                duration_seconds=args.duration,
                reference_image_paths=ref_images,
                generate_audio=args.generate_audio
            )
        except RuntimeError as e:
            # Gracefully handle safety filter blocks without crashing the whole script.
            if "blocked" in str(e).lower() or "dangerous content" in str(e).lower() or "sensitive words" in str(e).lower():
                print(f"\n⚠️  WARNING: Scene {scene_id} was blocked by safety filters. Skipping.")
                failed_safety_filter.append(scene_id)
                continue
            else:
                # For other runtime errors, exit as before
                print(f"\n❌ An unrecoverable error occurred during generation for Scene {scene_id}:")
                print(e)
                failed_other.append(scene_id)
                continue # Continue to the next scene instead of exiting
        except FileNotFoundError as e:
            print(f"\n⚠️  WARNING: Skipping Scene {scene_id} because a file was not found.")
            print(f"   Error: {e}")
            failed_file_not_found.append(scene_id)
            continue
        except Exception as e:
            # For any other unexpected exceptions
            print(f"\n❌ An unexpected error occurred during generation for Scene {scene_id}:")
            print(e)
            sys.exit(1)

        # --- e. Save and Cooldown ---
        print(f"    - Saving video to '{output_filename}'...")
        with open(output_filename, "wb") as f:
            f.write(video_bytes)

        successful_scenes.append(scene_id)
        print(f"✅ Scene {scene_id} generated successfully!")
        
        # Cooldown if there are more scenes to run
        if args.run_all and scene_id != scenes_to_run[-1]["id"]:
             print("    - Cooling down for 60 seconds...")
             time.sleep(30)
    
    # --- 4. Final Summary ---
    print("\n\n--- Run Summary ---")
    print(f"✅ Successful: {len(successful_scenes)} ({', '.join(successful_scenes)})")
    print(f"⏭️  Skipped (already existed): {len(skipped_scenes)} ({', '.join(skipped_scenes)})")
    print(f"❌ Failed (File Not Found): {len(failed_file_not_found)} ({', '.join(failed_file_not_found)})")
    print(f"❌ Failed (Safety Filter): {len(failed_safety_filter)} ({', '.join(failed_safety_filter)})")
    print(f"❌ Failed (Other Error): {len(failed_other)} ({', '.join(failed_other)})")
    print("---------------------\n")

if __name__ == "__main__":
    main()
