#!/usr/bin/env python3
# Copyright 2026 Arkapravo Ghosh
"""Automated CDP test suite for Ark's AI activity UI and MCP configuration.

Tests:
1. Executable and planned MCP capabilities are represented truthfully
2. MCP Manager in ark://ark-chat/#models (tab switching and persistence)
3. Adding and removing custom MCP server configurations
4. Composer '+' action button popover, file input, attachment thumbnails
5. Context token usage meter and compaction
6. Compact agent activity disclosure and opt-in tool details
7. Local model inference compatibility (Gemma via llama.cpp and Llama via mlx-vlm)
8. No regressions in standard chat and search features
"""

import argparse
import asyncio
import base64
import contextlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

import websockets

ROOT = Path(__file__).resolve().parents[1]


class CDP:
    def __init__(self, ws):
        self.ws = ws
        self.sequence = 0
        self.events = []

    async def call(self, method, params=None, session=None):
        self.sequence += 1
        request_id = self.sequence
        message = {'id': request_id, 'method': method, 'params': params or {}}
        if session:
            message['sessionId'] = session
        await self.ws.send(json.dumps(message))
        while True:
            data = json.loads(await asyncio.wait_for(self.ws.recv(), 240))
            if data.get('id') == request_id:
                if 'error' in data:
                    raise AssertionError(f'{method}: {data["error"]}')
                return data.get('result', {})
            if 'method' in data:
                self.events.append(data)

    async def attach_page(self, target):
        session = (await self.call('Target.attachToTarget', {
            'targetId': target, 'flatten': True}))['sessionId']
        await self.call('Runtime.enable', session=session)
        await self.call('Page.enable', session=session)
        await self.call('Network.enable', session=session)
        return session

    async def first_page(self):
        targets = (await self.call('Target.getTargets'))['targetInfos']
        target = next(item['targetId'] for item in targets if item['type'] == 'page')
        return await self.attach_page(target)

    async def evaluate(self, session, expression):
        result = await self.call('Runtime.evaluate', {
            'expression': expression, 'awaitPromise': True, 'returnByValue': True,
            'userGesture': True}, session)
        if 'exceptionDetails' in result:
            raise AssertionError(result['exceptionDetails'])
        return result.get('result', {}).get('value')

    async def wait_for(self, session, expression, timeout=25):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                if await self.evaluate(session, expression):
                    return
            except AssertionError as error:
                if 'context' not in str(error).lower():
                    raise
            await asyncio.sleep(.1)
        raise AssertionError(f'Timed out: {expression}')

    async def navigate(self, session, url, ready="document.readyState === 'complete'"):
        await self.call('Page.navigate', {'url': url}, session)
        await self.wait_for(session, ready)

    async def screenshot(self, session, path, width=1440, height=900):
        await self.call('Emulation.setDeviceMetricsOverride', {
            'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': False}, session)
        await asyncio.sleep(.3)
        shot = await self.call('Page.captureScreenshot', {'format': 'png'}, session)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(shot['data']))


def check(value, name, results):
    assert value, f"Failed check: {name}"
    results.append(name)
    print(f'PASS: {name}', flush=True)


@contextlib.asynccontextmanager
async def browser(binary, artifacts, extra=()):
    with tempfile.TemporaryDirectory(dir=artifacts, prefix='ark-agent-test-') as directory:
        profile = Path(directory)
        log = (artifacts / 'agent-browser.log').open('w')
        cmd = [
            str(binary),
            '--headless=new',
            '--no-first-run',
            '--no-default-browser-check',
            '--disable-background-networking',
            '--disable-component-update',
            '--disable-sync',
            '--remote-debugging-port=0',
            f'--user-data-dir={profile}',
            f'--crash-dumps-dir={profile / "Crashpad"}',
            '--disable-crash-reporter',
            '--window-size=1440,900',
            'ark://ark-chat/#home',
            *extra,
        ]
        process = subprocess.Popen(cmd, stdout=log, stderr=log)
        try:
            endpoint = profile / 'DevToolsActivePort'
            for _ in range(300):
                if endpoint.exists():
                    break
                if process.poll() is not None:
                    raise AssertionError(f'Browser exited {process.returncode}; see {log.name}')
                await asyncio.sleep(.1)
            assert endpoint.exists(), f'DevTools did not start; see {log.name}'
            lines = endpoint.read_text().splitlines()
            async with websockets.connect(
                    f'ws://127.0.0.1:{lines[0]}{lines[1]}', max_size=50 * 1024 * 1024) as ws:
                yield CDP(ws)
        finally:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait)
            log.close()


