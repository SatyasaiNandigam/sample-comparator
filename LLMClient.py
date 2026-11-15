from openai import OpenAI
from typing import Any
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file


def call_openai(
    messages: list[dict[str, Any]],
    response_format: str
) -> str:
    """
    Call an OpenAI chat completion model using a messages array.

    Args:
        messages: List of system, user, and assistant messages.
        model: OpenAI model to use.
        temperature: Controls response randomness.

    Returns:
        Generated response as a string.
    """
    client = OpenAI()

    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=messages,
        temperature=1.0,
        response_format=response_format
    )
    
    usage = response.usage

    print("Input tokens:", usage.prompt_tokens)
    print(
        "Cached tokens:",
        usage.prompt_tokens_details.cached_tokens
    )

    return response.choices[0].message.content or ""


# Example usage
if __name__ == "__main__":
    messages = [
        {
            "role": "system",
            "content": "You are a helpful AI assistant."
        },
        {
            "role": "user",
            "content": "Write it as a child would say the following content: Python is a programming language."
        }
    ]

    result = call_openai(messages)
    print(result)