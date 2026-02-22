"""
LLM integration - Ollama API calls for keyword extraction, image description, and query expansion.
All outputs are in English for consistent indexing.
"""
import httpx
import base64
import json
import re
from typing import Optional

OLLAMA_BASE_URL = "http://localhost:11434"
MODEL_NAME = "gemma3:4b"
TIMEOUT = 120.0  # seconds - local model can be slow


async def _chat(prompt: str, image_path: Optional[str] = None) -> str:
    """Send a chat request to Ollama."""
    messages = [{"role": "user", "content": prompt}]

    # If image, encode as base64 and attach
    if image_path:
        with open(image_path, "rb") as f:
            img_data = base64.b64encode(f.read()).decode("utf-8")
        messages[0]["images"] = [img_data]

    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.3,  # Low temperature for consistent outputs
            "num_predict": 1024,
        }
    }

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        return data["message"]["content"]


def _parse_json_response(text: str) -> dict:
    """Try to extract JSON from LLM response."""
    # Try to find JSON block in markdown code fence
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if json_match:
        text = json_match.group(1)

    # Try to find JSON object directly
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    # Fallback: return the whole text as summary
    return {"summary": text.strip(), "keywords": []}


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
- Keywords should be comprehensive: include topics, names, places, technical terms, actions, and concepts
- Include 15-30 keywords

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
    prompt = f"""Describe this image in EXTREME DETAIL for search indexing purposes.
File name: {file_name}

You must describe EVERYTHING you can see:
- Objects and items (what they are, their colors, materials, sizes)
- People (appearance, actions, emotions, clothing, number of people)
- Scene and setting (indoor/outdoor, location type, time of day, weather)
- Text visible in the image (signs, labels, watermarks)
- Colors, lighting, and visual style
- Background elements
- Any symbols, logos, or icons
- The overall mood and atmosphere
- Type of image (photo, screenshot, diagram, chart, illustration, meme, etc.)

Be as detailed and descriptive as possible. Every detail matters for searchability.
Include related concepts and synonyms. For example, if there is a beach, also mention: ocean, sea, coast, shore, sand, waves, tropical.

IMPORTANT: Respond ONLY with a JSON object. All content must be in English.

FORMAT:
{{"summary": "Detailed 2-4 sentence description of the image", "keywords": ["keyword1", "keyword2", ...]}}

Include 20-40 keywords covering all aspects of the image."""

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
            model_names = [m["name"] for m in models]

            has_model = any(MODEL_NAME.split(":")[0] in name for name in model_names)

            return {
                "ollama_running": True,
                "model_available": has_model,
                "available_models": model_names,
                "required_model": MODEL_NAME,
            }
    except Exception as e:
        return {
            "ollama_running": False,
            "model_available": False,
            "error": str(e),
            "required_model": MODEL_NAME,
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

    prompt = f"""You are an expert search query expansion system. The user wants to find SIMILAR files on their computer.
They have provided the following context:

{context}

INSTRUCTIONS:
1. Analyze BOTH the user's text description AND the uploaded file content/image.
2. Generate highly relevant English search keywords that would match SIMILAR files.
3. Include synonyms, related concepts, broader categories, and domain-specific terms.
4. For images: extract visual elements, objects, colors, themes, styles, and text within the image.
5. For documents: extract key topics, main subjects, technical jargon, and named entities.
6. Think about what metadata or content would exist in files similar to what the user is looking for.

CRITICAL:
Respond with ONLY a single line of space-separated English keywords (25-45 keywords).
DO NOT include prefixes like "Here are the keywords:" or "Keywords:".
DO NOT include any explanation or punctuation. JUST THE WORDS."""

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
