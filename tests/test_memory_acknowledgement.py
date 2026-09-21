#!/usr/bin/env python3
"""Live CDP regression for precise memory writes and bounded acknowledgements."""

import argparse
import asyncio
import json
from pathlib import Path

from agent_test import browser, default_binary, preserved_file


ROOT = Path(__file__).resolve().parents[1]
PROMPT = (
    'Can you record in your memory that I live in Bengaluru, Karnataka, India '
    'currently but my hometown is in Kolkata, West Bengal, India?'
)
RECALL_PROMPT = 'What do you remember about where I live and my hometown?'


async def run(args):
    artifacts = args.artifacts.resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    memory_file = Path.home() / '.arkbrowser' / 'mcp' / 'memory.jsonl'

    async with preserved_file(memory_file), browser(args.binary.resolve(), artifacts) as cdp:
        page = await cdp.first_page()
        await cdp.navigate(page, 'ark://ark-chat/#chat')
        await cdp.wait_for(page, 'Boolean(window.__arkTest)')
        result = await cdp.evaluate(page, f"""(async () => {{
            const {{state}} = await window.__arkTest.pageHandler.createConversation(
                'local:mlx:llama-3.2-11b-vision-instruct');
            try {{
                const {{response}} = await window.__arkTest.pageHandler.sendAgentPrompt({{
                    conversationId: state.id,
                    message: {json.dumps(PROMPT)},
                    images: [],
                    providerCredential: null,
                    steeringInstruction: null
                }});
                const {{response: recall}} = await window.__arkTest.pageHandler.sendAgentPrompt({{
                    conversationId: state.id,
                    message: {json.dumps(RECALL_PROMPT)},
                    images: [],
                    providerCredential: null,
                    steeringInstruction: null
                }});
                return {{
                    success: response.success,
                    response: response.response,
                    steps: (response.steps || []).map(step => ({{
                        stepType: step.stepType,
                        title: step.title,
                        detail: step.detail,
                        serverName: step.serverName,
                        toolName: step.toolName
                    }})),
                    recallSuccess: recall.success,
                    recallResponse: recall.response,
                    recallSteps: (recall.steps || []).map(step => ({{
                        stepType: step.stepType,
                        title: step.title,
                        detail: step.detail,
                        serverName: step.serverName,
                        toolName: step.toolName
                    }}))
                }};
            }} finally {{
                await window.__arkTest.pageHandler.deleteConversation(state.id);
            }}
        }})()""")

        (artifacts / 'response.json').write_text(
            json.dumps(result, indent=2) + '\n')
        assert result and result.get('success'), result
        calls = [step for step in result.get('steps', [])
                 if step.get('stepType') == 'tool_call' and
                 step.get('toolName') == 'add_observations']
        assert calls, result
        arguments = json.loads(calls[-1]['detail'])
        observations = arguments.get('observations', [])
        assert len(observations) == 1, arguments
        assert 'hometown is in Kolkata' in observations[0], observations
        assert 'lives in Kolkata' not in observations[0], observations

        answer = result.get('response', '').strip()
        lowered = answer.lower()
        assert answer and len(answer) <= 280, answer
        for forbidden in ('hello ark ai', 'i am ark ai', 'based on the model',
                          'code examples', 'technical capabilities'):
            assert forbidden not in lowered, answer
        assert '\n\nanswer:' not in lowered, answer

        recall_answer = result.get('recallResponse', '').strip()
        recall_lowered = recall_answer.lower()
        assert result.get('recallSuccess'), result
        assert 'bengaluru' in recall_lowered and 'kolkata' in recall_lowered, recall_answer
        assert len(recall_answer) <= 400, recall_answer
        assert any(step.get('stepType') == 'tool_call' and
                   step.get('toolName') in ('read_graph', 'search_nodes', 'open_nodes')
                   for step in result.get('recallSteps', [])), result
        for forbidden in ('hello ark ai', 'i am ark ai', 'based on the model',
                          'code examples', 'technical capabilities'):
            assert forbidden not in recall_lowered, recall_answer
        assert '\n\nanswer:' not in recall_lowered, recall_answer

        await cdp.evaluate(page, f"""(() => {{
            const payload = JSON.stringify({json.dumps(result.get('steps', []))});
            const answer = {json.dumps(answer)};
            window.__arkTest.renderMessageBubble(
                'assistant', `<!--ARK_PIPELINE:${{payload}}-->\\n${{answer}}`,
                'Llama 3.2 11B Vision Instruct (Local)', Date.now());
            const pipeline = Array.from(document.querySelectorAll('.agent-pipeline')).pop();
            if (pipeline) pipeline.querySelector('.pipeline-header')?.click();
            window.__arkTest.renderMessageBubble(
                'user', {json.dumps(RECALL_PROMPT)}, '', Date.now());
            const recallPayload = JSON.stringify({json.dumps(result.get('recallSteps', []))});
            const recallAnswer = {json.dumps(recall_answer)};
            window.__arkTest.renderMessageBubble(
                'assistant', `<!--ARK_PIPELINE:${{recallPayload}}-->\\n${{recallAnswer}}`,
                'Llama 3.2 11B Vision Instruct (Local)', Date.now());
        }})()""")
        await cdp.screenshot(page, artifacts / 'memory_acknowledgement.png')
        print('PASS: explicit memory fact preserved without semantic drift')
        print('PASS: post-memory acknowledgement is concise and contains no self-introduction')
        print('PASS: immediate follow-up recall stays grounded without stale assistant text')
        print(f'RESPONSE: {answer}')
        print(f'RECALL: {recall_answer}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, default=default_binary())
    parser.add_argument(
        '--artifacts', type=Path,
        default=ROOT / 'test-results' / 'memory-acknowledgement')
    asyncio.run(run(parser.parse_args()))


if __name__ == '__main__':
    main()
