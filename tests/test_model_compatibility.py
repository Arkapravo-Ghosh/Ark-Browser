#!/usr/bin/env python3
# Copyright 2026 Arkapravo Ghosh
"""Live CDP regression: every installed local model works with the agent.

Covers the Models page and chat composer for arbitrary Hugging Face models,
not only the two prepared presets:

1. Search results mark vision-capable repositories before download (a GGUF
   projector or an image-text MLX pipeline) and leave text-only ones unmarked.
2. Installed models carry a Vision tag only when their files support images,
   and text-only MLX checkpoints are labelled as running on MLX-LM.
3. The composer's "Attach Image" action is hidden for text-only models.
4. Each installed local model answers through the full agent path: a routed
   direct answer and a memory MCP write + recall.
5. An image sent to a text-only model fails with an explicit reason instead
   of a generic child-process failure.
6. Optionally (--image PATH [--image-words w ...]), each vision-capable model
   transcribes a real image through the agent path (no fixture is tracked in
   the repository, so the caller supplies one).
7. Optionally (--corrupt-gguf), a garbage GGUF is planted as an installed
   model, a prompt is sent to it, and the chat error must quote llama-cli's
   own cause ("invalid magic characters") rather than a generic failure; the
   planted installation is deleted afterwards.
8. Optionally (--expect-refusal REPO ...), each named repository must be
   refused before any byte is downloaded, with the reason recorded (for
   example a model whose smallest quantization exceeds this Mac's memory).
9. Optionally (--download REPO ...), each named public repository is
   downloaded through the Models page, used by the agent (with --image when
   it is vision-capable), and deleted again. Use one GGUF text model, one MLX
   text model, and one MLX vision model to cover all three runtime paths.
"""

import argparse
import asyncio
import base64
import json
import time
from pathlib import Path

from agent_test import browser, default_binary, preserved_file

ROOT = Path(__file__).resolve().parents[1]
RUN_STARTED = time.time()
VISION_GGUF_REPO = 'ggml-org/Qwen2.5-VL-7B-Instruct-GGUF'
TEXT_GGUF_REPO = 'Qwen/Qwen2.5-0.5B-Instruct-GGUF'
DEFAULT_DOWNLOADS = [
    'Qwen/Qwen2.5-0.5B-Instruct-GGUF',        # llama.cpp, text
    'mlx-community/Qwen3-0.6B-4bit',          # MLX-LM, text
    # MLX-VLM, vision. Not SmolVLM/Idefics3: in the bundled transformers 5.17
    # its "PIL" image processor still demands torchvision, which the MLX
    # bundle intentionally omits; Ark reports that with a specific error.
    'mlx-community/Qwen2-VL-2B-Instruct-4bit',
]
# 1x1 PNG; its content is irrelevant because text-only models must refuse it.
TINY_PNG = ('data:image/png;base64,' + base64.b64encode(bytes.fromhex(
    '89504e470d0a1a0a0000000d4948445200000001000000010806000000'
    '1f15c4890000000d49444154789c6360f8cfc0000003010100c9fe92ef'
    '0000000049454e44ae426082')).decode())


async def agent_prompt(cdp, page, conversation_id, message, images=()):
    return await cdp.evaluate(page, f"""(async () => {{
        const {{response}} = await window.__arkTest.pageHandler.sendAgentPrompt({{
            conversationId: {json.dumps(conversation_id)},
            message: {json.dumps(message)},
            images: {json.dumps(list(images))},
            providerCredential: null,
            steeringInstruction: null
        }});
        return {{
            success: response.success,
            response: response.response,
            steps: (response.steps || []).map(step => ({{
                stepType: step.stepType, title: step.title,
                toolName: step.toolName, detail: step.detail}}))
        }};
    }})()""")


async def installed_models(cdp, page):
    return await cdp.evaluate(page, """(async () => {
        const {models} = await window.__arkTest.pageHandler.getInstalledLocalModels();
        return models.map(model => ({
            modelId: model.modelId, displayName: model.displayName,
            repository: model.repository, runtimeBackend: model.runtimeBackend,
            runtimeCompatible: model.runtimeCompatible,
            supportsVision: model.supportsVision}));
    })()""")


async def with_conversation(cdp, page, model_id, body):
    conversation_id = await cdp.evaluate(page, f"""(async () => {{
        const {{state}} = await window.__arkTest.pageHandler.createConversation(
            {json.dumps(model_id)});
        return state.id;
    }})()""")
    try:
        return await body(conversation_id)
    finally:
        await cdp.evaluate(page, f"""(async () => {{
            await window.__arkTest.pageHandler.deleteConversation(
                {json.dumps(conversation_id)});
        }})()""")


