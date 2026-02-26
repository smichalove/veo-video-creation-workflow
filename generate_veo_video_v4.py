"""Generates video scenes using Google's Veo model via the Google Gen AI SDK (Vertex AI).
Version 3: Supports reference images, and specifying storyboard and cast files.
Supports 'generate_audio=False' to save costs.

Setup:
1. Install required packages: `pip install -r requirements.txt`
2. Authenticate with Google Cloud: `gcloud auth application-default login`
3. Ensure you have a GCS bucket and the `GCS_BUCKET_URI` environment variable is set.
"""

import os
import argparse
import time
import sys
import subprocess
import shutil
import platform
import re
import tempfile
import mimetypes
import glob
from PIL import Image
import qrcode
import io
from google.cloud import storage
import google.genai as genai
from google.genai import types
import requests
from urllib.parse import urlparse
import google.auth
# --- Configuration ---
# VEO_MODEL_NAME = "veo-3.1-generate-preview" # <--- THIS IS THE EXPENSIVE ONE ($$$)
VEO_MODEL_NAME = "veo-3.1-fast-generate-preview" # <--- USE THIS ONE ($)
# --- Configuration Update ---
# VEO_MODEL_NAME = "veo-3.1-fast-generate-preview" # Keep this as is ($)
GEMINI_MODEL_NAME = "gemini-2.5-flash"      # Updated to a valid model
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
                # Remove images from description
                value = re.sub(r'\[IMAGE:\s*(.*?)\]', '', value, flags=re.IGNORECASE).strip()
            
            # --- CLEAN DESCRIPTION ---
            # Remove labels like DOCSTRING:, FACIAL:, PROMPTING:, CONSTRAINTS:, ETHNICITY:, 1940s:, MODERN:, ROLE:
            # This makes the final substituted prompt much cleaner.
            labels_to_remove = [
                r'DOCSTRING:', r'FACIAL:', r'PROMPTING:', r'CONSTRAINTS:', r'ETHNICITY:', 
                r'1940s:', r'MODERN:', r'ROLE:', r'CINEMATIC CHARACTER STUDY:', r'DEMEANOR:', r'Physic:'
            ]
            for label in labels_to_remove:
                value = re.sub(label, '', value, flags=re.IGNORECASE).strip()
            
            char_data["description"] = value
            cast[key] = char_data
            if char_data["image_paths"]:
                print(f"  - Found {len(char_data['image_paths'])} character images for {key}")
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
            
            # Extract ALL [IMAGE: path] tags from the line
            image_paths = []
            image_matches = re.findall(r'\[IMAGE:\s*(.*?)\]', raw_line, re.IGNORECASE)
            if image_matches:
                for match_text in image_matches:
                    path = match_text.strip().strip('"').strip("'")
                    image_paths.append(path)
                # Remove ALL image tags from the prompt text
                raw_line = re.sub(r'\[IMAGE:\s*(.*?)\]', '', raw_line, flags=re.IGNORECASE).strip()

            prompt = raw_line 
            current_group.append({
                "prompt": prompt, 
                "images": image_paths, # Store as a list
                "raw_line": raw_line
            })
    
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

