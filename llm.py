"""
LLM integration - Ollama API calls for keyword extraction, image description, and query expansion.
All outputs are in English for consistent indexing.
"""
import httpx
import base64
import json
import re
from typing import Optional

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
            "temperature": 0.3,  # Low temperature for consistent outputs
            "num_predict": 1024,
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
            print(f"[LLM DEBUG] Raw Output: {content}")
            return content
        except httpx.ConnectError:
            raise Exception("Cannot connect to Ollama. Is it running?")
        except Exception as e:
            raise e


def _parse_json_response(text: str) -> dict:
    """Try to extract JSON from LLM response."""
    # Try to find JSON block in markdown code fence
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if json_match:
        text_to_parse = json_match.group(1)
    else:
        # Try to find JSON object directly
        obj_match = re.search(r'\{.*\}', text, re.DOTALL)
        text_to_parse = obj_match.group(0) if obj_match else None

    if text_to_parse:
        try:
            data = json.loads(text_to_parse)
            # Create a case-insensitive copy for key lookup
            data_low = {k.lower(): v for k, v in data.items()}
            
            # Find keywords (handle keywords, tags, keyword_list, etc.)
            raw_keywords = None
            for key in ["keywords", "tags", "keyword_list", "entities"]:
                if key in data_low:
                    raw_keywords = data_low[key]
                    break
            
            if isinstance(raw_keywords, str):
                keywords = [k.strip() for k in re.split(r'[;,\n]', raw_keywords) if k.strip()]
            elif isinstance(raw_keywords, list):
                keywords = [str(k).strip() for k in raw_keywords if k]
            else:
                keywords = []
                
            # Find summary
            summary = ""
            for key in ["summary", "description", "abstract"]:
                if key in data_low:
                    summary = str(data_low[key])
                    break
            
            if not summary and not keywords:
                return {"summary": text.strip(), "keywords": []}
                
            return {"summary": summary, "keywords": keywords}
        except json.JSONDecodeError:
            pass

    # Fallback: return the whole text as summary, and try to find anything that looks like a list
    keywords = []
    lines = text.split("\n")
    for line in lines:
        line = line.strip()
        # Look for bullet points
        if line.startswith(("- ", "* ", "• ")):
            keywords.append(line[2:].strip())
        # Look for "Keywords: A, B, C"
        elif ":" in line and any(k in line.lower() for k in ["keywords", "tags"]):
            parts = line.split(":", 1)[1]
            keywords.extend([k.strip() for k in re.split(r'[;,\n]', parts) if k.strip()])
    
    return {"summary": text.strip(), "keywords": list(set(keywords))}


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
- Respond ONLY with a JSON object, no other text
- All content must be in English
- If the original content is not in English, translate the key concepts
- Summary should be 1-3 sentences describing what this file is about
- Keywords should be comprehensive and EXHAUSTIVE: include ALL topics, names, places, technical terms, actions, concepts, and proper nouns
- Include 20-40 keywords
- CRITICAL: Multi-word terms MUST be kept as a single keyword. Examples:
  - "binary search" NOT "binary", "search"
  - "machine learning" NOT "machine", "learning"
  - "dynamic programming" NOT "dynamic", "programming"
  - "New York" NOT "New", "York"
  - "Google Cloud Platform" NOT "Google", "Cloud", "Platform"
- CRITICAL: Extract ALL proper nouns as complete keywords:
  - Person names (e.g. "Albert Einstein", "Elon Musk")
  - Place names (e.g. "San Francisco", "Mount Fuji")
  - Brand/product names (e.g. "Visual Studio Code", "TensorFlow")
  - Organization names (e.g. "World Health Organization", "MIT")
  - Technology names (e.g. "React Native", "Node.js")
- Keep original proper nouns even if they are not in English (e.g. "東京", "台北101")

FORMAT:
{{"summary": "Brief description of the file content", "keywords": ["keyword1", "keyword2", "keyword3"]}}"""

    try:
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
- Summary: 2-4 sentences capturing the core context AND the most defining background detail.
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