async def check_search_markers(cdp, page, report):
    async def search(query):
        return await cdp.evaluate(page, f"""(async () => {{
            const {{results, error}} =
                await window.__arkTest.pageHandler.searchLocalModels({json.dumps(query)});
            return {{error, results: results.map(result => ({{
                id: result.id, supportsVision: result.supportsVision}}))}};
        }})()""")

    vision = await search(VISION_GGUF_REPO)
    text = await search(TEXT_GGUF_REPO)
    vision_hit = next(r for r in vision['results'] if r['id'] == VISION_GGUF_REPO)
    text_hit = next(r for r in text['results'] if r['id'] == TEXT_GGUF_REPO)
    assert vision_hit['supportsVision'] is True, vision_hit
    assert text_hit['supportsVision'] is False, text_hit

    # The rendered search card shows the tag only for the vision repository.
    await cdp.navigate(page, 'ark://ark-chat/#models')
    await cdp.wait_for(page, 'Boolean(window.__arkTest)')
    rendered = await cdp.evaluate(page, f"""(async () => {{
        const input = document.getElementById('model-search-input');
        input.value = {json.dumps(VISION_GGUF_REPO)};
        document.getElementById('model-search-form')
            .dispatchEvent(new Event('submit', {{cancelable: true}}));
        const deadline = Date.now() + 30000;
        while (Date.now() < deadline &&
               !document.querySelector('.search-result-card')) {{
            await new Promise(resolve => setTimeout(resolve, 200));
        }}
        return [...document.querySelectorAll('.search-result-card')].map(card => ({{
            id: card.querySelector('.search-result-title')?.textContent,
            vision: Boolean(card.querySelector('.tag-vision'))}}));
    }})()""")
    card = next(item for item in rendered if item['id'] == VISION_GGUF_REPO)
    assert card['vision'], rendered
    report['search'] = {'vision': vision_hit, 'text': text_hit}
    print('PASS: search results mark vision GGUF repositories before download')


async def check_installed_markers(cdp, page, models, report):
    await cdp.navigate(page, 'ark://ark-chat/#models')
    await cdp.wait_for(page, 'Boolean(window.__arkTest)')
    await cdp.wait_for(
        page, "document.querySelectorAll('.installed-model-card').length > 0")
    cards = await cdp.evaluate(page, """(() =>
        [...document.querySelectorAll('.installed-model-card')].map(card => ({
            name: card.querySelector('h3')?.textContent,
            vision: Boolean(card.querySelector('.tag-vision')),
            meta: card.querySelector('p')?.textContent}))
    )()""")
    for model in models:
        card = next(c for c in cards if c['name'] == model['displayName'])
        assert card['vision'] == model['supportsVision'], (model, card)
        if model['runtimeBackend'] == 'mlx-vlm':
            expected = 'mlx-vlm' if model['supportsVision'] else 'mlx-lm'
            assert card['meta'].startswith(expected), (model, card)
    report['installed_cards'] = cards
    print('PASS: installed models show Vision only when their files support images')


async def check_attach_visibility(cdp, page, models, report):
    await cdp.navigate(page, 'ark://ark-chat/#chat')
    await cdp.wait_for(page, 'Boolean(window.__arkTest)')
    visibility = {}
    for model in models:
        async def body(conversation_id, model=model):
            return await cdp.evaluate(page, f"""(async () => {{
                await window.__arkTest.switchToConversation({json.dumps(conversation_id)});
                document.getElementById('composer-action-btn').click();
                const item = document.getElementById('menu-attach-image');
                const shown = !item.hidden && item.offsetParent !== null;
                document.body.click();
                return {{active: window.__arkTest.getActiveModel(), shown}};
            }})()""")
        state = await with_conversation(cdp, page, model['modelId'], body)
        assert state['active'] == model['modelId'], state
        assert state['shown'] == model['supportsVision'], (model, state)
        visibility[model['displayName']] = state['shown']
    report['attach_visibility'] = visibility
    print('PASS: Attach Image is offered only for vision-capable models')