def improve_prompt_with_gemini(prompt: str, story_context: str, cast_context: str) -> str:
    """
    Uses the Gemini 2.0 Flash Experimental model to dynamically improve a scene prompt.
    
    This function intercepts the base prompt before it is sent to Veo 3.1. It provides 
    the full story context and the cast definitions to the Gemini model, instructing 
    it to enhance the cinematic, lighting, and textural descriptors of the prompt 
    while strictly preserving narrative actions and constraints (e.g., 'NO GLASSES').
    
    Args:
        prompt (str): The raw base prompt for the individual scene to be improved.
        story_context (str): The full text of the story/script to provide narrative context.
        cast_context (str): The full text of the cast definitions to provide character context.
        
    Returns:
        str: The improved, cinematic prompt. If the API call fails, it falls back to 
             returning the original, unmodified prompt.
    """
    print("    - Improving prompt with Gemini Predictive Model...")
    
    try:
        # Initialize the Vertex AI Gemini client
        client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
        
        # Load the system instruction from configuration file
        base_dir = os.path.dirname(os.path.abspath(__file__))
        possible_paths = [
            os.path.join(base_dir, "gemini_prompt_config.txt"),
            os.path.join(base_dir, "it came and went", "gemini_prompt_config.txt"),
            os.path.join(os.getcwd(), "gemini_prompt_config.txt")
        ]
        
        system_instruction = None
        for config_path in possible_paths:
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    system_instruction = f.read().strip()
                print(f"    - ✅ Loaded Gemini system prompt from: {config_path}")
                break

        if not system_instruction:
            print(f"    - ⚠️ Gemini configuration file not found at any expected location. Using fallback system instruction.")
            system_instruction = """You are an expert cinematic prompt engineer for a text-to-video AI model (Veo).
Your job is to take a scene description, the overall story context, and the cast descriptions, and rewrite the prompt to be highly visual, cinematic, and optimized for Veo.

CRITICAL INSTRUCTIONS:
1. Preserve all placeholders like {CHARACTER_KEY} or {LEAH_DESC} exactly as they are in the input. 
2. Use the character information provided in the [CHARACTER: {KEY} - Description] blocks to inform the visual details of the scene (e.g. wardrobe, hair, facial features).
3. Ensure every character mentioned in the input prompt is represented in your output.
4. Maintain all specific constraints (like 'NO GLASSES' or specific wardrobe).
5. Do not add new actions or change the narrative. 
6. Enhance the visual descriptors (lighting, camera angle, mood, film stock, textures).
7. Respond ONLY with the improved prompt. Do not include any explanations or conversational text."""

        # --- PRE-SUBSTITUTION STRATEGY ---
        # We inject the character descriptions directly into the prompt to ensure Gemini sees them.
        # However, we keep the placeholders so Gemini can "write around" them.
        for char_key, char_description in cast_context.items():
            placeholder = f"{{{char_key}}}"
            if placeholder in prompt:
                # We replace "{KEY}" with "[CHARACTER: {KEY} - Description]"
                injected_desc = f"[CHARACTER: {placeholder} - {char_description}]"
                prompt = prompt.replace(placeholder, injected_desc)

        # Combine the user's specific context and the prompt to be rewritten
        user_message = f"""Here is the overall story context for narrative continuity:
---
{story_context}
---

Please improve this specific scene prompt for Veo. 
The character descriptions are already injected in [CHARACTER: {{KEY}} - Description] blocks within the prompt.
Use them for visual details but PRESERVE the {{KEY}} placeholders exactly in your final output.

SCENE TO IMPROVE:
{prompt}"""

        # print("\n" + "~"*80)
        # print("🧠 ACTIVE GEMINI SYSTEM INSTRUCTION (From Config File):")
        # print("~"*80)
        # print(system_instruction)
        
        # print("\n" + "~"*80)
        # print("📥 SENDING SCENE & CAST CONTEXT TO GEMINI:")
        # print("~"*80)
        # print(user_message)
        # print("~"*80 + "\n")

        # Execute the model request with a retry loop to handle 429 Resource Exhausted limits
        for attempt in range(4):
            try:
                response = client.models.generate_content(
                    model=GEMINI_MODEL_NAME, 
                    contents=user_message,
                    config={
                        'temperature': 0.7,
                        'system_instruction': system_instruction
                    }
                )
                
                improved_prompt = str(response.text).strip()
                
                # print("\n" + "~"*80)
                # print("✨ GEMINI RETURNED (IMPROVED PROMPT):")
                # print("~"*80)
                # print(improved_prompt)
                # print("~"*80 + "\n")
                print(f"    - ✨ Improved Prompt: {improved_prompt[:100]}...") # Just print a snippet
                
                return improved_prompt
                
            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    print(f"    - ⏳ Gemini rate limit reached (Attempt {attempt+1}/4). Retrying in 10 seconds...")
                    time.sleep(10)
                else:
                    # If it's a different error, break the retry loop and fall through to the outer exception
                    raise e
                    
        # If we exit the loop, all retries failed.
        print(f"    - ⚠️ Prompt improvement failed after multiple retries due to rate limits. Falling back to original prompt.")
        return prompt
        
    except Exception as e:
        # Graceful fallback: Use the original prompt if Gemini fails for any other non-rate-limit reason
        print(f"    - ⚠️ Prompt improvement failed: {e}. Falling back to original prompt.")
        return prompt

