"""Tests for text formatting utilities."""

import pytest

from utils.text import escape_markdown


@pytest.mark.unit
class TestText:
    """Test text formatting functions."""

    def test_escape_markdown_empty_string(self):
        """Test escaping empty string."""
        result = escape_markdown("")
        assert result == "", "Empty string should remain empty"

    def test_escape_markdown_normal_text(self):
        """Test that normal text without special chars is unchanged."""
        text = "Hello World"
        result = escape_markdown(text)
        assert result == text, "Normal text should not be modified"

    def test_escape_markdown_underscore(self):
        """Test escaping underscore."""
        result = escape_markdown("test_text")
        assert result == "test\\_text", "Underscore should be escaped"

    def test_escape_markdown_asterisk(self):
        """Test escaping asterisk."""
        result = escape_markdown("test*text")
        assert result == "test\\*text", "Asterisk should be escaped"

    def test_escape_markdown_brackets(self):
        """Test escaping brackets."""
        result = escape_markdown("test[text]")
        assert result == "test\\[text\\]", "Brackets should be escaped"

    def test_escape_markdown_parentheses(self):
        """Test escaping parentheses."""
        result = escape_markdown("test(text)")
        assert result == "test\\(text\\)", "Parentheses should be escaped"

    def test_escape_markdown_multiple_special_chars(self):
        """Test escaping multiple special characters."""
        result = escape_markdown("test_*[text](here)")
        assert result == "test\\_\\*\\[text\\]\\(here\\)", "All special chars should be escaped"

    @pytest.mark.parametrize("char", ["_", "*", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"])
    def test_escape_markdown_all_special_chars(self, char):
        """Test that all special characters are escaped."""
        result = escape_markdown(f"test{char}text")
        assert f"\\{char}" in result, f"Character {char} should be escaped"

    def test_escape_markdown_unicode(self):
        """Test that unicode characters are preserved."""
        text = "Тест українською мовою"
        result = escape_markdown(text)
        assert "Тест" in result, "Unicode characters should be preserved"

    def test_escape_markdown_mixed_content(self):
        """Test escaping mixed content with special and normal chars."""
        text = "User_name (admin) - [VIP]"
        result = escape_markdown(text)
        assert "User\\_name" in result
        assert "\\(admin\\)" in result
        assert "\\[VIP\\]" in result
