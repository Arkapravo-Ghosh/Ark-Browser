#!/usr/bin/env python3
"""One-shot MLX child used by Ark's process-level inference bridge.

Vision-language repositories run through MLX-VLM. Text-only MLX repositories
(Llama, Qwen, Mistral, Phi, Gemma text, ...) have no vision tower and are not
MLX-VLM architectures, so they run through the bundled MLX-LM instead.
"""

import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys

MAX_TOKENS = 1024
# Single-line stdout prefix that Ark's C++ bridge surfaces as the chat error
# for a failed request. Successful stdout remains completion text only.
ERROR_PREFIX = "ARK_RUNNER_ERROR: "


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


def coerce_int(value):
    """Return a Python int for an int-like value (int, numpy int, 0-d array)."""
    if isinstance(value, int):
        return value
    return int(value.item() if hasattr(value, "item") else value)


def coerce_tile_reps(reps):
    """Return tile() repetition counts as plain ints.

    mlx >= 0.32 type-checks ``mx.tile(a, reps)`` strictly (``int | Sequence[int]``),
    while several MLX-VLM 0.5.0 model files (Qwen2-VL, Qwen2.5-VL, Qwen3-VL, GLM-4V,
    ...) pass 0-d ``mx.array`` values taken from the image grid. Coercing each
    element with ``int()`` is exactly what those call sites intend.
    """
    if isinstance(reps, (tuple, list)):
        return tuple(coerce_int(r) for r in reps)
    return coerce_int(reps)


def install_mlx_compat_shims() -> None:
    """Wrap mx.tile/mx.repeat so MLX-VLM 0.5.0 model code runs on mlx 0.32.

    Both functions take repetition counts that the bundled mlx type-checks as
    plain ints; the model files hand them 0-d arrays from the image grid.
    """
    import mlx.core as mx

    if getattr(mx.tile, "_ark_shim", False):
        return
    original_tile = mx.tile
    original_repeat = mx.repeat

    def tile(a, reps, *args, **kwargs):
        return original_tile(a, coerce_tile_reps(reps), *args, **kwargs)

    def repeat(array, repeats, *args, **kwargs):
        return original_repeat(array, coerce_int(repeats), *args, **kwargs)

    tile._ark_shim = True
    repeat._ark_shim = True
    mx.tile = tile
    mx.repeat = repeat


def mlx_vlm_supports(model_type: str) -> bool:
    """Whether the bundled MLX-VLM ships an architecture for model_type."""
    try:
        from mlx_vlm.utils import MODEL_REMAPPING
    except ImportError:
        MODEL_REMAPPING = {}
    model_type = MODEL_REMAPPING.get(model_type, model_type)
    try:
        return importlib.util.find_spec(f"mlx_vlm.models.{model_type}") is not None
    except (ImportError, ValueError):
        return False


def mlx_lm_supports(model_type: str) -> bool:
    """Whether the bundled MLX-LM ships an architecture for model_type."""
    try:
        return importlib.util.find_spec(f"mlx_lm.models.{model_type}") is not None
    except (ImportError, ValueError):
        return False


def select_backend(config: dict) -> str:
    """Return "vlm" for vision-language checkpoints and "lm" otherwise.

    A vision tower plus a supported MLX-VLM architecture wins; otherwise any
    architecture MLX-LM knows runs as text. An MLX-VLM-only architecture whose
    config lays its vision block out unusually still goes to MLX-VLM. Anything
    else falls to MLX-LM, which reports the unsupported architecture.
    """
    model_type = str(config.get("model_type", "")).lower()
    vlm = mlx_vlm_supports(model_type)
    if config.get("vision_config") is not None and vlm:
        return "vlm"
    if mlx_lm_supports(model_type):
        return "lm"
    return "vlm" if vlm else "lm"


def merge_system_into_user(messages):
    """Fold system turns into the first user turn for templates without one."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    rest = [dict(m) for m in messages if m["role"] != "system"]
    if system:
        for message in rest:
            if message["role"] == "user":
                message["content"] = f"{system}\n\n{message['content']}"
                break
    return rest


def run_vlm(model_path: str, prompt: str, images) -> str:
    install_mlx_compat_shims()
    from mlx_vlm import generate, load
    from mlx_vlm.prompt_utils import apply_chat_template

    model, processor = load(model_path)
    config = model.config
    model.no_chunked_prefill = True
    images = images or None

    prompt_data = parse_prompt_to_messages(prompt, has_images=bool(images))
    formatted = apply_chat_template(
        processor, config, prompt_data, num_images=len(images or [])
    )
    result = generate(
        model,
        processor,
        formatted,
        images,
        max_tokens=MAX_TOKENS,
        verbose=False,
        prefill_step_size=None,
    )
    return completion_text(result)


def run_lm(model_path: str, prompt: str) -> str:
    from mlx_lm import generate, load

    model, tokenizer = load(model_path)
    messages = parse_prompt_to_messages(prompt, has_images=False)
    if getattr(tokenizer, "chat_template", None):
        try:
            formatted = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
        except Exception:
            # Some templates (for example older Gemma and Mistral) reject a
            # system role; keep its instructions in the first user turn.
            formatted = tokenizer.apply_chat_template(
                merge_system_into_user(messages),
                tokenize=False,
                add_generation_prompt=True,
            )
    else:
        formatted = "\n\n".join(
            f"{m['role']}: {m['content']}" for m in messages
        ) + "\n\nassistant: "
    return completion_text(
        generate(model, tokenizer, formatted, max_tokens=MAX_TOKENS, verbose=False)
    )


def fail(message: str) -> int:
    print(ERROR_PREFIX + " ".join(message.split()), flush=True)
    return 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--image", action="append", default=[])
    args = parser.parse_args()

    prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    try:
        config = json.loads(
            (Path(args.model) / "config.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return fail("This MLX installation has no readable config.json.")

    backend = select_backend(config)
    if args.image and backend != "vlm":
        return fail(
            "The selected MLX model is text-only and cannot read images. "
            "Choose a vision-capable model or remove the images."
        )
    try:
        if backend == "vlm":
            text = run_vlm(args.model, prompt, args.image)
        else:
            text = run_lm(args.model, prompt)
    except Exception as error:  # Reported to Ark; the child exits cleanly.
        print(f"{type(error).__name__}: {error}", file=sys.stderr, flush=True)
        model_type = config.get("model_type", "unknown")
        detail = f"{type(error).__name__}: {error}"
        if "torchvision" in str(error):
            # transformers 5 ships some vision families' image processors only
            # as torchvision-backed classes; Ark's MLX bundle has no PyTorch.
            detail = (
                "its image processor needs torchvision, which Ark's bundled "
                "MLX runtime does not include. Choose a vision model whose "
                "processor is PIL-based (for example Llama 3.2 Vision)."
            )
        return fail(
            f"The bundled MLX runtime could not run this model "
            f"(architecture '{model_type}'): {detail}"
        )
    print(text, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
