import os
import asyncio
import random
import json
import re
from llm import _chat

# Theme: Advanced Robotics and Artificial Intelligence
THEME = "Advanced_Robotics_AI"

# Text categories
TEXT_CATEGORIES = [
    "Technical Specification",
    "Research Paper Abstract",
    "Meeting Minutes",
    "Project Proposal",
    "Bug Report",
    "User Manual Snippet",
    "Personal Journal entry of an AI researcher",
    "Ethics Board Review",
    "Neural Network Architecture Note",
    "Robotic Arm Maintenance Log"
]

# Code categories
CODE_CATEGORIES = [
    "PID Controller",
    "A* Pathfinding Algorithm",
    "Simple Neural Network implementation",
    "Sensor Data Parser",
    "Robot State Machine",
    "Computer Vision Preprocessing",
    "Inverse Kinematics solver snippet"
]

async def generate_file_list():
    """Ask LLM to generate a list of 12 files (mix of txt, py, cpp)."""
    prompt = f"""Generate a list of 12 file names and very brief descriptions for a project folder.
Theme: {THEME}
Requirements:
- Mix of .txt (randomly selected from categories: {', '.join(TEXT_CATEGORIES)})
- Mix of .py and .cpp (randomly selected from categories: {', '.join(CODE_CATEGORIES)})
- Filenames should be short and descriptive (snake_case or camelCase).
- Respond ONLY with a JSON list of objects: [{{"name": "...", "type": "txt|py|cpp", "category": "..."}}]
"""
    response = await _chat(prompt)
    # Clean JSON
    match = re.search(r'\[.*\]', response, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    return []

async def generate_file_content(file_info):
    """Generate content for a specific file."""
    name = file_info['name']
    file_type = file_info['type']
    category = file_info['category']
    
    if file_type == 'txt':
        prompt = f"""Generate a long, detailed piece of text for a file.
File Name: {name}
Category: {category}
Theme: {THEME}
Requirements:
- It should look like a real {category}.
- Length should be at least 3-5 paragraphs.
- Tone should be professional or appropriate for the category.
- Respond with ONLY the file content, no other text."""
    else:
        prompt = f"""Generate a functional, runnable {file_type} source code.
File Name: {name}
Category: {category}
Theme: {THEME}
Requirements:
- Implement a {category}相关的 logic.
- The code must be clean, commented, and valid.
- For .py, include a main block or usage example.
- For .cpp, include headers and a main function.
- Respond with ONLY the source code, no other text."""

    content = await _chat(prompt)
    # Strip markdown code blocks if LLM included them
    content = re.sub(r'^```[a-z]*\n', '', content, flags=re.MULTILINE)
    content = re.sub(r'\n```$', '', content, flags=re.MULTILINE)
    return content.strip()

async def main():
    if not os.path.exists(THEME):
        os.makedirs(THEME)
        print(f"Created directory: {THEME}")

    print("Generating file list...")
    file_list = await generate_file_list()
    if not file_list:
        print("Failed to generate file list.")
        return

    print(f"Plan to generate {len(file_list)} files.")
    
    for i, file_info in enumerate(file_list):
        name = file_info['name']
        print(f"[{i+1}/{len(file_list)}] Generating content for {name}...")
        try:
            content = await generate_file_content(file_info)
            filepath = os.path.join(THEME, name)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"  Successfully saved {name}")
        except Exception as e:
            print(f"  Error generating {name}: {e}")

if __name__ == "__main__":
    asyncio.run(main())
