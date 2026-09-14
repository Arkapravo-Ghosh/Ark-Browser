#!/usr/bin/env python3
"""One-shot MLX-VLM child used by Ark's process-level inference bridge."""

import argparse
from pathlib import Path


def completion_text(result: object) -> str:
    """Normalize the pinned MLX-VLM generation result to Ark's text contract."""
    if isinstance(result, str):
        return result
    text = getattr(result, "text", None)
    if not isinstance(text, str):
        raise TypeError("MLX-VLM returned a generation result without text")
    return text


def main() -> int:
    from mlx_vlm import generate, load
    from mlx_vlm.prompt_utils import apply_chat_template

    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--image")
    args = parser.parse_args()

    prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    model, processor = load(args.model)
    config = model.config
    images = [args.image] if args.image else None
    formatted = apply_chat_template(
        processor, config, prompt, num_images=len(images or [])
    )
    result = generate(
        model, processor, formatted, images, max_tokens=1024, verbose=False
    )
    print(completion_text(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
