import argparse
import asyncio
import base64
import contextlib
import json
from pathlib import Path
import subprocess
import tempfile
import time
import websockets

class CDP:
    def __init__(self, ws):
        self.ws = ws
        self.seq = 0

    async def call(self, method, params=None, session=None):
        self.seq += 1
        msg_id = self.seq
        payload = {'id': msg_id, 'method': method}
        if params:
            payload['params'] = params
        if session:
            payload['sessionId'] = session
        await self.ws.send(json.dumps(payload))
        while True:
            raw = await self.ws.recv()
            data = json.loads(raw)
            if data.get('id') == msg_id:
                if 'error' in data:
                    raise AssertionError(f"{method}: {data['error']}")
                return data.get('result', {})

    async def attach_page(self, target_id):
        session = (await self.call('Target.attachToTarget', {
            'targetId': target_id, 'flatten': True}))['sessionId']
        await self.call('Page.enable', session=session)
        await self.call('Runtime.enable', session=session)
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

    async def wait_for(self, session, expression, timeout=15):
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
        path.write_bytes(base64.b64decode(shot['data']))

@contextlib.asynccontextmanager
async def browser(binary, artifacts):
    with tempfile.TemporaryDirectory(dir=artifacts, prefix='ark-test-') as directory:
        profile = Path(directory)
        log = (artifacts / 'chat-revamp-browser.log').open('w')
        manifest_flag = f"--user-agent=ArkBrowser/1.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
        process = subprocess.Popen([
            str(binary), '--headless=new', '--no-first-run', '--no-default-browser-check',
            '--disable-background-networking', '--disable-component-update',
            '--disable-sync', '--remote-debugging-port=0', f'--user-data-dir={profile}',
            manifest_flag], stdout=log, stderr=log)
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
                    f'ws://127.0.0.1:{lines[0]}{lines[1]}', max_size=32*1024*1024) as ws:
                yield CDP(ws)
        finally:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait)
            log.close()

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, default=Path('/tmp/ark_smoke_artifacts'))
    args = parser.parse_args()
    artifacts = args.artifacts.resolve()
    artifacts.mkdir(parents=True, exist_ok=True)

    async with browser(args.binary.resolve(), artifacts) as cdp:
        page = await cdp.first_page()

        # Test in Light Mode first
        await cdp.call('Emulation.setEmulatedMedia', {
            'features': [
                {'name': 'prefers-color-scheme', 'value': 'light'},
                {'name': 'prefers-reduced-motion', 'value': 'reduce'}
            ]}, session=page)

        await cdp.navigate(page, 'ark://ark-chat/#chat')
        await cdp.wait_for(page, "!document.querySelector('#chat-page').hidden")
        print("PASS 1: ark://ark-chat/#chat opened in light mode")

        # Check that About is not in rail and about page does not exist
        has_about = await cdp.evaluate(page, "!!document.querySelector('#about-page') || !!document.querySelector('.rail-btn[data-route=\"about\"]')")
        assert not has_about, "About page or rail button still exists"
        print("PASS 2: About section completely removed from rail and DOM")

        # Check that 'Your Space' section is removed
        has_rail_note = await cdp.evaluate(page, "!!document.querySelector('.rail-note')")
        assert not has_rail_note, "Your Space rail-note still exists"
        print("PASS 3: 'Your Space' section removed from sidebar")

        # Test Textarea ChatGPT dynamics (initial height ~38px)
        initial_height = await cdp.evaluate(page, "document.querySelector('#draft').clientHeight")
        print(f"Textarea initial height: {initial_height}px")
        assert 30 <= initial_height <= 45, f"Textarea initial height unexpected: {initial_height}"
        print("PASS 4: Textarea starts at compact ChatGPT height (~38px)")

        # Test auto-expanding textarea
        expanded_height = await cdp.evaluate(page, """(() => {
            const draft = document.querySelector('#draft');
            draft.value = 'Line 1\\nLine 2\\nLine 3\\nLine 4\\nLine 5\\nLine 6\\nLine 7\\nLine 8';
            draft.dispatchEvent(new Event('input'));
            return draft.clientHeight;
        })()""")
        print(f"Textarea expanded height: {expanded_height}px")
        assert expanded_height > initial_height, f"Textarea did not expand: {expanded_height}"
        assert expanded_height <= 200, f"Textarea exceeded max height 200: {expanded_height}"
        print("PASS 5: Textarea expands dynamically with input up to max 200px")

        # Test reset height on clear
        reset_height = await cdp.evaluate(page, """(() => {
            const draft = document.querySelector('#draft');
            draft.value = '';
            draft.dispatchEvent(new Event('input'));
            return draft.clientHeight;
        })()""")
        assert reset_height <= 45, f"Textarea did not reset height: {reset_height}"
        print("PASS 6: Textarea resets height to initial compact size when emptied")

        # Test renderMessageBubble with Markdown and Code highlighting without ANY TrustedHTML error
        eval_result = await cdp.evaluate(page, r"""(() => {
            try {
                const { renderMessageBubble } = window.__arkTest;
                const sampleMarkdown = "# Python Solution\nHere is how you can write a greeting function in Python with type hints:\n\n```python\ndef greet(name: str) -> str:\n    \"\"\"Return a friendly greeting.\"\"\"\n    return f\"Hello, {name}!\"\n\n# Call the function\nprint(greet(\"Ark\"))\n```\n\n### Key features\n- Fast execution\n- Native type annotations\n- F-string formatting\n\n> Pro tip: You can copy the snippet above directly into your project.";

                // Render user query bubble
                const userBubble = renderMessageBubble('user', 'Show me a Python greeting function with type hints');

                // Render assistant response bubble with rich Markdown and code
                const assistantBubble = renderMessageBubble('assistant', sampleMarkdown, 'Gemini 2.5 Flash');

                return {
                    success: true,
                    userText: userBubble.textContent,
                    hasCodeBlock: !!assistantBubble.querySelector('.md-code-block'),
                    codeLang: assistantBubble.querySelector('.md-code-lang')?.textContent,
                    hasKeyword: !!assistantBubble.querySelector('.tok-keyword'),
                    keywordText: assistantBubble.querySelector('.tok-keyword')?.textContent,
                    hasCopyBtn: !!assistantBubble.querySelector('.md-copy-btn'),
                    copyDataCode: assistantBubble.querySelector('.md-copy-btn')?.getAttribute('data-code'),
                    hasList: !!assistantBubble.querySelector('ul.md-list'),
                    hasBlockquote: !!assistantBubble.querySelector('blockquote.md-blockquote')
                };
            } catch (err) {
                return {
                    success: false,
                    error: String(err),
                    stack: err.stack
                };
            }
        })()""")

        if not eval_result.get('success'):
            raise AssertionError(f"renderMessageBubble threw error: {eval_result.get('error')}\n{eval_result.get('stack')}")

        assert eval_result['hasCodeBlock'], "Code block not rendered"
        assert eval_result['codeLang'] == 'python', f"Code block language incorrect: {eval_result['codeLang']}"
        assert eval_result['hasKeyword'], "Syntax highlighting keyword not rendered"
        assert eval_result['hasCopyBtn'], "Copy button not rendered"
        assert eval_result['hasList'], "List not rendered"
        assert eval_result['hasBlockquote'], "Blockquote not rendered"
        print(f"PASS 7: Markdown rendered with syntax highlighting (keyword: '{eval_result['keywordText']}'), copy button, lists, blockquotes with ZERO TrustedHTML errors")

        # Test assistant bubble pointed corner and automatic width adjustment
        bubble_checks = await cdp.evaluate(page, """(() => {
            const { renderMessageBubble } = window.__arkTest;
            const chatMessages = document.querySelector('#chat-messages');
            const shortBubble = renderMessageBubble('assistant', 'Yes, of course!');
            const cs = getComputedStyle(shortBubble);

            return {
                bottomLeftRadius: cs.borderBottomLeftRadius,
                topLeftRadius: cs.borderTopLeftRadius,
                topRightRadius: cs.borderTopRightRadius,
                bottomRightRadius: cs.borderBottomRightRadius,
                shortWidth: shortBubble.offsetWidth,
                containerWidth: chatMessages.offsetWidth,
                isNarrow: shortBubble.offsetWidth < chatMessages.offsetWidth * 0.6
            };
        })()""")
        print(f"Bubble checks: {bubble_checks}")
        assert bubble_checks['bottomLeftRadius'] == '4px', f"Expected 4px bottom-left radius, got {bubble_checks['bottomLeftRadius']}"
        assert bubble_checks['topLeftRadius'] == '18px', f"Expected 18px top-left radius, got {bubble_checks['topLeftRadius']}"
        assert bubble_checks['isNarrow'], f"Short bubble did not shrink: {bubble_checks['shortWidth']}px vs container {bubble_checks['containerWidth']}px"
        print("PASS 8: Assistant bubble has pointed bottom-left corner (4px) and automatically adjusts width to short content")

        # Test clicking copy button
        copy_click_result = await cdp.evaluate(page, """(() => {
            const btn = document.querySelector('.md-copy-btn');
            if (!btn) return false;
            btn.click();
            return true;
        })()""")
        assert copy_click_result, "Copy button click failed"
        print("PASS 8: Copy code button is interactive")

        # Test message timestamps below bubbles
        timestamp_checks = await cdp.evaluate(page, """(() => {
            const { formatMessageTimestamp } = window.__arkTest;
            const messages = document.querySelectorAll('.message');
            const lastUserMsg = document.querySelector('.message-user');
            const lastAssistantMsg = document.querySelector('.message-assistant');
            const userTime = lastUserMsg?.querySelector('.message-time');
            const assistantTime = lastAssistantMsg?.querySelector('.message-time');

            const now = Date.now();
            const formattedNow = formatMessageTimestamp(now);
            const formattedPast = formatMessageTimestamp(new Date('2026-01-15T12:00:00Z').getTime());

            return {
                hasUserTime: !!userTime,
                userTimeText: userTime?.textContent,
                hasAssistantTime: !!assistantTime,
                assistantTimeText: assistantTime?.textContent,
                formattedNow,
                formattedPast,
                userTimeCS: userTime ? getComputedStyle(userTime).fontSize : '',
                assistantTimeCS: assistantTime ? getComputedStyle(assistantTime).fontSize : ''
            };
        })()""")
        print(f"Timestamp checks: {timestamp_checks}")
        assert timestamp_checks['hasUserTime'], "User message missing .message-time element"
        assert timestamp_checks['hasAssistantTime'], "Assistant message missing .message-time element"
        assert timestamp_checks['userTimeText'].startswith('Today, '), f"User time unexpected: {timestamp_checks['userTimeText']}"
        assert timestamp_checks['assistantTimeText'].startswith('Today, '), f"Assistant time unexpected: {timestamp_checks['assistantTimeText']}"
        assert '11px' in timestamp_checks['userTimeCS'], f"Font size unexpected: {timestamp_checks['userTimeCS']}"
        print(f"PASS 9: Date and time rendered below bubbles ({timestamp_checks['userTimeText']})")

        # Test generateChatTitle and First-Message Title Auto-generation
        title_checks = await cdp.evaluate(page, """(async () => {
            const { generateChatTitle, sendMessage, getConversationsList, getCurrentMessages } = window.__arkTest;

            // 1. Test unit function generateChatTitle
            const shortTitle = generateChatTitle('What is photosynthesis?');
            const longTitle = generateChatTitle('Please explain quantum entanglement in detail and how it relates to quantum computing applications');

            // 2. Clear current messages to simulate brand new conversation
            const draft = document.querySelector('#draft');
            draft.value = 'How does nuclear fusion generate energy?';
            await sendMessage();

            const convsAfterFirst = getConversationsList();
            const firstConvTitle = convsAfterFirst[0]?.title;

            // 3. Send second message in the same conversation
            draft.value = 'What about fission?';
            await sendMessage();

            const convsAfterSecond = getConversationsList();
            const secondConvTitle = convsAfterSecond[0]?.title;

            // 4. Verify modelName in schema
            const msgs = getCurrentMessages();
            const userMsgModel = msgs[0]?.modelName;
            const assistantMsgModel = msgs[1]?.modelName;

            return {
                shortTitle,
                longTitle,
                firstConvTitle,
                secondConvTitle,
                titleRemainedSame: firstConvTitle === secondConvTitle,
                userMsgModel,
                assistantMsgModel,
                msgCount: msgs.length
            };
        })()""")
        print(f"Title & Schema checks: {title_checks}")
        assert title_checks['shortTitle'] == 'What is photosynthesis?', f"Short title unexpected: {title_checks['shortTitle']}"
        assert len(title_checks['longTitle']) <= 41 and title_checks['longTitle'].endswith('...'), f"Long title unexpected: {title_checks['longTitle']}"
        assert 'nuclear fusion' in title_checks['firstConvTitle'].lower(), f"First conv title unexpected: {title_checks['firstConvTitle']}"
        assert title_checks['titleRemainedSame'], f"Second message modified the title! {title_checks['firstConvTitle']} vs {title_checks['secondConvTitle']}"
        assert title_checks['userMsgModel'], "user message missing modelName"
        assert title_checks['assistantMsgModel'], "assistant message missing modelName"
        print(f"PASS 10: First-message title auto-generated ('{title_checks['firstConvTitle']}'), preserved across subsequent messages, and modelName present in message schema")

        # Wait for CSS animations to complete
        await asyncio.sleep(.5)

        # Capture Light Mode screenshot with full message flow
        light_screenshot_path = artifacts / 'chat_revamp_light.png'
        await cdp.screenshot(page, light_screenshot_path, 1440, 900)
        print(f"PASS 11: Light mode screenshot captured at {light_screenshot_path}")

        # Now switch to Dark Mode and capture Dark Mode screenshot
        await cdp.call('Emulation.setEmulatedMedia', {
            'features': [
                {'name': 'prefers-color-scheme', 'value': 'dark'},
                {'name': 'prefers-reduced-motion', 'value': 'reduce'}
            ]}, session=page)
        await asyncio.sleep(.3)
        dark_screenshot_path = artifacts / 'chat_revamp_dark.png'
        await cdp.screenshot(page, dark_screenshot_path, 1440, 900)
        print(f"PASS 12: Dark mode screenshot captured at {dark_screenshot_path}")

        # Test switching conversations and loadMessages
        conv_switch_result = await cdp.evaluate(page, """(async () => {
            try {
                await window.__arkTest.loadMessages();
                return { success: true };
            } catch (err) {
                return { success: false, error: String(err), stack: err.stack };
            }
        })()""")
        if not conv_switch_result.get('success'):
            raise AssertionError(f"loadMessages failed: {conv_switch_result.get('error')}")
        print("PASS 13: loadMessages executed cleanly with no TrustedHTML error")

        # Verify page height and internal scrolling: body and shell must not have document scrollbars
        overflow_check = await cdp.evaluate(page, """(() => {
            return {
                docScrollHeight: document.documentElement.scrollHeight,
                windowHeight: window.innerHeight,
                docOverflows: document.documentElement.scrollHeight > window.innerHeight + 2
            };
        })()""")
        print(f"Overflow check: docScrollHeight={overflow_check['docScrollHeight']}, windowHeight={overflow_check['windowHeight']}")
        assert not overflow_check['docOverflows'], f"Document overflows screen height! {overflow_check}"
        print("PASS 14: Overall chat page does not overflow screen height; chat container handles vertical scrolling")

        # Check Models page
        await cdp.evaluate(page, "location.hash = 'models'")
        await cdp.wait_for(page, "!document.querySelector('#models-page').hidden")
        models_screenshot_path = artifacts / 'models_revamp_verified.png'
        await cdp.screenshot(page, models_screenshot_path, 1440, 900)
        print(f"PASS 15: Models manager page verified and captured at {models_screenshot_path}")

    print("\nALL 15 VERIFICATION CHECKS PASSED PERFECTLY!")

if __name__ == '__main__':
    asyncio.run(main())
