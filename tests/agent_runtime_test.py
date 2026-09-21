#!/usr/bin/env python3
# Copyright 2026 Arkapravo Ghosh
"""Smoke test Ark's agent orchestration against installed local runtimes."""

import argparse
import asyncio
import base64
import json
from pathlib import Path

from agent_test import browser, default_binary


ROOT = Path(__file__).resolve().parents[1]
async def prompt(cdp, page, model_id, message, images=None):
    encoded_images = json.dumps(images or [])
    return await cdp.evaluate(page, f"""(async () => {{
        const module = await import('./ark.mojom-webui.js');
        const handler = module.PageHandler.getRemote();
        const created = await handler.createConversation({model_id!r});
        try {{
            const result = await handler.sendAgentPrompt({{
                conversationId: created.state.id,
                message: {message!r},
                images: {encoded_images},
                providerCredential: null,
                steeringInstruction: null,
            }});
            return {{
                success: result.response.success,
                text: result.response.response,
                steps: result.response.steps.map(step => ({{
                    type: step.stepType,
                    title: step.title,
                    detail: step.detail,
                    serverName: step.serverName,
                    toolName: step.toolName,
                }})),
            }};
        }} finally {{
            await handler.deleteConversation(created.state.id);
        }}
    }})()""")


async def run(args):
    artifacts = args.artifacts.resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    async with browser(args.binary.resolve(), artifacts) as cdp:
        page = await cdp.first_page()
        await cdp.navigate(page, 'ark://ark-chat/#chat')

        installed = await cdp.evaluate(page, """(async () => {
            const module = await import('./ark.mojom-webui.js');
            const handler = module.PageHandler.getRemote();
            const result = await handler.getInstalledLocalModels();
            return result.models.map(model => ({
                id: model.modelId,
                runtime: model.runtimeBackend,
                supportsVision: model.supportsVision,
            }));
        })()""")
        models = {}
        for runtime in {'mlx-vlm', 'llama.cpp'}:
            candidates = [
                model['id'] for model in installed
                if model['runtime'] == runtime
            ]
            if runtime == 'mlx-vlm':
                preferred = next(
                    (model_id for model_id in candidates
                     if 'llama-3.2-11b-vision' in model_id.lower()),
                    None,
                )
                if preferred:
                    candidates = [preferred]
            if candidates:
                models[runtime] = candidates[0]
        assert models.keys() == {'mlx-vlm', 'llama.cpp'}, models

        for runtime, model_id in models.items():
            ordinary = await prompt(
                cdp, page, model_id,
                'Reply with exactly ARK_RUNTIME_OK and nothing else.')
            assert ordinary['success'], f'{runtime} ordinary prompt failed: {ordinary}'
            assert 'ARK_RUNTIME_OK' in ordinary['text'], ordinary
            assert '<ark_tool_call>' not in ordinary['text'], ordinary
            assert not any(
                step['type'] == 'tool_call' for step in ordinary['steps']), ordinary
            print(f'PASS: {runtime} ordinary prompt bypasses tool orchestration')

            memory_question = await prompt(
                cdp, page, model_id,
                'Do you remember this conversation? Reply briefly.')
            assert memory_question['success'], (
                f'{runtime} memory question failed: {memory_question}')
            assert not any(
                step['title'] in {'add_observations', 'create_entities'}
                for step in memory_question['steps']), memory_question
            print(
                f'PASS: {runtime} memory question does not become a memory write')

            memory = await prompt(
                cdp, page, model_id,
                'Search my memory for agent-runtime-probe-that-does-not-exist. '
                'Tell me briefly whether it exists.')
            assert memory['success'], f'{runtime} memory prompt failed: {memory}'
            tool_steps = [
                step for step in memory['steps'] if step['type'] == 'tool_call']
            assert tool_steps, f'{runtime} did not use a memory tool: {memory}'
            assert all(
                step['title'] in {'read_graph', 'search_nodes'}
                for step in tool_steps), memory
            assert any(
                step['type'] == 'observation' for step in memory['steps']), memory
            assert '<ark_tool_call>' not in memory['text'], memory
            print(f'PASS: {runtime} completes a read-only memory tool loop')

        sample_png = (
            'data:image/png;base64,' +
            base64.b64encode((ROOT / 'sample.png').read_bytes()).decode()
        )
        vision_models = {}
        for runtime in {'mlx-vlm', 'llama.cpp'}:
            candidates = [
                model['id'] for model in installed
                if model['runtime'] == runtime and model['supportsVision']
            ]
            if candidates:
                vision_models[runtime] = candidates[0]
        assert vision_models.keys() == {'mlx-vlm', 'llama.cpp'}, installed
        for runtime, model_id in vision_models.items():
            vision = await prompt(
                cdp, page, model_id,
                'Read all visible chat text in the attached image. Reply concisely.',
                [sample_png],
            )
            assert vision['success'], vision
            lowered = vision['text'].lower()
            assert 'poc' in lowered or 'weekend' in lowered, vision
            print(f'PASS: {runtime} vision adapter receives and understands PNG input')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=default_binary())
    parser.add_argument(
        '--artifacts', type=Path,
        default=ROOT / 'test-results/agent-runtime')
    asyncio.run(run(parser.parse_args()))
