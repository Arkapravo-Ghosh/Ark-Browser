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

        # The desktop navigation rail collapses to icons, gives the workspace
        # the reclaimed width, and preserves the preference across reloads.
        await cdp.evaluate(page, "document.querySelector('#rail-toggle').click()")
        await asyncio.sleep(.25)
        collapsed = await cdp.evaluate(page, """(() => ({
            active: document.documentElement.classList.contains('rail-collapsed'),
            railWidth: document.querySelector('.rail').getBoundingClientRect().width,
            workspaceLeft: document.querySelector('.workspace').getBoundingClientRect().left,
            historyHidden: getComputedStyle(document.querySelector('.rail-history')).display === 'none',
            expanded: document.querySelector('#rail-toggle').getAttribute('aria-expanded')
        }))()""")
        print(f"Collapsed rail checks: {collapsed}")
        assert collapsed['active'] and collapsed['railWidth'] <= 74
        assert collapsed['workspaceLeft'] <= 74 and collapsed['historyHidden']
        assert collapsed['expanded'] == 'false'
        await cdp.call('Page.reload', session=page)
        await cdp.wait_for(page, "document.documentElement.classList.contains('rail-collapsed')")
        await cdp.evaluate(page, "document.querySelector('#rail-toggle').click()")
        await asyncio.sleep(.25)
        expanded = await cdp.evaluate(page, "document.querySelector('.rail').getBoundingClientRect().width")
        assert expanded >= 178, f"Expanded rail width unexpected: {expanded}"
        print("PASS 3b: Navigation rail collapses, reclaims space, persists, and expands")

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

        # User messages use the exact same safe Markdown renderer and support
        # language aliases beyond the original JavaScript/Python set.
        user_markdown_checks = await cdp.evaluate(page, r"""(() => {
            const { renderMessageBubble } = window.__arkTest;
            const shortUserBubble = renderMessageBubble('user', 'Hi');
            const userBubble = renderMessageBubble('user',
                '```csharp\npublic record User(string Name);\n```\n\n```java\npublic final class Ark {}\n```\n\n```sql\nSELECT * FROM models;\n```');
            const blocks = userBubble.querySelectorAll('.md-code-block');
            return {
                blockCount: blocks.length,
                hasKeywords: userBubble.querySelectorAll('.tok-keyword').length >= 3,
                csharpLabel: blocks[0]?.querySelector('.md-code-lang')?.textContent,
                javaLabel: blocks[1]?.querySelector('.md-code-lang')?.textContent,
                sqlLabel: blocks[2]?.querySelector('.md-code-lang')?.textContent,
                hasCopy: userBubble.querySelectorAll('.md-copy-btn').length === 3,
                bubbleWidth: userBubble.closest('.message-user')?.getBoundingClientRect().width,
                contentWidth: userBubble.getBoundingClientRect().width,
                shortBubbleWidth: shortUserBubble.getBoundingClientRect().width,
            };
        })()""")
        assert user_markdown_checks['blockCount'] == 3, "User Markdown did not render all fenced blocks"
        assert user_markdown_checks['hasKeywords'], "C#, Java, or SQL keyword was not highlighted"
        assert (user_markdown_checks['csharpLabel'], user_markdown_checks['javaLabel'], user_markdown_checks['sqlLabel']) == ('csharp', 'java', 'sql'), "Language labels changed unexpectedly"
        assert user_markdown_checks['hasCopy'], "User code blocks are missing copy controls"
        assert user_markdown_checks['bubbleWidth'] <= user_markdown_checks['contentWidth'] + 1, "User message wrapper is wider than its content"
        assert user_markdown_checks['shortBubbleWidth'] < 80, "Short user bubble still has a forced minimum width"
        print("PASS 7b: User messages render Markdown, broad syntax highlighting, and content-sized bubbles")

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

        # Exercise both local backends in one conversation. The conversation
        # ID must remain stable while the runtime process changes.
        switch_checks = await cdp.evaluate(page, """(async () => {
            const mlx = 'local:mlx:llama-3.2-11b-vision-instruct';
            const gguf = 'local:huggingface:google/gemma-4-12B-it-qat-q4_0-gguf@29d097773436b69ff9feafd636ab4cf873786537:Q4_0';
            const selectModel = async (model) => {
                localStorage.setItem('ark_selected_model', model);
                const menu = document.querySelector('#composer-model-menu');
                menu.querySelector('[data-model-value="' + model + '"]').click();
                await new Promise(resolve => setTimeout(resolve, 100));
                document.querySelector('#draft').value = `backend switch ${model}`;
                await window.__arkTest.sendMessage();
            };
            await selectModel(gguf);
            const afterGemma = window.__arkTest.getCurrentMessages().length;
            await selectModel(mlx);
            const afterLlama = window.__arkTest.getCurrentMessages().length;
            await selectModel(gguf);
            const messages = window.__arkTest.getCurrentMessages();
            const ids = new Set(messages.map(message => message.conversationId));
            return {
                afterGemma,
                afterLlama,
                finalCount: messages.length,
                conversationCount: ids.size,
                backends: messages.filter(message => message.role === 'assistant')
                    .slice(-3).map(message => message.modelName)
            };
        })()""")
        print(f"Backend switch checks: {switch_checks}")
        assert switch_checks['afterGemma'] > title_checks['msgCount']
        assert switch_checks['afterLlama'] > switch_checks['afterGemma']
        assert switch_checks['finalCount'] > switch_checks['afterLlama']
        assert switch_checks['conversationCount'] == 1
        assert switch_checks['backends'] == [
            'local:huggingface:google/gemma-4-12B-it-qat-q4_0-gguf@29d097773436b69ff9feafd636ab4cf873786537:Q4_0',
            'local:mlx:llama-3.2-11b-vision-instruct',
            'local:huggingface:google/gemma-4-12B-it-qat-q4_0-gguf@29d097773436b69ff9feafd636ab4cf873786537:Q4_0'
        ]
        print("PASS 10b: Gemma -> Llama -> Gemma completed in one conversation")

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
        model_manager_check = await cdp.evaluate(page, """(async () => {
            const {PageHandler} = await import('./ark.mojom-webui.js');
            const {models} = await PageHandler.getRemote().getInstalledLocalModels();
            return {
                apiCount: models.length,
                cardCount: document.querySelectorAll('.installed-model-card').length,
                hasArkNotice: !!document.querySelector('#ark-notice-dialog'),
                hasArkDeleteDialog: !!document.querySelector('#model-delete-dialog'),
                nativeAlertReferences: document.documentElement.innerHTML.includes('chrome://ark-chat says')
            };
        })()""")
        assert model_manager_check['apiCount'] == model_manager_check['cardCount']
        assert model_manager_check['hasArkNotice'] and model_manager_check['hasArkDeleteDialog']
        assert not model_manager_check['nativeAlertReferences']
        print("PASS 15: Installed-model API, cards, and Ark-native dialogs are wired")
        models_screenshot_path = artifacts / 'models_revamp_verified.png'
        await cdp.screenshot(page, models_screenshot_path, 1440, 900)
        print(f"PASS 16: Models manager page verified and captured at {models_screenshot_path}")

        rail_state = await cdp.evaluate(page, """(async () => {
            const {PageHandler} = await import('./ark.mojom-webui.js');
            const handler = PageHandler.getRemote();
            const before = (await handler.getConversations()).conversations.length;
            const newChat = document.querySelector('#new-chat');
            newChat.click();
            newChat.click();
            await new Promise(resolve => setTimeout(resolve, 100));
            const after = (await handler.getConversations()).conversations.length;
            return {
                unchanged: before === after,
                hasChatRailLink: !!document.querySelector('nav a[data-route="chat"]'),
                searchLabel: document.querySelector('nav a[data-route="home"] span')?.textContent,
                emptyWorkspace: document.querySelector('#chat-messages').children.length === 0 &&
                    !document.querySelector('#chat-empty').hidden
            };
        })()""")
        assert rail_state['unchanged'] and not rail_state['hasChatRailLink']
        assert rail_state['searchLabel'] == 'Search' and rail_state['emptyWorkspace']
        print("PASS 17: New chat stays transient, duplicate Chat rail action is removed, and web navigation is labeled Search")

        route_state = await cdp.evaluate(page, """(async () => {
            const clickRoute = async (selector, hash) => {
                document.querySelector(selector).click();
                const route = hash.slice(1);
                for (let i = 0; i < 30 && (location.hash !== hash ||
                    !document.querySelector(`[data-route="${route}"][aria-current="page"]`)); i++) {
                    await new Promise(resolve => setTimeout(resolve, 20));
                }
            };
            await clickRoute('nav a[data-route="home"]', '#home');
            const search = {
                route: location.hash,
                activeRoute: document.querySelector('[data-route][aria-current="page"]')?.dataset.route,
                activeChats: document.querySelectorAll('.conversation-item.active').length
            };
            await clickRoute('nav a[data-route="models"]', '#models');
            return {
                search,
                models: {
                    route: location.hash,
                    activeRoute: document.querySelector('[data-route][aria-current="page"]')?.dataset.route,
                    activeChats: document.querySelectorAll('.conversation-item.active').length
                }
            };
        })()""")
        assert rail_state['searchLabel'] == 'Search'
        assert route_state['search']['activeRoute'] == 'home'
        assert route_state['models']['activeRoute'] == 'models'
        assert route_state['search']['activeChats'] == 0 and route_state['models']['activeChats'] == 0
        print("PASS 18: Search and Models own the active rail state after leaving a chat")

        enter_result = await cdp.evaluate(page, """(async () => {
            document.querySelector('#new-chat').click();
            const draft = document.querySelector('#draft');
            draft.value = 'Explain the causes of tides';
            draft.dispatchEvent(new Event('input', {bubbles: true}));
            draft.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
            for (let i = 0; i < 600; i++) {
                const messages = window.__arkTest.getCurrentMessages();
                const title = document.querySelector('.conversation-item-title')?.textContent || '';
                if (messages.length >= 2 && title && title !== 'New conversation') break;
                await new Promise(resolve => setTimeout(resolve, 100));
            }
            const messages = window.__arkTest.getCurrentMessages();
            const visible = Array.from(
                document.querySelectorAll('#chat-messages > .message'));
            const tail = visible.slice(-2);
            const assistant = tail.find(node =>
                node.classList.contains('message-assistant'));
            const pipeline = assistant?.querySelector('.agent-pipeline');
            const bubble = assistant?.querySelector('.message-bubble');
            return {
                userMessages: messages.filter(m => m.role === 'user').length,
                assistantMessages: messages.filter(m => m.role === 'assistant').length,
                visibleUserBubbles: document.querySelectorAll('.message-user').length,
                visibleAssistantBubbles: document.querySelectorAll('.message-assistant').length,
                tailRoles: tail.map(node => node.classList.contains('message-user') ?
                    'user' : node.classList.contains('message-assistant') ?
                    'assistant' : 'other'),
                generatingPlaceholders: document.querySelectorAll(
                    '.message-bubble[data-generation-conversation-id]').length,
                pipelineOwnedByAssistant: Boolean(pipeline &&
                    pipeline.closest('.message-assistant') === assistant),
                pipelineBeforeAnswer: Boolean(pipeline && bubble &&
                    (pipeline.compareDocumentPosition(bubble) &
                        Node.DOCUMENT_POSITION_FOLLOWING))
            };
        })()""")
        assert enter_result['userMessages'] == 1 and enter_result['assistantMessages'] == 1
        assert enter_result['visibleUserBubbles'] == 1 and enter_result['visibleAssistantBubbles'] == 1
        assert enter_result['tailRoles'] == ['user', 'assistant'], enter_result
        assert enter_result['generatingPlaceholders'] == 0, enter_result
        assert enter_result['pipelineOwnedByAssistant'] and enter_result['pipelineBeforeAnswer'], enter_result
        await cdp.screenshot(page, artifacts / '20_message_pipeline_order.png')
        print("PASS 19: User message, owned agent pipeline, and assistant response remain in strict turn order")

    print("\nALL 16 VERIFICATION CHECKS PASSED PERFECTLY!")

if __name__ == '__main__':
    asyncio.run(main())
