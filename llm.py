"""
LLM integration - Ollama API calls for keyword extraction, image description, and query expansion.
All outputs are in English for consistent indexing.
"""
import httpx
import base64
import json
import re
import logging
import os
from typing import Optional

# Setup AI Logger
ai_log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai.log")
ai_logger = logging.getLogger("ai_engine")
ai_logger.setLevel(logging.INFO)
# Clear existing handlers
if ai_logger.handlers:
    ai_logger.handlers.clear()
handler = logging.FileHandler(ai_log_file, encoding='utf-8')
handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
ai_logger.addHandler(handler)

OLLAMA_BASE_URL = "http://127.0.0.1:11434"
TIMEOUT = 300.0  # seconds - local model can be slow

# Simple cache for the model name to avoid constant DB reads
_cached_model = None
_cache_time = 0
CACHE_TTL = 30 # seconds

def get_model_name() -> str:
    """Get the current selected model name from database with caching."""
    global _cached_model, _cache_time
    import time
    from database import get_setting

    now = time.time()
    if _cached_model is None or (now - _cache_time) > CACHE_TTL:
        _cached_model = get_setting("llm_model", "gemma3:4b")
        _cache_time = now
    return _cached_model


def _clear_llm_cache():
    """Clear the cached model name to force a refresh from the database."""
    global _cached_model
    _cached_model = None


async def _chat(prompt: str, image_path: Optional[str] = None) -> str:
    """Send a chat request to Ollama."""
    model = get_model_name().strip() # Ensure no newlines/spaces
    messages = [{"role": "user", "content": prompt}]

    # If image, encode as base64 and attach
    if image_path:
        with open(image_path, "rb") as f:
            img_data = base64.b64encode(f.read()).decode("utf-8")
        messages[0]["images"] = [img_data]

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.1,  # Lower temperature for even more consistent JSON outputs
            # Removed num_predict: 1024 as it causes empty responses in Qwen/Vision models
        }
    }

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            response = await client.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json=payload,
            )
            if response.status_code == 404:
                raise Exception(f"Model '{model}' not found in Ollama. Please download it or select another model.")
            response.raise_for_status()
            data = response.json()
            content = data["message"]["content"]
            ai_logger.info(f"Model '{model}' responded. Content length: {len(content)}")
            ai_logger.debug(f"Raw Output: {content}")
            return content
        except httpx.ConnectError:
            raise Exception("Cannot connect to Ollama. Is it running?")
        except Exception as e:
            raise e


