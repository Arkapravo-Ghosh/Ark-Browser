#!/usr/bin/env python3
# Copyright 2026 Arkapravo Ghosh
"""CDP regression for user/assistant ordering and pipeline ownership."""

import argparse
import asyncio
from pathlib import Path

from agent_test import browser, default_binary


ROOT = Path(__file__).resolve().parents[1]


async def run(args):
    artifacts = args.artifacts.resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    async with browser(args.binary.resolve(), artifacts) as cdp:
        page = await cdp.first_page()
        await cdp.navigate(page, 'ark://ark-chat/#chat')
        await cdp.wait_for(page, "Boolean(window.__arkTest)")

        await cdp.evaluate(page, """(() => {
            window.__arkTest.createNewChat();
            const draft = document.querySelector('#draft');
            draft.value = 'Reply with exactly UI_ORDER_OK and nothing else.';
            draft.dispatchEvent(new Event('input', {bubbles: true}));
            window.__arkOrderPromise = window.__arkTest.sendMessage();
            return true;
        })()""")

        await cdp.wait_for(page, """(() => {
            const messages = document.querySelectorAll('#chat-messages > .message');
            return messages.length >= 2 &&
                messages[messages.length - 2].classList.contains('message-user') &&
                messages[messages.length - 1].classList.contains('message-assistant');
        })()""", timeout=60)
        await cdp.wait_for(page, "Boolean(document.querySelector('.message-assistant .agent-pipeline'))", timeout=60)

        active_layout = await cdp.evaluate(page, """(() => {
            const messages = Array.from(document.querySelectorAll(
                '#chat-messages > .message'));
            const tail = messages.slice(-2);
            const assistant = tail[1];
            const pipeline = assistant?.querySelector('.agent-pipeline');
            const bubble = assistant?.querySelector('.message-bubble');
            return {
                roles: tail.map(node => node.classList.contains('message-user') ?
                    'user' : node.classList.contains('message-assistant') ?
                    'assistant' : 'other'),
                assistantCount: document.querySelectorAll(
                    '#chat-messages > .message-assistant').length,
                placeholderCount: document.querySelectorAll(
                    '.message-bubble[data-generation-conversation-id]').length,
                pipelineOwned: Boolean(pipeline &&
                    pipeline.closest('.message-assistant') === assistant),
                pipelineBeforeBubble: Boolean(pipeline && bubble &&
                    (pipeline.compareDocumentPosition(bubble) &
                        Node.DOCUMENT_POSITION_FOLLOWING)),
            };
        })()""")
        assert active_layout['roles'] == ['user', 'assistant'], active_layout
        assert active_layout['assistantCount'] == 1, active_layout
        assert active_layout['placeholderCount'] == 1, active_layout
        assert active_layout['pipelineOwned'], active_layout
        assert active_layout['pipelineBeforeBubble'], active_layout
        await cdp.screenshot(page, artifacts / '01_active_turn_order.png')
        print('PASS: active assistant placeholder stays after its user message')

        await cdp.evaluate(page, "window.__arkOrderPromise")
        await cdp.wait_for(page, """(() =>
            window.__arkTest.getGeneratingConversationIds().length === 0 &&
            window.__arkTest.getCurrentMessages().filter(
                message => message.role === 'assistant').length === 1
        )()""", timeout=240)

        complete_layout = await cdp.evaluate(page, """(() => {
            const messages = Array.from(document.querySelectorAll(
                '#chat-messages > .message'));
            const tail = messages.slice(-2);
            const assistant = tail[1];
            const pipeline = assistant?.querySelector('.agent-pipeline');
            const bubble = assistant?.querySelector('.message-bubble');
            return {
                roles: tail.map(node => node.classList.contains('message-user') ?
                    'user' : node.classList.contains('message-assistant') ?
                    'assistant' : 'other'),
                userCount: document.querySelectorAll(
                    '#chat-messages > .message-user').length,
                assistantCount: document.querySelectorAll(
                    '#chat-messages > .message-assistant').length,
                placeholderCount: document.querySelectorAll(
                    '.message-bubble[data-generation-conversation-id]').length,
                pipelineOwned: Boolean(pipeline &&
                    pipeline.closest('.message-assistant') === assistant),
                pipelineBeforeBubble: Boolean(pipeline && bubble &&
                    (pipeline.compareDocumentPosition(bubble) &
                        Node.DOCUMENT_POSITION_FOLLOWING)),
                answer: bubble?.textContent || '',
            };
        })()""")
        assert complete_layout['roles'] == ['user', 'assistant'], complete_layout
        assert complete_layout['userCount'] == 1, complete_layout
        assert complete_layout['assistantCount'] == 1, complete_layout
        assert complete_layout['placeholderCount'] == 0, complete_layout
        assert complete_layout['pipelineOwned'], complete_layout
        assert complete_layout['pipelineBeforeBubble'], complete_layout
        assert complete_layout['answer'].strip(), complete_layout
        await cdp.screenshot(page, artifacts / '02_completed_turn_order.png')
        print('PASS: completed pipeline and answer remain owned by the following assistant turn')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=default_binary())
    parser.add_argument(
        '--artifacts', type=Path,
        default=ROOT / 'test-results/agent-ui-order')
    asyncio.run(run(parser.parse_args()))
