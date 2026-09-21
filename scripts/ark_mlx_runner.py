#!/usr/bin/env python3
"""One-shot MLX-VLM child used by Ark's process-level inference bridge."""

import argparse
from pathlib import Path
import re


def completion_text(result: object) -> str:
    """Normalize the pinned MLX-VLM generation result to Ark's text contract."""
    if isinstance(result, str):
        return result
    text = getattr(result, "text", None)
    if not isinstance(text, str):
        raise TypeError("MLX-VLM returned a generation result without text")
    return text


def parse_prompt_to_messages(raw: str, has_images: bool = False):
    """Split concatenated Ark prompt text into structured system and chat turns."""
    control_block = ""
    control_markers = ("\n\n# Available Tools", "\n\n# Capability decision")
    control_positions = [raw.find(marker) for marker in control_markers]
    control_positions = [position for position in control_positions if position != -1]
    if control_positions:
        control_idx = min(control_positions)
        control_block = raw[control_idx + 2:].strip()
        raw = raw[:control_idx]

    anti_hallucination = ""
    if not has_images:
        anti_hallucination = (
            "There are no images attached to this message. "
            "Do not describe, imagine, or hallucinate any image, photograph, or visual layout. "
            "Answer based ONLY on the text provided."
        )

    def combine_system(*parts):
        valid = [p.strip() for p in parts if p and p.strip()]
        return "\n\n".join(valid)

    parts = re.split(r'\n\n(?=(?:user|assistant): )', raw)
    messages = []

    if len(parts) <= 1:
        content = raw.strip()
        if content.startswith("user: "):
            content = content[6:].strip()
        sys_content = combine_system(control_block, anti_hallucination)
        if sys_content:
            messages.append({"role": "system", "content": sys_content})
        messages.append({"role": "user", "content": content})
        return messages

    first = parts[0].strip()
    if first.startswith("user: "):
        sys_content = combine_system(control_block, anti_hallucination)
        if sys_content:
            messages.append({"role": "system", "content": sys_content})
        messages.append({"role": "user", "content": first[6:].strip()})
    elif first.startswith("assistant: "):
        sys_content = combine_system(control_block, anti_hallucination)
        if sys_content:
            messages.append({"role": "system", "content": sys_content})
        messages.append({"role": "assistant", "content": first[11:].strip()})
    else:
        sys_content = combine_system(first, control_block, anti_hallucination)
        messages.append({"role": "system", "content": sys_content})

    for part in parts[1:]:
        p = part.strip()
        if p.startswith("user: "):
            messages.append({"role": "user", "content": p[6:].strip()})
        elif p.startswith("assistant: "):
            messages.append({"role": "assistant", "content": p[11:].strip()})
        else:
            messages.append({"role": "user", "content": p})

    if not any(m["role"] == "user" for m in messages):
        messages.append({"role": "user", "content": raw.strip()})

    return messages


def main() -> int:
    from mlx_vlm import generate, load
    from mlx_vlm.prompt_utils import apply_chat_template

    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--image", action="append", default=[])
    args = parser.parse_args()

    prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    model, processor = load(args.model)
    config = model.config
    model.no_chunked_prefill = True
    images = args.image or None

    prompt_data = parse_prompt_to_messages(prompt, has_images=bool(images))
    formatted = apply_chat_template(
        processor, config, prompt_data, num_images=len(images or [])
    )
    result = generate(
        model,
        processor,
        formatted,
        images,
        max_tokens=1024,
        verbose=False,
        prefill_step_size=None,
    )
    print(completion_text(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
