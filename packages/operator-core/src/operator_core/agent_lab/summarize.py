"""Haiku-based text summarization for audit logs."""

import anthropic

from .prompts import HAIKU_SUMMARIZE_PROMPT


def summarize_with_haiku(client: anthropic.Anthropic, text: str) -> str:
    """Summarize text using Haiku for concise audit logs.

    Args:
        client: Anthropic client instance
        text: Text to summarize

    Returns:
        Summarized text, or original text (truncated to 500 chars) if summarization fails
    """
    if len(text) < 100:
        return text
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20250929",
            max_tokens=300,  # Increased from 150 for better summaries
            messages=[{"role": "user", "content": f"{HAIKU_SUMMARIZE_PROMPT}\n\n{text}"}],
        )
        return response.content[0].text  # type: ignore
    except Exception:
        # Better fallback - keep more context
        return text[:500] + "..." if len(text) > 500 else text