def generate_scene_filename(storyboard_line: str, scene_index: int, characters: dict) -> str:
    """Generates a structured, Resolve-friendly filename using an AI model.

    This function sends the raw storyboard line to a Gemini model to classify
    the scene and generate a filename in the format 'FMP_XXX_ACTION_CAST.mp4'.
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
Format: FMP_XXX_ACTION_CAST.mp4
Characters: {character_keys_str}
- Use 3-letter initials (e.g., AEL, THA).
- Use 'GEN' if no characters are present.
- MUST end with '.mp4'."""

        scene_num_padded = str(scene_index * 10).zfill(3)
        user_prompt = f"Index: {scene_num_padded} | Line: '{storyboard_line}'"

        response = client.models.generate_content(
            model=GEMINI_MODEL_NAME, 
            contents=f"{system_prompt}\n\n{user_prompt}",
            config={'temperature': 0.1}
        )
        
        filename = response.text.strip().replace(" ", "_")
        
        # --- ROBUSTNESS FIX ---
        # If the AI forgot the extension, add it.
        if not filename.lower().endswith(".mp4"):
            filename += ".mp4"
            
        # Ensure it starts with the exact correct prefix (FMP_ + scene_num_padded + _)
        expected_prefix = f"FMP_{scene_num_padded}_"
        if not filename.startswith(expected_prefix):
            if filename.startswith("FMP_"):
                # Try to strip out whatever was put in the XXX place (e.g. FMP_CEL_...)
                parts = filename.split("_", 2)
                if len(parts) >= 3:
                    filename = expected_prefix + parts[2]
                else:
                    filename = expected_prefix + filename[4:]
            else:
                filename = expected_prefix + filename

        print(f"    - ✅ AI-generated filename: {filename}")
        return filename
    except Exception as e:
        print(f"    - ⚠️ AI filename generation failed: {e}. Falling back to slug.")
        return None

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

