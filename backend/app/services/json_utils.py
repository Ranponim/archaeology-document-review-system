import re

MARKDOWN_JSON_PATTERN = re.compile(
    r"```(?:json)?\s*\n?(.*?)\n?\s*```",
    re.DOTALL | re.IGNORECASE,
)


def strip_markdown_json(text: str) -> str:
    """Extract JSON string from markdown code blocks if present.

    - Uses regex r'```(?:json)?\s*\n?(.*?)\n?\s*```' (with re.DOTALL) to extract
      content from markdown code blocks.
    - If no code block found, returns the original text stripped.
    - Handles multiple code blocks by taking the first one.
    """
    if not text:
        return ""
    text_stripped = text.strip()
    match = MARKDOWN_JSON_PATTERN.search(text_stripped)
    if match:
        return match.group(1).strip()
    return text_stripped