def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences like ```json ... ``` that Qwen/other models add."""
    # Remove ```json ... ``` or ``` ... ``` blocks, keeping only the inner content
    text = re.sub(r'^```(?:json|JSON)?\s*', '', text.strip())
    text = re.sub(r'```\s*$', '', text.strip())
    # Also handle inline fences in the middle
    text = re.sub(r'```(?:json|JSON)?([\s\S]*?)```', r'\1', text)
    return text.strip()


def _parse_json_response(text: str) -> dict:
    """Try to extract JSON from LLM response with high resilience.
    Handles Qwen-style markdown fences, trailing commas, and other quirks.
    """
    if not text:
        return {"summary": "", "keywords": []}

    # Step 0: Strip markdown code fences (Qwen, Mistral etc. love adding these)
    text = _strip_markdown_fences(text).strip()

    data = None

    # Step 1: Try first { ... last } extraction
    first_brace = text.find('{')
    last_brace = text.rfind('}')

    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        json_str = text[first_brace:last_brace+1]
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            # Fix trailing commas, then retry
            json_str_fixed = re.sub(r',\s*([\]}])', r'\1', json_str)
            try:
                data = json.loads(json_str_fixed)
            except json.JSONDecodeError:
                pass

    if data and isinstance(data, dict):
        # Case-insensitive key lookup
        data_low = {k.lower(): v for k, v in data.items()}

        # Keywords extraction
        keywords = []
        for key in ["keywords", "tags", "keyword_list", "entities", "labels"]:
            if key in data_low:
                val = data_low[key]
                if isinstance(val, str):
                    keywords = [k.strip() for k in re.split(r'[;,\n]', val) if k.strip()]
                elif isinstance(val, list):
                    keywords = [str(k).strip() for k in val if k]
                break

        # Summary extraction
        summary = ""
        for key in ["summary", "description", "abstract", "content"]:
            if key in data_low:
                summary = str(data_low[key]).strip()
                break

        if summary and keywords:
            ai_logger.info(f"JSON parsed OK: {len(keywords)} keywords.")
            return {"summary": summary, "keywords": keywords}

        if keywords:  # have keywords but no summary
            summary = text[:500] + "..." if len(text) > 500 else text
            ai_logger.info(f"JSON partial: {len(keywords)} keywords, no summary.")
            return {"summary": summary, "keywords": keywords}

    # Step 2: Regex fallback — try to extract keywords array directly
    # Handles cases like:  "keywords": ["a", "b", "c"]
    kw_array_match = re.search(
        r'["\']?keywords["\']?\s*:\s*\[([^\]]+)\]', text, re.IGNORECASE | re.DOTALL
    )
    if kw_array_match:
        raw_items = kw_array_match.group(1)
        # Extract quoted strings or bare words
        keywords = re.findall(r'["\']([^"\']+)["\']|([^,\[\]\n"\'\.]+)', raw_items)
        keywords = [a or b for a, b in keywords]
        keywords = [k.strip() for k in keywords if k.strip()]
        if keywords:
            ai_logger.info(f"Regex array fallback: {len(keywords)} keywords.")
            return {"summary": "", "keywords": keywords}

    # Step 3: Line-by-line parsing for bullet-point style outputs
    keywords = []
    lines = text.split("\n")
    for line in lines:
        line = line.strip()
        if line.startswith(("- ", "* ", "• ")) and len(line) > 2:
            keywords.append(line[2:].strip())
        elif ":" in line and any(k in line.lower() for k in ["keywords", "tags", "labels"]):
            parts = line.split(":", 1)[1]
            keywords.extend([k.strip() for k in re.split(r'[;,\n]', parts) if k.strip()])

    clean_text = re.sub(r'```.*?```', '', text, flags=re.DOTALL).strip()
    result = {"summary": clean_text if clean_text else text.strip(), "keywords": list(set(keywords))}
    ai_logger.info(f"Fallback parse: {len(result['keywords'])} keywords found.")
    return result


async def extract_keywords(text: str, file_name: str) -> dict:
    """
    Extract keywords and summary from text content.
    Returns: {"summary": str, "keywords": [str]}
    """
    prompt = f"""Analyze this file and extract information for search indexing.
File name: {file_name}

CONTENT:
{text[:3000]}

INSTRUCTIONS:
- Respond ONLY with a valid JSON object. No markdown, no code fences, no explanation before or after.
- All content must be in English
- If the original content is not in English, translate the key concepts
- Summary should be a detailed 3-5 sentence paragraph comprehensively describing what this file is about
- Keywords should be comprehensive and EXHAUSTIVE: include ALL topics, names, places, technical terms, actions, concepts, and proper nouns
- Include 20-40 keywords
- CRITICAL: Multi-word terms MUST be kept as a single keyword (e.g. "binary search", "machine learning", "New York")
- CRITICAL: Extract ALL proper nouns as complete keywords (person names, place names, brand names, org names, tech names)
- Keep original proper nouns even if they are not in English (e.g. "東京", "台北101")

