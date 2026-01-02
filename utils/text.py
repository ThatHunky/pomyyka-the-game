"""Text formatting utilities."""


def escape_markdown(text: str) -> str:
    """
    Escape special Markdown V2 characters to prevent parsing errors.

    Args:
        text: Text to escape (user-provided content like names, descriptions).

    Returns:
        Escaped text safe for Markdown parsing.
    """
    if not text:
        return ""

    # Characters that need escaping in Markdown V2
    # Note: We escape these to prevent breaking Markdown formatting
    special_chars = ["_", "*", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"]

    # Escape each special character
    for char in special_chars:
        text = text.replace(char, f"\\{char}")

    return text