async def check_agent(cdp, page, model, report, image=None, image_words=(),
                      strict_tools=True):
    """Run one model through the agent loop.

    strict_tools=False accepts a model that runs the memory tools but cannot
    honour the <final_answer> synthesis contract (sub-1B checkpoints); the
    tools must still execute and the direct answer must still be exact.
    """
    async def body(conversation_id):
        # A fixed marker, as in agent_runtime_test.py: the small vision model
        # answers arithmetic instead of emitting the route tag, which would
        # measure router brittleness rather than whether the model runs.
        direct = await agent_prompt(
            cdp, page, conversation_id,
            'Reply with exactly ARK_MODEL_OK and nothing else.')
        assert direct['success'], direct
        assert 'ARK_MODEL_OK' in direct['response'], direct
        assert not any(step['stepType'] == 'tool_call'
                       for step in direct['steps']), direct
        remember = await agent_prompt(
            cdp, page, conversation_id,
            'Remember that my favorite color is teal.')
        assert remember['success'], remember
        assert any(step['stepType'] == 'tool_call' and
                   step['toolName'] in ('add_observations', 'create_entities')
                   for step in remember['steps']), remember
        recall = await agent_prompt(
            cdp, page, conversation_id, 'What is my favorite color?')
        assert recall['success'], recall
        assert any(step['stepType'] == 'tool_call' and
                   step['toolName'] in ('read_graph', 'search_nodes', 'open_nodes')
                   for step in recall['steps']), recall
        recalled = 'teal' in recall['response'].lower()
        assert recalled or not strict_tools, recall
        result = {'direct': direct['response'], 'remember': remember['response'],
                  'recall': recall['response'], 'recall_synthesized': recalled}
        if not model['supportsVision']:
            refused = await agent_prompt(
                cdp, page, conversation_id, 'Describe this image.', [TINY_PNG])
            assert not refused['success'], refused
            assert 'isolated local model process failed' not in \
                refused['response'].lower(), refused
            assert 'image' in refused['response'].lower(), refused
            result['image_refusal'] = refused['response']
        elif image:
            seen = await agent_prompt(
                cdp, page, conversation_id,
                'Transcribe the visible text in this image concisely.', [image])
            assert seen['success'], seen
            lowered = seen['response'].lower()
            missing = [w for w in image_words if w.lower() not in lowered]
            assert not missing, (missing, seen)
            result['image_answer'] = seen['response']
        return result

    result = await with_conversation(cdp, page, model['modelId'], body)
    report.setdefault('agent', {})[model['displayName']] = result
    print(f"PASS: agent direct answer and memory MCP round trip on {model['displayName']}"
          + ('' if result['recall_synthesized'] else
             ' (tools ran; too small to synthesise the tool result)'))
    if 'image_answer' in result:
        print(f"PASS: image transcribed through the agent path on {model['displayName']}")


async def download_and_use(cdp, page, repository, report, image, image_words):
    start = await cdp.evaluate(page, f"""(async () => {{
        const {{state}} = await window.__arkTest.pageHandler.startLocalModelDownload(
            {json.dumps(repository)}, true);
        return state;
    }})()""")
    assert start['state'] != 'error', start
    deadline = asyncio.get_running_loop().time() + 1800
    state = start
    idle_polls = 0
    while asyncio.get_running_loop().time() < deadline:
        state = await cdp.evaluate(page, """(async () => {
            const {state} = await window.__arkTest.pageHandler.getLocalModelState();
            return state;
        })()""")
        if state['installed'] or state['state'] == 'error':
            break
        if state['state'] == 'downloading' and 'card' not in report.setdefault('download_cards', {}).get(repository, {}):
            # The Models page card must describe THIS download, not the
            # prepared preset (its static copy used to say "5.6 GiB").
            card = await cdp.evaluate(page, """(async () => {
                location.hash = 'models';
                await new Promise(resolve => setTimeout(resolve, 1500));
                const text = id => document.getElementById(id)?.textContent || '';
                const card = {title: text('prepared-model-title'), meta: text('prepared-heading-meta'),
                              summary: text('prepared-model-summary'), desc: text('prepared-model-desc'),
                              progress: text('model-progress-label'), detail: text('model-download-detail'),
                              vision: !document.getElementById('model-vision-tag').hidden};
                location.hash = 'chat';
                return card;
            })()""")
            assert card['title'] == state['displayName'], (card, state)
            assert '5.6 GiB' not in card['summary'] or state['bytesTotal'] > 5.5 * 2**30, (card, state)
            assert state['variant'].upper() in card['meta'], (card, state)
            assert card['vision'] == state['supportsVision'], (card, state)
            expected_runtime = 'LLAMA.CPP' if state['runtimeBackend'] == 'llama.cpp' else ('MLX-VLM' if state['supportsVision'] else 'MLX-LM')
            assert expected_runtime in card['meta'], (card, state)
            report['download_cards'][repository] = {'card': card}
        # A started download goes preparing -> starting -> downloading ->
        # verifying -> installed. Falling back to "available" means the
        # browser lost the download item; do not wait 30 minutes for it.
        idle_polls = idle_polls + 1 if state['state'] == 'available' else 0
        assert idle_polls < 5, f'download was lost: {state}'
        await asyncio.sleep(2)
    assert state['installed'], state
    models = await installed_models(cdp, page)
    model = next(m for m in models if m['repository'] == repository)
    assert model['runtimeCompatible'], model
    # The pre-download hint and the installed-file verdict must agree.
    assert model['supportsVision'] == state['supportsVision'], (state, model)
    try:
        await check_agent(cdp, page, model, report, image, image_words,
                          strict_tools=False)
    finally:
        await cdp.evaluate(page, f"""(async () => {{
            await window.__arkTest.pageHandler.deleteLocalModel(
                {json.dumps(model['modelId'])});
        }})()""")
    remaining = await installed_models(cdp, page)
    assert not any(m['repository'] == repository for m in remaining), remaining
    # Deletion must not leave a hollow owner/repo/revision tree behind.
    owner = Path.home() / '.arkbrowser' / 'models' / 'installed' / 'huggingface' / repository.split('/')[0]
    assert not owner.exists() or any(owner.rglob('manifest.json')), owner
    report.setdefault('downloads', []).append({
        'repository': repository, 'variant': state['variant'],
        'runtimeBackend': model['runtimeBackend'],
        'supportsVision': model['supportsVision'],
        'bytes': state['bytesTotal']})
    print(f"PASS: downloaded {repository} ({state['variant']}, "
          f"{'vision' if model['supportsVision'] else 'text'}) runs through "
          f"the agent and deletes cleanly")