OUTPUT FORMAT (respond with ONLY this, no additional text):
{{"summary": "Detailed comprehensive description of the file content", "keywords": ["keyword1", "keyword2", "keyword3"]}}"""

    try:
        ai_logger.info(f"Extracting keywords for {file_name}...")
        response = await _chat(prompt)
        result = _parse_json_response(response)
        # Ensure required fields
        if "summary" not in result:
            result["summary"] = ""
        if "keywords" not in result:
            result["keywords"] = []
        return result
    except Exception as e:
        print(f"[LLM] Error extracting keywords for {file_name}: {e}")
        return {"summary": f"Error processing file: {file_name}", "keywords": []}


async def describe_image(image_path: str, file_name: str) -> dict:
    """
    Describe an image in extreme detail using vision model.
    Returns: {"summary": str, "keywords": [str]}
    """
    prompt = f"""Act as a high-fidelity image scanner and deep analysis system for search indexing.
File name: {file_name}

INSTRUCTIONS: Analyze this image with EXTREME precision. Extract and list EVERYTHING visible, especially background details that are often missed.

FIELDS TO ANALYZE:
1. BACKGROUND TEXT & OCR: 
   - Transcribe ALL visible text, even if small, blurred, or in the background.
   - Look for text on any surface in the image (ONLY IF ACTUALLY PRESENT).
   - If there are mathematical formulas, scientific equations, or code snippets, transcribe them exactly.
2. PEOPLE & ACTIONS: 
   - Describe specific physical actions ONLY IF PEOPLE ARE PRESENT.
   - Detail their posture, gestures, eye contact.
3. VISIBLE OBJECTS & ITEMS (CRITICAL - EXHAUSTIVE LIST):
   - List EVERY SINGLE concrete physical object you see in the image.
   - Categorize mentally: Food, Drink, Furniture, Decor, Electronics, Tools, Vehicles, Nature.
   - Mention specific models, types, materials, and colors when possible.
4. SCENE & ENVIRONMENT:
   - Detail the lighting (natural, neon, cinematic, dim) and shadows.
   - Describe the depth of field and focus.
5. PROPER NOUNS (CRITICAL - extract ALL of these as complete keywords):
   - PLACE NAMES: cities, countries, landmarks, buildings
   - BRAND NAMES: logos, product names, company names
   - PERSON NAMES: if identifiable from context (name tags, credits, watermarks)
   - ORGANIZATION NAMES: schools, companies, government agencies visible in the image
   - Keep proper nouns in their ORIGINAL language too (e.g., "東京タワー", "台北101")

CRITICAL:
- Respond ONLY with a JSON object. All content must be in English.
- Summary: A highly detailed 3-5 sentence paragraph capturing the core context, explicitly listing prominent objects, AND the most defining background details.
- Keywords: Include 40-70 keywords. MUST include all objects from step 3 and text from step 1.
- CRITICAL: ANTICIPATE HALLUCINATIONS. DO NOT invent items. ONLY list objects that are explicitly visible in the pixels of the image.
- CRITICAL: Multi-word terms MUST be kept as a single keyword:
  - "Eiffel Tower" NOT "Eiffel", "Tower"
  - "machine learning" NOT "machine", "learning"

FORMAT:
{{"summary": "...", "keywords": ["keyword1", "keyword2", ...]}}"""

    try:
        response = await _chat(prompt, image_path=image_path)
        result = _parse_json_response(response)
        if "summary" not in result:
            result["summary"] = ""
        if "keywords" not in result:
            result["keywords"] = []
        return result
    except Exception as e:
        print(f"[LLM] Error describing image {file_name}: {e}")
        return {"summary": f"Image file: {file_name}", "keywords": []}


async def expand_query(user_query: str) -> str:
    """
    Expand a natural language query into comprehensive English search keywords.
    Returns a space-separated string of keywords for Elasticsearch search.
    """
    prompt = f"""You are an expert search query expansion system. The user wants to find files on their computer based on a natural language query.

USER QUERY: {user_query}

INSTRUCTIONS:
1. Extract the core intent from the query.
2. Generate highly relevant English search keywords to match the files they are looking for.
3. Include synonyms, related technical terms, broad categories, and specific examples.
4. If the query is not in English, translate the core concepts into English keywords.
5. For visual concepts, include words describing the image contents (colors, objects, scenes).
6. Example: "沙灘照片" → beach sand ocean sea coast shore waves tropical photo sunny water vacation seaside nature