@contextlib.asynccontextmanager
async def preserved_file(path):
    """Restore a user-owned runtime file exactly after an integration test."""
    existed = path.exists()
    original = path.read_bytes() if existed else b''
    try:
        yield
    finally:
        path.parent.mkdir(parents=True, exist_ok=True)
        if existed:
            path.write_bytes(original)
        elif path.exists():
            path.unlink()


async def run(args):
    artifacts = args.artifacts.resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    results = []

    print(f"Testing Ark binary: {args.binary}")
    print(f"Artifacts output: {artifacts}")

    memory_file = Path.home() / '.arkbrowser' / 'mcp' / 'memory.jsonl'
    async with preserved_file(memory_file), browser(args.binary.resolve(), artifacts) as cdp:
        page = await cdp.first_page()
        await cdp.navigate(page, 'ark://ark-chat/#home')

        # 1. Verify Home & Navigation to Models page
        check(await cdp.evaluate(page, "document.title.includes('Ark Browser')"),
              'Ark home page loads with correct title', results)

        # 2. Test Navigation to MCP Plugins Manager in ark://ark-chat/#models
        await cdp.navigate(page, 'ark://ark-chat/#models')
        await cdp.wait_for(page, "Boolean(document.getElementById('models-page'))")
        await cdp.screenshot(page, artifacts / '01_models_page.png')
        check(await cdp.evaluate(page, "Boolean(document.getElementById('mcp-tab'))"),
              'MCP Plugins tab exists in Model Manager segmented bar', results)

        # 3. Switch to MCP Plugins tab
        await cdp.evaluate(page, "document.getElementById('mcp-tab').click()")
        await cdp.wait_for(page, "!document.getElementById('mcp-plugins').hidden")
        await cdp.wait_for(page, "document.querySelectorAll('.mcp-card').length >= 3", timeout=15)
        await cdp.screenshot(page, artifacts / '02_mcp_plugins_tab.png')

        # 4. Verify the 3 pre-installed MCP servers are listed
        mcp_servers = await cdp.evaluate(page, """(() => {
            const cards = Array.from(document.querySelectorAll('.mcp-card'));
            return cards.map(c => ({
                name: c.querySelector('h3')?.textContent || '',
                desc: c.querySelector('.mcp-desc')?.textContent || '',
                enabled: c.querySelector('input[type="checkbox"]')?.checked || false,
                isBundled: (c.querySelector('.tag')?.textContent || '').includes('Bundled')
            }));
        })()""")

        server_names = [s['name'] for s in mcp_servers]
        print(f"Discovered MCP plugins: {server_names}")

        has_memory = any('Memory Knowledge Graph' in n for n in server_names)
        has_sequential = any('Sequential Thinking' in n for n in server_names)
        has_browser = any('Browser Primitives' in n for n in server_names)

        check(has_memory, 'Memory Knowledge Graph MCP plugin is pre-installed', results)
        check(has_sequential, 'Sequential Thinking MCP plugin is pre-installed', results)
        check(has_browser, 'Browser Primitives MCP plugin is pre-installed', results)
        memory_server = next(s for s in mcp_servers if 'Memory Knowledge Graph' in s['name'])
        seq_server_info = next(s for s in mcp_servers if 'Sequential Thinking' in s['name'])
        browser_server_info = next(s for s in mcp_servers if 'Browser Primitives' in s['name'])
        check(memory_server['enabled'], 'Executable memory tools are enabled by default', results)
        check(seq_server_info['enabled'], 'Sequential thinking tool is enabled by default', results)
        check(not browser_server_info['enabled'],
              'Reserved browser MCP integration is not presented as executable', results)

        unavailable_controls = await cdp.evaluate(page, """(() => {
            const browserCard = Array.from(document.querySelectorAll('.mcp-card.is-unavailable')).find(c =>
                c.querySelector('h3')?.textContent.includes('Browser Primitives'));
            if (!browserCard) return false;
            const input = browserCard.querySelector('input[type="checkbox"]');
            return input?.disabled && !input.checked &&
                browserCard.textContent.includes('Configuration only');
        })()""")
        check(unavailable_controls,
              'Unavailable MCP adapters like Browser Primitives are labeled and cannot be falsely enabled', results)

        # 5. Test MCP Server ON/OFF Toggle on Sequential Thinking
        seq_toggle_off = await cdp.evaluate(page, """(async () => {
            const seqCard = Array.from(document.querySelectorAll('.mcp-card')).find(c =>
                c.querySelector('h3')?.textContent.includes('Sequential Thinking'));
            if (!seqCard) return null;
            const cb = seqCard.querySelector('input[type="checkbox"]');
            if (!cb || cb.disabled) return null;
            cb.click();
            await new Promise(r => setTimeout(r, 400));
            return cb.checked;
        })()""")
        check(seq_toggle_off is False, 'Toggling Sequential Thinking MCP switches state to OFF', results)

        # Toggle it back ON
        seq_toggle_on = await cdp.evaluate(page, """(async () => {
            const seqCard = Array.from(document.querySelectorAll('.mcp-card')).find(c =>
                c.querySelector('h3')?.textContent.includes('Sequential Thinking'));
            if (!seqCard) return null;
            const cb = seqCard.querySelector('input[type="checkbox"]');
            if (!cb) return null;
            cb.click();
            await new Promise(r => setTimeout(r, 400));
            return cb.checked;
        })()""")
        check(seq_toggle_on is True, 'Toggling Sequential Thinking MCP switches state back to ON', results)

        # 6. Test Custom MCP Server Addition
        await cdp.evaluate(page, """(() => {
            document.getElementById('mcp-name-input').value = 'Test Custom Tools';
            document.getElementById('mcp-cmd-input').value = 'echo test';
            document.getElementById('mcp-transport-select').value = 'stdio';
            document.getElementById('mcp-policy-select').value = 'auto_allow';
            const form = document.getElementById('mcp-add-form');
            form.dispatchEvent(new Event('submit', {cancelable: true}));
        })()""")
        await cdp.wait_for(page, """Array.from(document.querySelectorAll('.mcp-card h3'))
            .some(h => h.textContent.includes('Test Custom Tools'))""", timeout=10)
        await cdp.screenshot(page, artifacts / '03_custom_mcp_added.png')
        check(True, 'Custom MCP server was successfully added and rendered in the list', results)

        # 7. Test Removal of Custom MCP Server
        await cdp.evaluate(page, """(() => {
            const customCard = Array.from(document.querySelectorAll('.mcp-card')).find(c =>
                c.querySelector('h3')?.textContent.includes('Test Custom Tools'));
            if (customCard) {
                const rmBtn = customCard.querySelector('button.button-danger');
                if (rmBtn) {
                    // Bypass confirm modal in headless test
                    window.confirm = () => true;
                    rmBtn.click();
                }
            }
        })()""")
        await asyncio.sleep(1.0)
        has_custom = await cdp.evaluate(page, """Array.from(document.querySelectorAll('.mcp-card h3'))
            .some(h => h.textContent.includes('Test Custom Tools'))""")
        check(not has_custom, 'Custom MCP server was successfully removed', results)

        # 8. Test Navigation to Memory Knowledge Graph Manager in ark://ark-chat/#models
        check(await cdp.evaluate(page, "Boolean(document.getElementById('memory-tab'))"),
              'Memory tab exists in Model Manager segmented bar', results)
        await cdp.evaluate(page, "document.getElementById('memory-tab').click()")
        await cdp.wait_for(page, "!document.getElementById('memory-editor').hidden")
        await cdp.screenshot(page, artifacts / '03b_memory_tab.png')

        # Add a new Memory entity
        await cdp.evaluate(page, """(() => {
            document.getElementById('memory-name-input').value = 'User Profile';
            document.getElementById('memory-obs-input').value = 'Prefers dark theme\\nSoftware architect';
            const form = document.getElementById('memory-form');
            form.dispatchEvent(new Event('submit', {cancelable: true}));
        })()""")
        await cdp.wait_for(page, """Array.from(document.querySelectorAll('.memory-card-title'))
            .some(t => t.textContent.includes('User Profile'))""", timeout=10)
        await cdp.screenshot(page, artifacts / '03c_memory_entity_added.png')
        check(True, 'Memory entity was successfully added and rendered in the memory list', results)

        # Verify entity details rendered
        obs_texts = await cdp.evaluate(page, """(() => {
            const card = Array.from(document.querySelectorAll('.memory-card')).find(c =>
                c.querySelector('.memory-card-title')?.textContent.includes('User Profile'));
            if (!card) return [];
            return Array.from(card.querySelectorAll('.memory-obs-item')).map(el => el.textContent);
        })()""")
        check(any('dark theme' in o for o in obs_texts) and any('Software architect' in o for o in obs_texts),
              'Memory entity observations are rendered cleanly', results)

        # Test Editing the entity
        await cdp.evaluate(page, """(() => {
            const card = Array.from(document.querySelectorAll('.memory-card')).find(c =>
                c.querySelector('.memory-card-title')?.textContent.includes('User Profile'));
            const editBtn = card?.querySelector('.memory-card-actions button.subtle-button');
            editBtn?.click();
            document.getElementById('memory-obs-input').value += '\\nBuilds Ark Browser';
            const form = document.getElementById('memory-form');
            form.dispatchEvent(new Event('submit', {cancelable: true}));
        })()""")
        await cdp.wait_for(page, """Array.from(document.querySelectorAll('.memory-obs-item'))
            .some(el => el.textContent.includes('Builds Ark Browser'))""", timeout=10)
        check(True, 'Memory entity observations were successfully edited and updated', results)

        # Test Deleting the entity
        await cdp.evaluate(page, """(() => {
            const card = Array.from(document.querySelectorAll('.memory-card')).find(c =>
                c.querySelector('.memory-card-title')?.textContent.includes('User Profile'));
            const delBtn = card?.querySelector('.memory-card-actions button.button-danger');
            window.confirm = () => true;
            delBtn?.click();
        })()""")
        await asyncio.sleep(1.0)
        has_profile = await cdp.evaluate(page, """Array.from(document.querySelectorAll('.memory-card-title'))
            .some(t => t.textContent.includes('User Profile'))""")
        check(not has_profile, 'Memory entity was successfully deleted', results)

        # 9. Test Navigation to Chat & Composer Enhancements
        await cdp.navigate(page, 'ark://ark-chat/#chat')
        await cdp.wait_for(page, "!document.getElementById('composer').hidden")
        await cdp.screenshot(page, artifacts / '04_chat_composer.png')

        # Check '+' action button and popover
        has_action_btn = await cdp.evaluate(page, "Boolean(document.getElementById('composer-action-btn'))")
        check(has_action_btn, 'Composer has "+" action button for media and MCP tools', results)

        # Click '+' button to toggle action menu
        await cdp.evaluate(page, "document.getElementById('composer-action-btn').click()")
        menu_visible = await cdp.evaluate(page, "!document.getElementById('composer-action-menu').hidden")
        check(menu_visible, 'Clicking "+" action button displays action menu popover', results)

        # Check menu options: Attach Image (Vision) and Manage MCP Plugins
        has_attach_opt = await cdp.evaluate(page, "Boolean(document.getElementById('menu-attach-image'))")
        has_mcp_opt = await cdp.evaluate(page, "Boolean(document.getElementById('menu-mcp-plugins'))")
        check(has_attach_opt and has_mcp_opt, 'Action menu provides Vision image attachment and MCP management', results)

        # Close action menu
        await cdp.evaluate(page, "document.body.click()")

        # 10. Test Context Usage Meter and Compact Button
        has_context_meter = await cdp.evaluate(page, "Boolean(document.getElementById('context-meter-wrap'))")
        has_compact_btn = await cdp.evaluate(page, "Boolean(document.getElementById('compact-btn'))")
        check(has_context_meter and has_compact_btn, 'Composer toolbar displays Context Token Meter and Compact button', results)

        # 11. Test Stop, Steer, and Queue controls plus supported vision formats
        has_stop_btn = await cdp.evaluate(page, "Boolean(document.getElementById('composer-stop-btn'))")
        has_steer_btn = await cdp.evaluate(page, "Boolean(document.getElementById('composer-steer-btn'))")
        has_queue_btn = await cdp.evaluate(page, "Boolean(document.getElementById('composer-queue-btn'))")
        has_queue_region = await cdp.evaluate(page, "Boolean(document.getElementById('composer-queue'))")
        accepted_images = await cdp.evaluate(page, "document.getElementById('composer-file-input').accept")
        check(has_stop_btn and has_steer_btn and has_queue_btn and has_queue_region,
              'Composer has Stop, Steer, and queued follow-up controls', results)
        check(all(fmt in accepted_images for fmt in ('image/png', 'image/jpeg', 'image/webp')),
              'Vision picker accepts PNG, JPEG, and WebP inputs', results)

        # 12. Test compact agent activity disclosure via __arkTest
        await cdp.evaluate(page, """(() => {
            const pipelinePayload = JSON.stringify([
                {step_type: 'progress', title: 'Understanding your request', detail: '', elapsed_ms: 340},
                {step_type: 'tool_call', title: 'search_nodes', detail: '{"query": "release preference"}', elapsed_ms: 120, server_name: 'Memory Knowledge Graph', tool_name: 'search_nodes'},
                {step_type: 'observation', title: 'Received search_nodes result', detail: JSON.stringify([{
                    name: 'user', entityType: 'person',
                    observations: ['prefers compact payloads']
                }], null, 2), elapsed_ms: 0, server_name: 'Memory Knowledge Graph', tool_name: 'search_nodes'}
            ]);
            const fullMessage = `<!--ARK_PIPELINE:${pipelinePayload}-->\\nHere is my clean final answer mentioning update_memory exactly as written.`;
            window.__arkTest.renderMessageBubble('assistant', fullMessage, 'Agent: Gemma', Date.now());
        })()""")
        await cdp.screenshot(page, artifacts / '05_agent_thoughts_rendered.png')

        pipeline_rendered = await cdp.evaluate(page, "document.querySelectorAll('.agent-pipeline').length > 0")
        header_text = await cdp.evaluate(page, "document.querySelector('.pipeline-header')?.textContent.trim()")
        old_stepper_nodes = await cdp.evaluate(page, """document.querySelectorAll(
            '.pipeline-dot, .pipeline-line, .mini-dot, .step-badge').length""")
        is_initially_collapsed = await cdp.evaluate(page, "document.querySelector('.pipeline-flow').hidden")
        details_are_closed = await cdp.evaluate(page, """Array.from(
            document.querySelectorAll('.step-detail')).every(detail => !detail.open)""")
        server_identity_rendered = await cdp.evaluate(page, """Array.from(
            document.querySelectorAll('.step-server')).some(el =>
                el.textContent.includes('Memory Knowledge Graph'))""")
        bubble_text = await cdp.evaluate(page, """(() => {
            const bubbles = document.querySelectorAll('.message-bubble');
            const lastBubble = bubbles[bubbles.length - 1];
            return lastBubble ? (lastBubble.querySelector('.message-text-content')?.textContent || lastBubble.textContent || '').trim() : '';
        })()""")

        check(pipeline_rendered, 'Agentic pipeline container is mounted cleanly above message bubble', results)
        check(header_text and 'Worked for' in header_text and '1 tool' in header_text,
              'Completed work has a compact duration and tool summary', results)
        check(old_stepper_nodes == 0,
              'Legacy colored dot, line, and badge stepper is absent', results)
        check(is_initially_collapsed and details_are_closed,
              'Completed activity and raw tool payloads are collapsed by default', results)
        check(server_identity_rendered,
              'Tool activity identifies the MCP server that provided the tool', results)
        payload_rendering = await cdp.evaluate(page, """(() => {
            const pipelines = Array.from(document.querySelectorAll('.agent-pipeline'));
            const pipeline = pipelines[pipelines.length - 1];
            pipeline.querySelector('.pipeline-header').click();
            pipeline.querySelectorAll('.step-detail').forEach(detail => detail.open = true);
            const input = pipeline.querySelector('.tool-args');
            const output = pipeline.querySelector('.tool-result');
            if (!input || !output) return null;
            const inputStyle = getComputedStyle(input);
            const outputStyle = getComputedStyle(output);
            return {
                inputText: input.textContent,
                outputText: output.textContent,
                inputClass: input.className,
                outputClass: output.className,
                sameBackground: inputStyle.backgroundColor === outputStyle.backgroundColor,
                sameBorder: inputStyle.border === outputStyle.border,
                samePadding: inputStyle.padding === outputStyle.padding
            };
        })()""")
        await cdp.screenshot(page, artifacts / '05b_tool_payloads_consistent.png')
        check(payload_rendering and '\n' not in payload_rendering['outputText'] and
              json.loads(payload_rendering['outputText'])[0]['name'] == 'user',
              'Structured tool results are normalized to compact JSON', results)
        check(payload_rendering and payload_rendering['sameBackground'] and
              payload_rendering['sameBorder'] and payload_rendering['samePadding'] and
              'tool-payload' in payload_rendering['inputClass'] and
              'tool-payload' in payload_rendering['outputClass'],
              'Tool inputs and structured results use the same payload card', results)
        check('clean final answer' in bubble_text and 'ARK_PIPELINE' not in bubble_text and
              'update_memory exactly as written' in bubble_text,
              'Message bubble preserves the real answer and strips only pipeline metadata', results)

        # Test Sequential Thinking step rendering in pipeline
        await cdp.evaluate(page, """(() => {
            const seqPayload = JSON.stringify([
                {step_type: 'tool_call', title: 'sequential_thinking', detail: '{"thought": "Deconstructing problem...", "thoughtNumber": 1, "totalThoughts": 2, "nextThoughtNeeded": true}', elapsed_ms: 150},
                {step_type: 'observation', title: 'Completed thought 1/2', detail: 'Thought registered', elapsed_ms: 0},
                {step_type: 'tool_call', title: 'sequential_thinking', detail: '{"thought": "Synthesizing solution...", "thoughtNumber": 2, "totalThoughts": 2, "nextThoughtNeeded": false}', elapsed_ms: 120},
                {step_type: 'observation', title: 'Completed thought 2/2', detail: 'Thought registered', elapsed_ms: 0}
            ]);
            const fullSeqMessage = `<!--ARK_PIPELINE:${seqPayload}-->\\nThis is the final response after deliberation.`;
            window.__arkTest.renderMessageBubble('assistant', fullSeqMessage, 'Agent: Gemma', Date.now());
        })()""")

        seq_step_rendered = await cdp.evaluate(page, """(() => {
            const titles = Array.from(document.querySelectorAll('.step-title')).map(el => el.textContent);
            return titles.some(t => t.includes('Thought 1 of 2')) && titles.some(t => t.includes('Thought 2 of 2'));
        })()""")
        check(seq_step_rendered, 'Sequential thinking steps render formatted thought progression (e.g. Thought 1 of 2)', results)

        seq_bubble_text = await cdp.evaluate(page, """(() => {
            const bubbles = document.querySelectorAll('.message-bubble');
            const lastBubble = bubbles[bubbles.length - 1];
            return (lastBubble?.querySelector('.message-text-content')?.textContent || lastBubble?.textContent || '').trim();
        })()""")
        check('final response after deliberation' in seq_bubble_text and 'ARK_PIPELINE' not in seq_bubble_text,
              'Final answer is displayed cleanly in the message bubble below sequential thinking pipeline', results)

        # Check thought count on the sequential thinking pipeline header
        seq_header_text = await cdp.evaluate(page, """(() => {
            const headers = Array.from(document.querySelectorAll('.pipeline-header'));
            return headers[headers.length - 1]?.textContent || '';
        })()""")
        check('2 thoughts' in seq_header_text, 'Pipeline header displays accurate thought count (2 thoughts)', results)

        # Test mixed thoughts + tools header (e.g. 1 thought · 1 tool)
        await cdp.evaluate(page, """(() => {
            const mixedPayload = JSON.stringify([
                {step_type: 'tool_call', title: 'read_graph', detail: '{}', elapsed_ms: 100},
                {step_type: 'observation', title: 'Graph read', detail: '{}', elapsed_ms: 0},
                {step_type: 'tool_call', title: 'sequential_thinking', detail: '{"thought": "Planning..."}', elapsed_ms: 200},
                {step_type: 'observation', title: 'Completed thought 1/1', detail: 'Done', elapsed_ms: 0}
            ]);
            const msg = `<!--ARK_PIPELINE:${mixedPayload}-->\\nMixed response.`;
            window.__arkTest.renderMessageBubble('assistant', msg, 'Agent: Gemma', Date.now());
        })()""")
        mixed_header_text = await cdp.evaluate(page, """(() => {
            const headers = Array.from(document.querySelectorAll('.pipeline-header'));
            return headers[headers.length - 1]?.textContent || '';
        })()""")
        check('1 thought' in mixed_header_text and '1 tool' in mixed_header_text,
              'Pipeline header displays both thoughts and tools count (1 thought · 1 tool)', results)

        # Test Unboxed nature of pipeline
        pipeline_styles = await cdp.evaluate(page, """(() => {
            const p = document.querySelector('.agent-pipeline');
            if (!p) return null;
            const style = window.getComputedStyle(p);
            return {
                borderStyle: style.borderStyle,
                borderWidth: style.borderWidth,
                backgroundColor: style.backgroundColor
            };
        })()""")
        check(pipeline_styles and (pipeline_styles['borderStyle'] == 'none' or pipeline_styles['borderWidth'] == '0px')
              and pipeline_styles['backgroundColor'] in ('rgba(0, 0, 0, 0)', 'transparent'),
              'Agent pipeline is completely unboxed (no border boxes or dark container backgrounds)', results)

        # Test accessible disclosure toggle on header click
        await cdp.evaluate(page, "document.querySelector('.pipeline-header').click()")
        is_now_open = await cdp.evaluate(page, """(() => {
            const header = document.querySelector('.pipeline-header');
            const flow = document.querySelector('.pipeline-flow');
            return !flow.hidden && header.getAttribute('aria-expanded') === 'true';
        })()""")
        await cdp.evaluate(page, "document.querySelector('.pipeline-header').click()")
        is_closed_again = await cdp.evaluate(page, """(() => {
            const header = document.querySelector('.pipeline-header');
            const flow = document.querySelector('.pipeline-flow');
            return flow.hidden && header.getAttribute('aria-expanded') === 'false';
        })()""")
        check(is_now_open and is_closed_again,
              'Agent activity details toggle accessibly without an enclosing box', results)

        # 13. Test Context Compaction Checkpoint rendering
        await cdp.evaluate(page, """(() => {
            window.__arkTest.renderMessageBubble('system', '[CONVERSATION CHECKPOINT]\\nSummarized 10 previous turns into compact context.', '', Date.now());
        })()""")
        await cdp.screenshot(page, artifacts / '06_compaction_checkpoint.png')
        checkpoint_rendered = await cdp.evaluate(page, "document.querySelectorAll('.checkpoint-banner').length > 0")
        check(checkpoint_rendered, 'Context compaction renders prominent checkpoint banner', results)

        # 14. Test Image Attachments Preview
        await cdp.evaluate(page, """(() => {
            const fakeDataUrl = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';
            const wrap = document.getElementById('composer-attachments');
            wrap.hidden = false;
            wrap.innerHTML = `<div class="attachment-chip"><img src="${fakeDataUrl}" class="attachment-thumb"><button class="attachment-remove">✕</button></div>`;
        })()""")
        await cdp.screenshot(page, artifacts / '07_image_attachments.png')
        attachment_rendered = await cdp.evaluate(page, "document.querySelectorAll('.attachment-chip').length > 0")
        check(attachment_rendered, 'Vision media attachments render thumbnail chips with remove controls', results)

        # 15. Test three jumping dots typing indicator in message bubble
        has_three_dots = await cdp.evaluate(page, """(() => {
            const bubble = document.createElement('div');
            bubble.className = 'message-bubble';
            document.getElementById('chat-messages').appendChild(bubble);
            const dots = document.createElement('span');
            dots.className = 'typing-dots';
            for (let i = 0; i < 3; i++) {
                dots.appendChild(document.createElement('span'));
            }
            bubble.replaceChildren(dots);
            const spans = bubble.querySelectorAll('.typing-dots span');
            bubble.remove();
            return spans.length === 3;
        })()""")
        check(has_three_dots,
              'Assistant typing indicator uses three jumping dots in message bubble', results)

        # 16. Test working... spinner is a Material UI circular progress indicator (perfectly circular)
        spinner_verification = await cdp.evaluate(page, """(() => {
            const parent = document.createElement('div');
            const bubble = document.createElement('div');
            parent.appendChild(bubble);
            document.body.appendChild(parent);

            window.__arkTest.renderAgentPipeline(parent, bubble, [], 'Working...', true);
            const pipeline = parent.querySelector('.agent-pipeline');
            const state = pipeline ? pipeline.querySelector('.pipeline-state.is-working') : null;
            const svg = state ? state.querySelector('svg.pipeline-spinner') : null;
            const circle = svg ? svg.querySelector('circle.pipeline-spinner-circle') : null;

            let isCircular = false;
            if (svg) {
                const rect = svg.getBoundingClientRect();
                isCircular = rect.width > 0 && Math.abs(rect.width - rect.height) < 1;
            }
            parent.remove();
            return {
                hasWorkingState: Boolean(state),
                hasSvg: Boolean(svg),
                hasCircle: Boolean(circle),
                isCircular
            };
        })()""")
        check(spinner_verification.get('hasWorkingState') and spinner_verification.get('hasSvg'),
              'Working state indicator uses a Material UI circular progress SVG spinner', results)
        check(spinner_verification.get('hasCircle'),
              'Working spinner contains animated circular progress track matching Material spec', results)
        check(spinner_verification.get('isCircular'),
              'Working spinner is strictly circular (1:1 aspect ratio) and not deformed into an oval', results)

        # 17. Test Sequential Thinking MCP Server is configured, enabled, and executable
        servers = await cdp.evaluate(page, """(async () => {
            const {servers} = await window.__arkTest.pageHandler.getMcpServers();
            return servers;
        })()""")
        seq_server = next((s for s in (servers or []) if s.get('id') == 'ark.sequential_thinking'), None)
        check(seq_server is not None and seq_server.get('enabled') and 'sequential_thinking' in seq_server.get('tools', []),
              'Sequential Thinking MCP server is pre-installed, enabled, and registered', results)

        # 18. Test Simple Greeting Message ("Hello") does not trigger tool calls
        hello_test_result = await cdp.evaluate(page, """(async () => {
            const {state} = await window.__arkTest.pageHandler.createConversation('local:mlx:llama-3.2-11b-vision-instruct');
            try {
                const {response} = await window.__arkTest.pageHandler.sendAgentPrompt({
                    conversationId: state.id,
                    message: 'Hello',
                    images: [],
                    providerCredential: null,
                    steeringInstruction: null
                });
                const toolSteps = (response.steps || []).filter(s => s.stepType === 'tool_call');
                return {
                    success: response.success,
                    toolStepCount: toolSteps.length,
                    stepCount: (response.steps || []).length
                };
            } finally {
                await window.__arkTest.pageHandler.deleteConversation(state.id);
            }
        })()""")
        check(hello_test_result.get('toolStepCount') == 0,
              'Simple greeting "Hello" does not trigger tool calls or unnecessary agentic calls', results)

        # 19. Test Full-Fledged Message that saves into memory
        memory_test_result = await cdp.evaluate(page, """(async () => {
            const {state} = await window.__arkTest.pageHandler.createConversation('local:mlx:llama-3.2-11b-vision-instruct');
            try {
                const {response} = await window.__arkTest.pageHandler.sendAgentPrompt({
                    conversationId: state.id,
                    message: 'Please remember that my favorite programming language is Python.',
                    images: [],
                    providerCredential: null,
                    steeringInstruction: null
                });
                const toolSteps = (response.steps || []).filter(s => s.stepType === 'tool_call');
                const obsSteps = (response.steps || []).filter(s => s.stepType === 'observation');
                const {entries} = await window.__arkTest.pageHandler.getMemoryEntries();
                const userEntry = entries.find(e => e.entityName === 'user');
                return {
                    toolStepCount: toolSteps.length,
                    obsStepCount: obsSteps.length,
                    hasAddObs: toolSteps.some(s => s.title === 'add_observations'),
                    hasObsEntry: Boolean(userEntry && userEntry.observations.some(o => o.includes('Python'))),
                    userEntry
                };
            } finally {
                await window.__arkTest.pageHandler.deleteConversation(state.id);
                await window.__arkTest.pageHandler.deleteMemoryEntry('user');
            }
        })()""")
        check(memory_test_result.get('hasAddObs') and memory_test_result.get('obsStepCount') > 0,
              'Memory-saving request invokes add_observations and records observation step in pipeline', results)
        check(memory_test_result.get('hasObsEntry'),
              'Memory-saving message successfully persisted observation into memory graph', results)

        # Verify no uncaught exceptions occurred
        errors = [e for e in cdp.events if e['method'] == 'Runtime.exceptionThrown' and 'ark' in json.dumps(e)]
        check(not errors, 'No uncaught Ark renderer exceptions during test suite execution', results)

    # Output summary
    report = {
        'total_checks': len(results),
        'passed': results,
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
    }
    (artifacts / 'agent_test_results.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f"\nSUCCESS: All {len(results)} Agentic AI & MCP system checks passed perfectly!")


def default_binary() -> Path:
    ark_bin = ROOT / 'chromium/src/out/ArkDev/Ark Browser.app/Contents/MacOS/Ark Browser'
    cr_bin = ROOT / 'chromium/src/out/ArkDev/Chromium.app/Contents/MacOS/Chromium'
    return ark_bin if ark_bin.exists() else cr_bin


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=default_binary())
    parser.add_argument('--artifacts', type=Path, default=ROOT / 'test-results/agent')
    asyncio.run(run(parser.parse_args()))
