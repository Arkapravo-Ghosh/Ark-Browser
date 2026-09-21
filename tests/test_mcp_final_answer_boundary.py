#!/usr/bin/env python3
"""Live CDP regression for generic MCP final-answer isolation."""

import argparse
import asyncio
import json
from pathlib import Path

from agent_test import browser, default_binary, preserved_file


ROOT = Path(__file__).resolve().parents[1]
PROMPT = (
    'Use the calculate_magic_multiplier tool with a=6 and b=7, then tell me '
    'the result in one concise sentence.'
)


async def run(args):
    artifacts = args.artifacts.resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    mcp_config = Path.home() / '.arkbrowser' / 'mcp' / 'servers.json'
    custom_script = ROOT / 'tests' / 'test_custom_mcp_server.cjs'

    async with preserved_file(mcp_config), browser(
            args.binary.resolve(), artifacts) as cdp:
        page = await cdp.first_page()
        await cdp.navigate(page, 'ark://ark-chat/#chat')
        await cdp.wait_for(page, 'Boolean(window.__arkTest)')

        result = await cdp.evaluate(page, f"""(async () => {{
            await window.__arkTest.pageHandler.deleteMcpServer(
                'final_answer_boundary_test');
            const {{success}} =
                await window.__arkTest.pageHandler.addOrUpdateMcpServer({{
                    id: 'final_answer_boundary_test',
                    name: 'Generic Calculation MCP',
                    description: 'Local generic MCP final-answer boundary test',
                    transportType: 'stdio',
                    commandOrUrl: 'node',
                    args: [{json.dumps(str(custom_script))}],
                    enabled: true,
                    isPreinstalled: false,
                    policy: 'auto_allow',
                    tools: []
                }});
            if (!success) throw new Error('Could not add test MCP server');
            const {{state}} = await window.__arkTest.pageHandler.createConversation(
                'local:mlx:llama-3.2-11b-vision-instruct');
            try {{
                const {{response}} =
                    await window.__arkTest.pageHandler.sendAgentPrompt({{
                        conversationId: state.id,
                        message: {json.dumps(PROMPT)},
                        images: [],
                        providerCredential: null,
                        steeringInstruction: null
                    }});
                return {{
                    success: Boolean(response.success),
                    reply: String(response.response || ''),
                    steps: (response.steps || []).map(step => ({{
                        stepType: String(step.stepType || ''),
                        title: String(step.title || ''),
                        detail: String(step.detail || ''),
                        serverName: String(step.serverName || ''),
                        toolName: String(step.toolName || '')
                    }}))
                }};
            }} finally {{
                await window.__arkTest.pageHandler.deleteConversation(state.id);
                await window.__arkTest.pageHandler.deleteMcpServer(
                    'final_answer_boundary_test');
            }}
        }})()""")

        (artifacts / 'response.json').write_text(
            json.dumps(result, indent=2) + '\n')
        assert result and result.get('success'), result
        steps = result.get('steps', [])
        calls = [step for step in steps
                 if step.get('stepType') == 'tool_call' and
                 step.get('toolName') == 'calculate_magic_multiplier']
        assert calls, result
        observations = [step for step in steps
                        if step.get('stepType') == 'observation' and
                        step.get('toolName') == 'calculate_magic_multiplier']
        assert observations and 'MAGIC-42' in observations[-1]['detail'], result

        answer = result.get('reply', '').strip()
        lowered = answer.lower()
        assert answer and '42' in answer, answer
        for forbidden in (
                '<final_answer>', '</final_answer>', '<think>', '</think>',
                '<thought>', '</thought>', "the user's request",
                'the user is asking', 'we need to answer', 'analysis:',
                'reasoning:', 'answer synthesis'):
            assert forbidden not in lowered, answer

        ui = await cdp.evaluate(page, f"""(() => {{
            const steps = {json.dumps(steps)};
            const payload = JSON.stringify(steps.map(step => ({{
                step_type: step.stepType,
                title: step.title,
                detail: step.detail,
                server_name: step.serverName,
                tool_name: step.toolName
            }})));
            window.__arkTest.renderMessageBubble(
                'assistant', `<!--ARK_PIPELINE:${{payload}}-->\\n` +
                    {json.dumps(answer)},
                'Llama 3.2 11B Vision Instruct (Local)', Date.now());
            const pipelines = Array.from(document.querySelectorAll('.agent-pipeline'));
            const pipeline = pipelines[pipelines.length - 1];
            pipeline?.querySelector('.pipeline-header')?.click();
            const message = pipeline?.closest('.message');
            const thoughtRows = Array.from(
                pipeline?.querySelectorAll('.step-detail') || []).filter(detail =>
                    detail.querySelector('summary')?.textContent === 'View thought');
            return {{
                bubbleText: message?.querySelector('.message-bubble')?.textContent?.trim() || '',
                thoughtCount: thoughtRows.length,
                thoughtText: thoughtRows.map(row =>
                    row.querySelector('.step-detail-body')?.textContent?.trim() || '')
            }};
        }})()""")
        assert ui['bubbleText'] == answer, ui
        assert "The user's request" not in ui['bubbleText'], ui
        await asyncio.sleep(.5)
        await cdp.screenshot(page, artifacts / 'generic_mcp_final_answer.png')

        print('PASS: generic custom MCP tool executed and returned MAGIC-42')
        print('PASS: model synthesis and answer tags did not leak into the chat bubble')
        print(f'PASS: {ui["thoughtCount"]} synthesis thought row(s) remain in activity')
        print(f'RESPONSE: {answer}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, default=default_binary())
    parser.add_argument(
        '--artifacts', type=Path,
        default=ROOT / 'test-results' / 'mcp-final-answer-boundary')
    asyncio.run(run(parser.parse_args()))


if __name__ == '__main__':
    main()