CRITICAL:
Respond with ONLY a single line of space-separated English keywords (15-30 keywords).
DO NOT include prefixes like "Here are the keywords:" or "Keywords:".
DO NOT include any explanation or punctuation. JUST THE WORDS."""

    try:
        response = await _chat(prompt)
        # Clean up the response
        if not response:
            return user_query
            
        # Remove quotes if present
        keywords = response.strip().strip('"').strip("'")
        
        # Remove any lines that look like explanations ("Here are the keywords: ...")
        lines = keywords.split("\n")
        # Take the last line that looks like keywords (often LLMs put explanation first)
        for line in reversed(lines):
            line = line.strip()
            if line and len(line.split()) > 1:
                keywords = line
                # Stop if we found a good candidate (not empty, more than 1 word)
                break
        
        # Remove common prefixes LLMs might add
        keywords = re.sub(r'^(keywords:|answer:|result:)\s*', '', keywords, flags=re.IGNORECASE)
                
        return keywords
    except Exception as e:
        print(f"[LLM] Error expanding query: {e}")
        return user_query


async def check_ollama_status() -> dict:
    """Check if Ollama is running and model is available."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Check if Ollama is running
            resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            resp.raise_for_status()
            models = resp.json().get("models", [])
            model_names = [m["name"].strip() for m in models]
            
            current_model = get_model_name().strip()
            # Loose match: check if the selected model name (before version) is in the available models
            model_base = current_model.split(":")[0]
            has_model = any(model_base in name or current_model in name for name in model_names)

            return {
                "ollama_running": True,
                "model_available": has_model,
                "available_models": model_names,
                "selected_model": current_model,
            }
    except Exception as e:
        return {
            "ollama_running": False,
            "model_available": False,
            "error": str(e),
            "selected_model": get_model_name(),
        }


async def expand_query_with_file(user_query: str, file_content: Optional[str] = None,
                                  image_path: Optional[str] = None) -> str:
    """
    Expand a search query using both text and an uploaded file.
    The LLM analyzes the file content/image + user query together to
    generate comprehensive search keywords.
    """
    context_parts = []

    if user_query:
        context_parts.append(f"USER TEXT QUERY: {user_query}")

    if file_content:
        context_parts.append(f"UPLOADED FILE CONTENT:\n{file_content[:3000]}")

    context = "\n\n".join(context_parts)

    prompt = f"""You are a multi-modal high-fidelity search query expansion system.
Context provided:
{context}

INSTRUCTIONS:
1. Perform a Deep Visual/Content Audit:
   - For images: Index ALL background elements, transcribing text on boards/screens and describing specific human actions (gestures, postures, tool usage).
   - For documents: Extract technical formulas, specific named entities, and deep topical metadata.
2. Generate space-separated English keywords (35-60 keywords) that represent:
   - Core visual components (foreground/background).
   - Transcribed text, math expressions, and branding.
   - Specific user intent combined with file context.
   - Professional/domain synonyms and related concepts.

CRITICAL:
Respond with ONLY a single line of space-separated English keywords.
DO NOT include any conversational text, prefixes, or punctuation. JUST THE WORDS."""

    try:
        response = await _chat(prompt, image_path=image_path)
        if not response:
            return user_query or ""

        # Clean up
        keywords = response.strip().strip('"').strip("'")
        lines = keywords.split("\n")
        for line in reversed(lines):
            line = line.strip()
            if line and len(line.split()) > 1:
                keywords = line
                break

        keywords = re.sub(r'^(keywords:|answer:|result:)\s*', '', keywords, flags=re.IGNORECASE)
        return keywords
    except Exception as e:
        print(f"[LLM] Error expanding query with file: {e}")
        return user_query or ""