def get_all_scenes(cast_file, storyboard_file, global_cli_ref_image) -> tuple[list, dict]:
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
        tuple[list, dict]: A tuple containing:
            - A flattened list of scene dictionaries, ready for generation.
            - The loaded characters dictionary.
    """
    characters = load_cast(cast_file)
    if not characters:
        print("⚠️ No characters loaded. Character placeholders will not be substituted.")

    scene_groups = load_storyboard(storyboard_file, characters)

    all_scenes = []
    counter = 1
    for group in scene_groups:
        for scene_data in group:
            # Extract character images but DO NOT substitute descriptions yet
            # We want to send the clean, short prompt to Gemini so it doesn't get confused
            final_prompt = scene_data["prompt"]
            
            # Map of char_key -> list of its images
            char_images_by_key = {}
            for char_key, char_info in characters.items():
                placeholder = f"{{{char_key}}}"
                if placeholder in final_prompt:
                    if char_info["image_paths"]:
                        char_images_by_key[char_key] = char_info["image_paths"]

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
                "storyboard_images": scene_data.get("images", []), # List of images from storyboard line
                "char_images_by_key": char_images_by_key,         # Grouped images for fair selection
                "raw_line": scene_data.get("raw_line", "")        # Pass raw line for filename generation
            })
            if qr_code_image_path: all_scenes[-1]["qr_code_image"] = qr_code_image_path # Add QR image to scene data
            counter += 1

    # Determine the list of effective reference images for each scene
    for scene in all_scenes:
        effective_images = []

        # 1. Storyboard line images (highest precedence for location/backdrop)
        if scene["storyboard_images"]:
            effective_images.extend(scene["storyboard_images"])
            
        # 2. QR Code image (if generated)
        if scene.get("qr_code_image"):
            effective_images.append(scene["qr_code_image"])
            
        # 2. Character images (FAIR SELECTION)
        # We want to ensure that if there are multiple characters, at least one image 
        # from each is included before we start doubling up.
        if scene["char_images_by_key"]:
            char_keys = sorted(scene["char_images_by_key"].keys())
            
            # First pass: one image from each character
            for key in char_keys:
                if scene["char_images_by_key"][key]:
                    effective_images.append(scene["char_images_by_key"][key][0])
            
            # Second pass: fill remaining slots (if any) with additional images
            # Veo 3.1 limit is 3, so we probably only have 0-1 slots left.
            if len(effective_images) < 3:
                for key in char_keys:
                    for extra_img in scene["char_images_by_key"][key][1:]:
                        if extra_img not in effective_images:
                            effective_images.append(extra_img)
                        if len(effective_images) >= 3:
                            break
                    if len(effective_images) >= 3:
                        break
            
        # 3. Global CLI reference image (lowest precedence)
        if not effective_images and global_cli_ref_image:
            effective_images.append(global_cli_ref_image)

        # Remove duplicates while preserving order
        seen = set()
        unique_images = []
        for img in effective_images:
            if img.lower() not in seen:
                unique_images.append(img)
                seen.add(img.lower())
        
        # Handle explicit 'none'
        if any(img.lower() in ['none', 'clear', 'null'] for img in unique_images):
            unique_images = []
            
        # Limit to 3 images (API limit for Veo 3.1)
        scene["effective_images"] = unique_images[:3]
    
    return all_scenes, characters

def upload_to_gcs_and_get_uri(local_path: str, gcs_bucket_name: str, destination_folder: str = "reference_images") -> str:
    """Uploads a local file to GCS if it doesn't already exist and returns its GCS URI.

    Args:
        local_path (str): The path to the local file to upload.
        gcs_bucket_name (str): The name of the target GCS bucket.
        destination_folder (str): The subfolder within the bucket to upload to.

    Returns:
        str: The `gs://` URI of the file in GCS.
    """
    try:
        storage_client = storage.Client(project=PROJECT_ID)
        bucket = storage_client.bucket(gcs_bucket_name)
        
        filename = os.path.basename(local_path)
        destination_blob_name = f"{destination_folder}/{filename}"
        blob = bucket.blob(destination_blob_name)

        if not blob.exists():
            print(f"      - Uploading '{filename}' to GCS bucket '{gcs_bucket_name}'...")
            
            # Explicitly set the content type during upload. The Veo API backend requires
            # this metadata to be set on the GCS object when using a gs:// URI.
            # This directly fixes the 'image mime type is empty' error for local files.
            mime_type, _ = mimetypes.guess_type(local_path)
            if not mime_type:
                mime_type = "image/jpeg" # A safe fallback for image files
                print(f"      - ⚠️  Could not guess mime type for '{filename}'. Using default '{mime_type}'.")

            blob.upload_from_filename(local_path, content_type=mime_type)
            print(f"      - ✅ Upload complete.")
        return f"gs://{gcs_bucket_name}/{destination_blob_name}"
    except Exception as e:
        print(f"      - ❌ Failed to upload '{os.path.basename(local_path)}' to GCS. Hint: Ensure you have 'Storage Object Creator' permissions on the bucket.")
        raise e

def _prepare_image_for_api(img_path: str, gcs_bucket_name: str) -> types.Image:
    """Prepares a single image (local or URL) for the Veo API.

    This helper function encapsulates the logic for handling different image sources:
    - GCS URLs are converted to gs:// URIs.
    - Google Photos URLs are fetched using an authenticated session.
    - Other public URLs are fetched with a standard request.
    - Local file paths are uploaded to GCS and referenced via gs:// URI.

    Args:
        img_path (str): The path or URL of the image.
        gcs_bucket_name (str): The name of the GCS bucket for uploads.

    Returns:
        types.Image: An Image object configured for the API.
    """
    print(f"    - ✅ Preparing reference image: {os.path.basename(img_path)}...")
    parsed_url = urlparse(img_path)
    is_url = all([parsed_url.scheme, parsed_url.netloc])

    if is_url:
        if "storage.googleapis.com" in parsed_url.netloc:
            gcs_uri = img_path.replace("https://storage.googleapis.com/", "gs://")
            print(f"      - Using direct GCS URI: {gcs_uri}")
            return types.Image(gcs_uri=gcs_uri)
        else:
            # Reverted to a simple, unauthenticated request for all non-GCS URLs.
            print(f"      - Fetching image from public URL: {img_path}")
            response = requests.get(img_path)
            response.raise_for_status()
            content_type = response.headers.get('Content-Type', '').lower()
            if "image" not in content_type:
                raise ValueError(f"URL did not point to a direct image. Content-Type was '{content_type}'. Please use a direct link to a JPG/PNG file.")
            return types.Image(image_bytes=response.content, mime_type=content_type)
    else:
        if not os.path.exists(img_path):
            raise FileNotFoundError(f"Reference image not found at: {img_path}")

        print(f"      - Resizing local image '{os.path.basename(img_path)}' to 1280x720...")
        
        # Create a temporary file path for the resized image.
        # This avoids modifying the original file and works with the existing upload function.
        temp_dir = tempfile.gettempdir()
        base, _ = os.path.splitext(os.path.basename(img_path))
        resized_filename = f"{base}_resized_720p.jpg"
        temp_resized_path = os.path.join(temp_dir, resized_filename)

        with Image.open(img_path) as img:
            # Resize to match the 720p output resolution
            img_resized = img.resize((1280, 720), Image.Resampling.LANCZOS)
            
            # Convert to RGB if it has an alpha channel (e.g. PNG) before saving as JPEG
            if img_resized.mode in ("RGBA", "P"):
                img_resized = img_resized.convert("RGB")
            
            img_resized.save(temp_resized_path, "JPEG", quality=95)

        try:
            # Upload the resized temporary file. The GCS object will be named '..._resized_720p.jpg'
            gcs_uri = upload_to_gcs_and_get_uri(temp_resized_path, gcs_bucket_name)
            
            # The API needs the mime type even with a GCS URI. Since we saved as JPEG, we know the type.
            return types.Image(gcs_uri=gcs_uri, mime_type="image/jpeg")
        finally:
            # Clean up the temporary file
            if os.path.exists(temp_resized_path):
                os.remove(temp_resized_path)

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
        # Parse bucket name from URI, removing 'gs://' and any subfolders
        gcs_bucket_name = GCS_BUCKET_URI.replace("gs://", "").split('/')[0]
        ref_images_config = []

        for img_path in reference_image_paths:
            try:
                image_for_api = _prepare_image_for_api(img_path, gcs_bucket_name)
                ref_images_config.append(types.VideoGenerationReferenceImage(image=image_for_api, reference_type="asset"))
            except Exception as e:
                # If any image fails to prepare, print a warning but continue generating without it.
                print(f"      - ⚠️  WARNING: Failed to prepare image '{img_path}': {e}. Generating without this image.")
                
        if ref_images_config:
            config.reference_images = ref_images_config

    print("\n" + "="*80)
    print("🚀 SENDING PROMPT TO VEO API (UNTRUNCATED):")
    print("-" * 80)
    print(prompt)
    print("=" * 80 + "\n")
    
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
        # Reverting to the simpler polling logic from the reference code to address the silent exit.
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
    import uuid
    local_filename = f"temp_download_{uuid.uuid4().hex}.mp4" 
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
        try:
            os.remove(local_filename)
        except OSError as e:
            print(f"      - Warning: Could not remove temp file {local_filename}: {e}")

    return final_bytes

def test_gemini_connection():
    """Tests the connection to the Gemini API and exits on failure."""
    print("Testing Gemini API connection...")
    try:
        client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
        response = client.models.generate_content(
            model=GEMINI_MODEL_NAME,
            contents="test",
            config={'max_output_tokens': 1}
        )
        if response:
            print("✅ Gemini API connection successful.")
    except Exception as e:
        print(f"❌ Gemini connection failure: {e}")
        sys.exit(1)

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

    test_gemini_connection()

    # Read the full storyboard context for the Gemini Predictive Model
    full_story_context = ""
    if os.path.exists(args.storyboard):
        try:
            full_story_context = "".join(_load_text_file_robustly(args.storyboard))
        except Exception as e:
            print(f"⚠️ Error reading full story context: {e}")
            
    full_cast_context = ""
    if os.path.exists(args.cast):
        try:
            full_cast_context = "".join(_load_text_file_robustly(args.cast))
        except Exception as e:
            print(f"⚠️ Error reading full cast context: {e}")

    # --- 2. Scene Discovery and Scoping ---
    # Ensure cast and storyboard paths are absolute for robustness in the loop
    args.cast = os.path.abspath(args.cast)
    args.storyboard = os.path.abspath(args.storyboard)
    print(f"    - Using absolute cast path: {args.cast}")
    print(f"    - Using absolute storyboard path: {args.storyboard}")

    # Load cast and scenes ONCE at the start. This prevents redundant file loading in the loop.
    all_scenes, characters = get_all_scenes(args.cast, args.storyboard, args.reference_image)

    # Determine which scenes to run
    # This block handles the different run modes: --list-scenes, --run-all, or --scene-number.
    scenes_to_run = []
    if args.list_scenes: # This path is for listing only, not for actual generation
        print(f"--- Scene List ({len(all_scenes)} total) ---")
        for scene in all_scenes:
            img_info = f" [Refs: {', '.join(scene['effective_images'])}]" if scene['effective_images'] else ""
            print(f"Scene {scene['id']}: {scene['prompt']}{img_info}")
        return
    elif args.run_all:
        scenes_to_run = all_scenes
    elif args.scene_number:
        # Find the specific scene
        found = next((s for s in all_scenes if s["id"] == args.scene_number), None)
        if found:
            scenes_to_run = [found]
        else:
            print(f"❌ Error: Scene number '{args.scene_number}' not found. Valid numbers are 1 to {len(all_scenes)}.")
            return
    else:
        print("❌ Error: You must specify --scene-number <N>, --run-all, or --list-scenes")
        return

    # Use the output directory from arguments and create it if it doesn't exist
    os.makedirs(args.output_dir, exist_ok=True)

    # --- 3. Main Generation Loop ---
    # We maintain a robust loop that iterates through scene IDs, but we dynamically reload the files 
    # and find the target scene_data inside the loop so live edits to story.md and cast.md take effect immediately.
    
    # Get the static list of scene IDs we need to process to control the loop.
    if args.list_scenes or not hasattr(args, 'scenes_to_run'):
        scenes_to_run = all_scenes
    
    scene_ids_to_run = [s["id"] for s in scenes_to_run]
    print(f"--- Processing {len(scene_ids_to_run)} scenes ---")
    
    # Initialize lists for tracking the outcome of the run for the final summary.
    successful_scenes = []
    skipped_scenes = []
    failed_file_not_found = []
    failed_safety_filter = []
    failed_other = []

    try:
        for scene_id in scene_ids_to_run:
            print(f"\n--- Processing Scene {scene_id} ---")
            
            # --- DYNAMIC RELOAD ---
            # Reload everything here so live edits are caught!
            live_all_scenes, live_characters = get_all_scenes(args.cast, args.storyboard, args.reference_image)
            
            # Find the specific scene_data for this ID from the newly loaded list
            scene_data_matches = [s for s in live_all_scenes if str(s["id"]) == str(scene_id)]
            
            if not scene_data_matches:
                print(f"⚠️ Scene {scene_id} was removed from the storyboard. Skipping.")
                continue
                
            scene_data = scene_data_matches[0]
            
            # Reload context strings for Gemini
            full_story_context = ""
            if os.path.exists(args.storyboard):
                full_story_context = "".join(_load_text_file_robustly(args.storyboard))
            
            # Use the live_characters dict to build a clean cast context for Gemini
            # This is more robust than reloading the file and ensures cleaned descriptions are used.
            cast_context = {k: v["description"] for k, v in live_characters.items()}

            # --- b. Robust File Existence Check ---
            # Checks for existing files using a pattern to avoid re-rendering if the AI name changes slightly.
            if not args.overwrite:
                scene_num_padded = str(int(scene_id) * 10).zfill(3)
                
                # Check for new AI-named files using a pattern
                ai_pattern = os.path.join(args.output_dir, f"FMP_{scene_num_padded}_*.mp4")
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

            ai_filename = generate_scene_filename(raw_line, int(scene_id), live_characters)
            
            if ai_filename:
                output_filename = os.path.join(args.output_dir, ai_filename)
            else:
                slug = create_prompt_slug(prompt)
                output_filename = os.path.join(args.output_dir, f"scene_{scene_id}_{slug}.mp4")
                print(f"    - Fallback slug filename: {os.path.basename(output_filename)}")
                
            print(f"\n🎬 Generating Scene {scene_id}...")
            print(f"    - Original Prompt: \"{prompt}\"")
            prompt = improve_prompt_with_gemini(prompt, full_story_context, cast_context)
            
            # Post-Gemini placeholder replacement:
            # Gemini might use the {CHARACTER_DESC} placeholders in its output because
            # it sees them in the story.md context. We must substitute them again.
            for char_key, char_info in live_characters.items():
                placeholder = f"{{{char_key}}}"
                if placeholder in prompt:
                    prompt = prompt.replace(placeholder, char_info["description"])

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
                    continue  # Continue to the next scene instead of exiting
            # Catch auth errors from googleusercontent.com URLs as well
            except (FileNotFoundError, requests.exceptions.RequestException, google.auth.exceptions.GoogleAuthError, IOError, ValueError) as e:
                print(f"\n⚠️  WARNING: Skipping Scene {scene_id} because a reference image could not be loaded.")
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
                print("    - Cooling down for 30 seconds (Press Ctrl+C to stop)...")
                try:
                    time.sleep(30)
                except KeyboardInterrupt:
                    print("\n\n⚠️  Sleep interrupted by user.")
                    break
    except KeyboardInterrupt:
        print("\n\n⚠️  Script interrupted by user (KeyboardInterrupt). Moving to summary...")
    
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
