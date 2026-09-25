# Copyright 2026 Arkapravo Ghosh

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ark_mlx_runner.py"
SPEC = importlib.util.spec_from_file_location("ark_mlx_runner", SCRIPT)
assert SPEC and SPEC.loader
ark_mlx_runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ark_mlx_runner)


class ArkMlxRunnerTest(unittest.TestCase):
    def test_extracts_text_from_mlx_vlm_generation_result(self) -> None:
        result = SimpleNamespace(
            text="A direct completion",
            prompt_tokens=12,
            generation_tokens=3,
        )

        self.assertEqual(
            ark_mlx_runner.completion_text(result), "A direct completion"
        )

    def test_accepts_legacy_plain_string_result(self) -> None:
        self.assertEqual(
            ark_mlx_runner.completion_text("Legacy completion"),
            "Legacy completion",
        )

    def test_rejects_result_without_text(self) -> None:
        with self.assertRaisesRegex(TypeError, "without text"):
            ark_mlx_runner.completion_text(SimpleNamespace(tokens=[1, 2, 3]))

    def test_moves_capability_control_block_to_system_message(self) -> None:
        messages = ark_mlx_runner.parse_prompt_to_messages(
            "What is the weather?\n\n# Capability decision\n"
            "Return only a routing decision."
        )

        self.assertEqual(messages[-1], {
            "role": "user",
            "content": "What is the weather?",
        })
        self.assertIn("Capability decision", messages[0]["content"])

    def test_image_prompt_omits_no_image_guard(self) -> None:
        messages = ark_mlx_runner.parse_prompt_to_messages(
            "Describe the attached image.", has_images=True
        )

        self.assertEqual(messages, [{
            "role": "user",
            "content": "Describe the attached image.",
        }])

    def _with_support(self, vlm, lm):
        """Patch the architecture probes; returns a restore callable."""
        saved = (ark_mlx_runner.mlx_vlm_supports, ark_mlx_runner.mlx_lm_supports)
        ark_mlx_runner.mlx_vlm_supports = lambda model_type: model_type in vlm
        ark_mlx_runner.mlx_lm_supports = lambda model_type: model_type in lm

        def restore():
            ark_mlx_runner.mlx_vlm_supports, ark_mlx_runner.mlx_lm_supports = saved
        return restore

    def test_text_only_config_uses_mlx_lm(self) -> None:
        restore = self._with_support(vlm={"mllama"}, lm={"llama", "qwen3"})
        try:
            self.assertEqual(
                ark_mlx_runner.select_backend({"model_type": "llama"}), "lm")
            self.assertEqual(
                ark_mlx_runner.select_backend({"model_type": "qwen3"}), "lm")
        finally:
            restore()

    def test_vision_config_uses_mlx_vlm_when_supported(self) -> None:
        restore = self._with_support(vlm={"mllama"}, lm=set())
        try:
            self.assertEqual(ark_mlx_runner.select_backend(
                {"model_type": "mllama", "vision_config": {}}), "vlm")
        finally:
            restore()

    def test_vision_config_without_vlm_architecture_uses_mlx_lm(self) -> None:
        restore = self._with_support(vlm=set(), lm={"future"})
        try:
            self.assertEqual(ark_mlx_runner.select_backend(
                {"model_type": "future", "vision_config": {}}), "lm")
        finally:
            restore()

    def test_vlm_only_architecture_without_vision_config_uses_mlx_vlm(self) -> None:
        restore = self._with_support(vlm={"odd_vlm"}, lm=set())
        try:
            self.assertEqual(ark_mlx_runner.select_backend(
                {"model_type": "odd_vlm"}), "vlm")
        finally:
            restore()

    def test_unknown_architecture_falls_to_mlx_lm(self) -> None:
        restore = self._with_support(vlm=set(), lm=set())
        try:
            self.assertEqual(ark_mlx_runner.select_backend(
                {"model_type": "nothing"}), "lm")
        finally:
            restore()

    def test_tile_reps_coerced_to_ints(self) -> None:
        class Scalar:  # stands in for a 0-d mlx array
            def item(self):
                return 3

        self.assertEqual(ark_mlx_runner.coerce_tile_reps((Scalar(), 1)), (3, 1))
        self.assertEqual(ark_mlx_runner.coerce_tile_reps([2, 2]), (2, 2))
        self.assertEqual(ark_mlx_runner.coerce_tile_reps(4), 4)
        self.assertEqual(ark_mlx_runner.coerce_int(Scalar()), 3)
        self.assertEqual(ark_mlx_runner.coerce_int(7), 7)

    def test_system_turn_folds_into_first_user_turn(self) -> None:
        self.assertEqual(ark_mlx_runner.merge_system_into_user([
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ]), [
            {"role": "user", "content": "Be brief.\n\nHi"},
            {"role": "assistant", "content": "Hello"},
        ])


if __name__ == "__main__":
    unittest.main()
