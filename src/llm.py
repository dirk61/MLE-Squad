"""LLM client wrapper with model selection, prompt caching, and adaptive thinking.

Render order is tools -> system -> messages. We mark the system block with
cache_control, which caches both tools and system as a single static prefix
(Anthropic's prefix-match rule means the system breakpoint covers everything
rendered before it). We also mark the last message block, so conversation
history caches incrementally as the ReAct loop grows. Two breakpoints, well
under the 4-per-request limit.

Adaptive thinking + effort are enabled on the opus and sonnet tiers; Haiku
4.5 supports neither and is called plain.

See spec_LLM.md for tier definitions; D16 in decisions.md for the rationale
behind the caching layout, model bump to Opus 4.7, and effort levels.
"""

import anthropic

# Tier name -> Anthropic model ID
MODEL_MAP: dict[str, str] = {
    "opus": "claude-opus-4-7",
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5-20251001",
}

# Default max_tokens per tier. Opus gets extra headroom for adaptive
# thinking; capped at 20K to stay under the SDK's non-streaming guard
# (raises ValueError above ~21,333 tokens, derived from a 10-minute
# wall-clock estimate).
MAX_TOKENS: dict[str, int] = {
    "opus": 20000,
    "sonnet": 16384,
    "haiku": 8192,
}


def _get_client() -> anthropic.Anthropic:
    """Create an Anthropic client using ANTHROPIC_API_KEY from environment."""
    return anthropic.Anthropic()


def _annotate_last_message(messages: list[dict]) -> list[dict]:
    """Return a copy of messages with cache_control on the last content block.

    Caches the growing conversation prefix turn-over-turn — each new ReAct
    iteration reuses everything before its own final block. We don't mutate
    the caller's list, so prior calls' annotations don't accumulate across
    iterations (only the current call's last block carries a marker).
    """
    if not messages:
        return messages
    out = list(messages)
    last = dict(out[-1])
    content = last["content"]
    if isinstance(content, str):
        last["content"] = [{
            "type": "text",
            "text": content,
            "cache_control": {"type": "ephemeral"},
        }]
    else:
        new_content = list(content)
        new_content[-1] = {**new_content[-1], "cache_control": {"type": "ephemeral"}}
        last["content"] = new_content
    out[-1] = last
    return out


def call_llm(
    *,
    tier: str,
    system: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    max_tokens: int | None = None,
) -> anthropic.types.Message:
    """Call the Anthropic API with caching and tier-appropriate thinking config.

    Args:
        tier: Model tier key ("opus", "sonnet", or "haiku").
        system: System prompt string.
        messages: Conversation messages in Anthropic API format.
        tools: Optional tool definitions for tool-use.
        max_tokens: Override default max tokens for this tier.

    Returns:
        The raw Anthropic Message response.
    """
    if tier not in MODEL_MAP:
        raise ValueError(f"Unknown model tier '{tier}'. Expected one of: {list(MODEL_MAP.keys())}")

    model_id = MODEL_MAP[tier]
    tokens = max_tokens or MAX_TOKENS[tier]
    client = _get_client()

    kwargs: dict = {
        "model": model_id,
        "max_tokens": tokens,
        "system": [{
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }],
        "messages": _annotate_last_message(messages),
    }
    if tools:
        kwargs["tools"] = tools

    if tier == "opus":
        # display="summarized" restores visible thinking text in responses;
        # Opus 4.7 defaults to omitted, which would leave the trace blind.
        kwargs["thinking"] = {"type": "adaptive", "display": "summarized"}
        kwargs["output_config"] = {"effort": "high"}
    elif tier == "sonnet":
        kwargs["thinking"] = {"type": "adaptive"}
        kwargs["output_config"] = {"effort": "medium"}
    # haiku 4.5: supports neither thinking nor effort — call plain.

    return client.messages.create(**kwargs)
