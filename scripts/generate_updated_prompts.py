
import json
import re
from pathlib import Path

# Input/Output paths
INPUT_FILE = "docs/reference/PROMPTS_FOR_AI_STUDIO.md"
OUTPUT_FILE = "docs/reference/UPDATED_TEMPLATE_PROMPTS.json"

def main():
    # Read the markdown file
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    # Extract JSON block
    match = re.search(r"```json\n(.*?)```", content, re.DOTALL)
    if not match:
        print("Error: Could not find JSON block in input file.")
        return

    json_str = match.group(1)
    prompts = json.loads(json_str)

    updated_prompts = []

    for item in prompts:
        old_prompt = item["prompt"]
        
        # Define the regex to find the old stats section
        # We look for the section starting from ATK and ending at DEF
        # The structure is specific:
        # BOTTOM LEFT: "⚔️ ATK: 50"
        # BOTTOM CENTER: "🎭 MEME: 50"
        # BOTTOM RIGHT: "🛡️ DEF: 50"
        
        stats_pattern = r'BOTTOM LEFT: "⚔️ ATK: 50"\nBOTTOM CENTER: "🎭 MEME: 50"\nBOTTOM RIGHT: "🛡️ DEF: 50"'
        
        new_stats_section = (
            'STATS ROW (below lore, above footer): '
            'Arrange these 5 stats in a clear horizontal line or grid: '
            '"⚔️ ATK: 50", "⚡ INIT: +5", "🛡️ AC: 15", "🛡️ DEF: 50", "🎭 MEME: 50"'
        )
        
        if re.search(stats_pattern, old_prompt):
            new_prompt = re.sub(stats_pattern, new_stats_section, old_prompt)
            updated_prompts.append({
                "filename": item["filename"], # Keep original filename (user can overwrite)
                "prompt": new_prompt
            })
        else:
            print(f"Warning: Stats pattern not found in {item['filename']}")
            updated_prompts.append(item)

    # Write dictionary to JSON file
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(updated_prompts, f, indent=2, ensure_ascii=False)

    print(f"Successfully wrote {len(updated_prompts)} updated prompts to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
