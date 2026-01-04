
import json
from pathlib import Path

# Input/Output paths
INPUT_FILE = "docs/reference/UPDATED_TEMPLATE_PROMPTS.json"
OUTPUT_FILE = "docs/reference/UPDATED_TEMPLATE_AI_STUDIO.md"

def main():
    # Read the JSON file
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        prompts = json.load(f)

    markdown_content = "# AI Studio Prompts for Card Templates\n\n"
    markdown_content += "Use these prompts to generate the card templates. Each block contains the recommended parameters and the full prompt text.\n\n"

    for item in prompts:
        filename = item["filename"]
        prompt_text = item["prompt"]
        
        # Determine aspect ratio based on description (vertical portrait)
        # Standard TCG card is 2.5 x 3.5 inches, approx 5:7 or 2:3.
        # Converting to common AI model aspect ratios:
        # Midjourney: --ar 2:3
        # Stable Diffusion: 512x768 or 832x1216 (approx 2:3)
        # Nano Banana Pro assumed parameter style is just listed text.
        
        markdown_content += f"## {filename}\n\n"
        markdown_content += "**Parameters:**\n"
        markdown_content += "- **Aspect Ratio**: 2:3 (Vertical Portrait)\n"
        markdown_content += "- **Dimensions**: 832x1216 (or similar vertical high-res)\n"
        markdown_content += "- **Model**: Nano Banana Pro / Midjourney v6 / Flux.1 (Recommended)\n"
        markdown_content += "- **Guidance Scale**: 3.5 - 7\n\n"
        markdown_content += "```text\n"
        markdown_content += prompt_text
        markdown_content += "\n```\n\n"
        markdown_content += "---\n\n"

    # Write to Markdown file
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(markdown_content)

    print(f"Successfully formatted {len(prompts)} prompts to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
