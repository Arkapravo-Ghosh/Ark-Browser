#!/usr/bin/env python3
"""CDP regression for consistent structured tool input/result payload cards."""

import argparse
import asyncio
import json
from pathlib import Path

from agent_test import browser, default_binary


ROOT = Path(__file__).resolve().parents[1]


async def run(args):
    artifacts = args.artifacts.resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    async with browser(args.binary.resolve(), artifacts) as cdp:
        page = await cdp.first_page()
        await cdp.navigate(page, 'ark://ark-chat/#chat')
        await cdp.wait_for(page, 'Boolean(window.__arkTest)')
        rendering = await cdp.evaluate(page, """(() => {
            const steps = [{
                step_type: 'tool_call',
                title: 'add_observations',
                tool_name: 'add_observations',
                server_name: 'Memory Knowledge Graph',
                detail: '{"entityName":"user","observations":["prefers precise JSON"]}'
            }, {
                step_type: 'observation',
                title: 'Memory updated',
                tool_name: 'add_observations',
                server_name: 'Memory Knowledge Graph',
                detail: JSON.stringify([{
                    name: 'user', entityType: 'person',
                    observations: ['prefers precise JSON']
                }], null, 2)
            }, {
                step_type: 'reasoning',
                title: 'Answer synthesis',
                tool_name: 'answer_synthesis',
                detail: "The user's request is to save a preference. Answer: Saved."
            }];
            const message = `<!--ARK_PIPELINE:${JSON.stringify(steps)}-->\nSaved.`;
            window.__arkTest.renderMessageBubble(
                'assistant', message, 'Llama 3.2 11B Vision Instruct (Local)', Date.now());
            const pipeline = Array.from(document.querySelectorAll('.agent-pipeline')).pop();
            pipeline.querySelector('.pipeline-header').click();
            pipeline.querySelectorAll('.step-detail').forEach(detail => detail.open = true);
            const input = pipeline.querySelector('.tool-args');
            const output = pipeline.querySelector('.tool-result');
            const thought = Array.from(pipeline.querySelectorAll('.step-detail')).find(
                detail => detail.querySelector('summary')?.textContent === 'View thought');
            const messageElement = pipeline.closest('.message');
            const bubbleText = messageElement?.querySelector('.message-bubble')?.textContent?.trim() || '';
            const inputStyle = getComputedStyle(input);
            const outputStyle = getComputedStyle(output);
            return {
                inputText: input.textContent,
                outputText: output.textContent,
                inputClass: input.className,
                outputClass: output.className,
                sameBackground: inputStyle.backgroundColor === outputStyle.backgroundColor,
                sameBorder: inputStyle.border === outputStyle.border,
                samePadding: inputStyle.padding === outputStyle.padding,
                sameFont: inputStyle.fontFamily === outputStyle.fontFamily,
                thoughtSummary: thought?.querySelector('summary')?.textContent || '',
                thoughtText: thought?.querySelector('.step-detail-body')?.textContent?.trim() || '',
                bubbleText
            };
        })()""")
        assert '\n' not in rendering['inputText'], rendering
        assert '\n' not in rendering['outputText'], rendering
        assert json.loads(rendering['outputText'])[0]['name'] == 'user', rendering
        assert 'tool-payload' in rendering['inputClass'], rendering
        assert 'tool-payload' in rendering['outputClass'], rendering
        assert all(rendering[key] for key in (
            'sameBackground', 'sameBorder', 'samePadding', 'sameFont')), rendering
        assert rendering['thoughtSummary'] == 'View thought', rendering
        assert "The user's request" in rendering['thoughtText'], rendering
        assert rendering['bubbleText'] == 'Saved.', rendering
        assert "The user's request" not in rendering['bubbleText'], rendering
        await asyncio.sleep(1)
        await cdp.screenshot(page, artifacts / 'tool_payload_consistency.png')
        (artifacts / 'result.json').write_text(json.dumps(rendering, indent=2) + '\n')
        print('PASS: structured tool input and output use one compact payload-card treatment')
        print('PASS: synthesis notes remain expandable activity and never enter the answer bubble')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, default=default_binary())
    parser.add_argument(
        '--artifacts', type=Path,
        default=ROOT / 'test-results' / 'tool-payload-ui')
    asyncio.run(run(parser.parse_args()))


if __name__ == '__main__':
    main()
