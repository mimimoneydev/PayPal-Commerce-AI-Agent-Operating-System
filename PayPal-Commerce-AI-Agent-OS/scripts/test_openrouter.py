# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

"""Check OpenRouter's Anthropic-compatible tool protocol with the configured free model.

python3 scripts/test_openrouter.py
python3 scripts/test_openrouter.py --model vendor/model:free
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "commerce-common"))

from commerce_common.model_provider import (  # noqa: E402
    OPENROUTER_FREE_MODEL,
    build_model_client,
)


async def check(model: str) -> int:
    client = build_model_client(60)
    try:
        response = await client.messages.create(
            model=model,
            max_tokens=128,
            tools=[
                {
                    "name": "provider_check",
                    "description": "Return the exact connectivity check value.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                        "additionalProperties": False,
                    },
                }
            ],
            tool_choice={"type": "tool", "name": "provider_check"},
            messages=[
                {
                    "role": "user",
                    "content": "Call provider_check with value OPENROUTER_OK.",
                }
            ],
        )
    finally:
        await client.close()
    calls = [block for block in response.content if block.type == "tool_use"]
    if not calls or calls[0].name != "provider_check":
        print("OpenRouter replied, but the selected model did not produce the required tool call.")
        return 1
    if calls[0].input.get("value") != "OPENROUTER_OK":
        print("OpenRouter tool calling worked, but the tool arguments failed validation.")
        return 1
    print(f"OpenRouter connectivity and tool calling passed with {model}.")
    print(
        f"usage: input={response.usage.input_tokens}, output={response.usage.output_tokens} tokens"
    )
    return 0


def main() -> int:
    load_dotenv(REPO_ROOT / ".env", override=False)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENROUTER_MODEL", OPENROUTER_FREE_MODEL),
        help="OpenRouter model id; defaults to OPENROUTER_MODEL or DeepSeek V4.1 Flash",
    )
    args = parser.parse_args()
    if not os.environ.get("OPENROUTER_API_KEY", "").strip():
        print("OPENROUTER_API_KEY is not set; add it to .env before the live check.")
        return 2
    return asyncio.run(check(args.model))


if __name__ == "__main__":
    raise SystemExit(main())
