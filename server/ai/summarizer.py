from server.ai.openrouter import chat_completion_stream
from server.db.models import ChatMessage

SUMMARY_THRESHOLD = 0.70
SUMMARIZE_RATIO = 0.40

SUMMARY_SYSTEM_PROMPT = (
    "Summarize the following adventure log into a concise narrative paragraph. "
    "Preserve key events, decisions, character interactions, locations visited, "
    "and any unresolved plot points. Write in past tense, third person. "
    "Be thorough but concise — aim for density, not length."
)


def should_summarize(
    preamble_tokens: int,
    history_tokens: int,
    max_context: int,
    max_response: int,
) -> bool:
    total = preamble_tokens + history_tokens
    budget = max_context - max_response
    return budget > 0 and total / budget > SUMMARY_THRESHOLD


def pick_messages_to_summarize(
    messages: list[ChatMessage],
) -> tuple[list[ChatMessage], list[ChatMessage], int]:
    """Returns (to_summarize, to_keep, new_summary_up_to_turn)."""
    if len(messages) < 4:
        return [], messages, 0

    split = max(2, int(len(messages) * SUMMARIZE_RATIO))
    to_summarize = messages[:split]
    to_keep = messages[split:]
    new_boundary = to_summarize[-1].turn_number
    return to_summarize, to_keep, new_boundary


def format_messages_for_summary(messages: list[ChatMessage]) -> str:
    lines = []
    for m in messages:
        prefix = "Player" if m.role == "user" else "Narrator"
        lines.append(f"[{prefix}]: {m.content}")
    return "\n\n".join(lines)


async def generate_summary(
    api_key: str,
    model_id: str,
    messages_to_summarize: list[ChatMessage],
    existing_summary: str,
) -> str:
    user_content = ""
    if existing_summary:
        user_content += f"Previous summary:\n{existing_summary}\n\n---\n\nNew events to incorporate:\n"
    user_content += format_messages_for_summary(messages_to_summarize)

    prompt = [
        {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    result = ""
    async for chunk in chat_completion_stream(
        api_key=api_key,
        model_id=model_id,
        messages=prompt,
        temperature=0.3,
        max_tokens=500,
    ):
        result += chunk

    return result.strip()