async def expect_refusal(cdp, page, repository, report):
    state = await cdp.evaluate(page, f"""(async () => {{
        const {{state}} = await window.__arkTest.pageHandler.startLocalModelDownload(
            {json.dumps(repository)}, true);
        return state;
    }})()""")
    # Refusal happens after the metadata round trip; poll briefly.
    for _ in range(30):
        if state['state'] == 'error' or state['installed'] or \
                state['state'] == 'downloading':
            break
        await asyncio.sleep(1)
        state = await cdp.evaluate(page, """(async () => {
            const {state} = await window.__arkTest.pageHandler.getLocalModelState();
            return state;
        })()""")
    assert state['state'] == 'error', state
    assert state['bytesDownloaded'] == 0, state
    # Nothing may have been written for this repository during this run; an
    # installation left by an earlier session is not this run's doing.
    owner = Path.home() / '.arkbrowser' / 'models' / 'installed' / 'huggingface' / repository.split('/')[0]
    leftovers = [p for p in owner.rglob('*')
                 if p.is_file() and p.name != '.DS_Store'
                 and p.stat().st_mtime >= RUN_STARTED
                 and repository.split('/')[1] in str(p)] if owner.exists() else []
    assert not leftovers, leftovers
    report.setdefault('refusals', []).append({'repository': repository, 'detail': state['detail']})
    print(f"PASS: {repository} refused before download: {state['detail'][:120]}")


CORRUPT_REPO = 'ark-test/corrupt-gguf'
CORRUPT_MODEL_ID = 'local:huggingface:ark-test/corrupt-gguf@deadbeef:Q4_0'


async def check_corrupt_gguf(cdp, page, report):
    """Plant a garbage GGUF under ~/.arkbrowser and expect a specific error."""
    root = Path.home() / '.arkbrowser' / 'models' / 'installed' / 'huggingface'
    install = root / 'ark-test' / 'corrupt-gguf' / 'deadbeef' / 'Q4_0'
    install.mkdir(parents=True, exist_ok=True)
    weights = install / 'corrupt.gguf'
    weights.write_bytes(b'\xde\xad\xbe\xef' * 1024)
    (install / 'manifest.json').write_text(json.dumps({
        'schema_version': 1, 'installation_id': CORRUPT_MODEL_ID,
        'model_id': CORRUPT_MODEL_ID, 'display_name': 'Corrupt GGUF (test)',
        'source': 'huggingface', 'repository': CORRUPT_REPO,
        'resolved_revision': 'deadbeef', 'variant': 'Q4_0',
        'license': 'unknown', 'runtime_backend': 'llama.cpp',
        'runtime_compatibility': 'downloaded_unverified',
        'files': [{'role': 'weights', 'filename': 'corrupt.gguf',
                   'size_bytes': str(weights.stat().st_size)}],
    }))
    try:
        models = await installed_models(cdp, page)
        assert any(m['modelId'] == CORRUPT_MODEL_ID for m in models), models

        async def body(conversation_id):
            return await agent_prompt(cdp, page, conversation_id, 'Hello')
        result = await with_conversation(cdp, page, CORRUPT_MODEL_ID, body)
        assert not result['success'], result
        lowered = result['response'].lower()
        assert 'invalid magic characters' in lowered, result
        assert 'isolated local model process failed' not in lowered, result
        report['corrupt_gguf'] = result['response']
    finally:
        await cdp.evaluate(page, f"""(async () => {{
            await window.__arkTest.pageHandler.deleteLocalModel(
                {json.dumps(CORRUPT_MODEL_ID)});
        }})()""")
        assert not (root / 'ark-test').exists(), 'empty parent directories left behind'

    remaining = await installed_models(cdp, page)
    assert not any(m['modelId'] == CORRUPT_MODEL_ID for m in remaining), remaining
    print('PASS: a corrupt GGUF reports llama-cli\'s own cause and deletes cleanly')


async def run(args):
    artifacts = args.artifacts.resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    memory_file = Path.home() / '.arkbrowser' / 'mcp' / 'memory.jsonl'
    report = {}
    async with preserved_file(memory_file), \
            browser(args.binary.resolve(), artifacts) as cdp:
        page = await cdp.first_page()
        await cdp.navigate(page, 'ark://ark-chat/#chat')
        await cdp.wait_for(page, 'Boolean(window.__arkTest)')
        models = [m for m in await installed_models(cdp, page)
                  if m['runtimeCompatible']]
        assert models, 'no installed local models'
        if args.models:
            # Whole-token match so "1B" does not also select "11B".
            def selected(model):
                tokens = model['displayName'].lower().split()
                return any(f.lower() in tokens for f in args.models)
            models = [m for m in models if selected(m)]
            assert models, f'no installed model matches {args.models}'
        report['models'] = models

        await check_search_markers(cdp, page, report)
        await check_installed_markers(cdp, page, models, report)
        await check_attach_visibility(cdp, page, models, report)
        await cdp.screenshot(page, artifacts / 'composer.png')
        image = None
        if args.image:
            data = args.image.resolve().read_bytes()
            mime = 'image/png' if data[:8] == b'\x89PNG\r\n\x1a\n' else 'image/jpeg'
            image = f'data:{mime};base64,' + base64.b64encode(data).decode()
        if not args.skip_inference:
            for model in models:
                await check_agent(cdp, page, model, report, image,
                                  args.image_words or ())
        if args.corrupt_gguf:
            await check_corrupt_gguf(cdp, page, report)
        for repository in (args.expect_refusal or []):
            await expect_refusal(cdp, page, repository, report)
        for repository in (args.download or []):
            await download_and_use(cdp, page, repository, report, image,
                                   args.image_words or ())
        await cdp.navigate(page, 'ark://ark-chat/#models')
        await cdp.wait_for(page, 'Boolean(window.__arkTest)')
        await asyncio.sleep(1)
        await cdp.screenshot(page, artifacts / 'models.png')

    (artifacts / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: all installed local models are usable by the agent')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=default_binary())
    parser.add_argument('--artifacts', type=Path,
                        default=ROOT / 'test-results/model-compatibility')
    parser.add_argument('--models', nargs='*',
                        help='Only test installed models whose name contains one of these.')
    parser.add_argument('--skip-inference', action='store_true')
    parser.add_argument('--image', type=Path,
                        help='PNG or JPEG sent to each vision-capable model.')
    parser.add_argument('--image-words', nargs='*',
                        help='Words that must appear in the image transcription.')
    parser.add_argument('--corrupt-gguf', action='store_true',
                        help='Plant a garbage GGUF install and verify the '
                             'chat error quotes llama-cli\'s cause.')
    parser.add_argument('--expect-refusal', nargs='*',
                        help='Repositories that must be refused before download.')
    parser.add_argument('--download', nargs='*',
                        help='Also download, use, and delete these public '
                             'repositories (default: one GGUF text, one MLX '
                             'text, one MLX vision model).')
    args = parser.parse_args()
    if args.download is not None and not args.download:
        args.download = DEFAULT_DOWNLOADS
    asyncio.run(run(args))


if __name__ == '__main__':
    main()
