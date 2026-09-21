import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile
import websockets

class CDP:
    def __init__(self, ws):
        self.ws = ws
        self._id = 0

    async def send(self, method, params=None):
        self._id += 1
        call_id = self._id
        await self.ws.send(json.dumps({'id': call_id, 'method': method, 'params': params or {}}))
        while True:
            raw = await self.ws.recv()
            msg = json.loads(raw)
            if msg.get('id') == call_id:
                if 'error' in msg:
                    raise RuntimeError(msg['error']['message'])
                return msg.get('result', {})

    async def evaluate(self, expr):
        res = await self.send('Runtime.evaluate', {'expression': expr, 'awaitPromise': True, 'returnByValue': True})
        result = res.get('result', {})
        if 'value' in result:
            return result['value']
        return result

async def main():
    binary = Path('/Users/arkapravoghosh/Ark-Browser/chromium/src/out/ArkDev/Ark Browser.app/Contents/MacOS/Ark Browser')
    artifacts = Path('/Users/arkapravoghosh/Ark-Browser/test-results/user_flow')
    artifacts.mkdir(parents=True, exist_ok=True)
    log_file = (artifacts / 'browser.log').open('w')

    with tempfile.TemporaryDirectory(dir=artifacts, prefix='ark-test-', ignore_cleanup_errors=True) as profile_dir:
        profile = Path(profile_dir)
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
            'ark://ark-chat/#chat',
        ]
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=log_file)
        log_file.flush()
        try:
            endpoint = profile / 'DevToolsActivePort'
            for _ in range(300):
                if endpoint.exists():
                    break
                if proc.poll() is not None:
                    log_file.flush()
                    log_content = (artifacts / 'browser.log').read_text()
                    raise AssertionError(f"Browser exited prematurely with code {proc.returncode}. Log:\n{log_content}")
                await asyncio.sleep(0.1)
            if not endpoint.exists():
                log_file.flush()
                log_content = (artifacts / 'browser.log').read_text()
                raise AssertionError(f"DevToolsActivePort not found after 30s. Log:\n{log_content}")
            lines = endpoint.read_text().splitlines()
            ws_url = f'ws://127.0.0.1:{lines[0]}{lines[1]}'

            async with websockets.connect(ws_url, max_size=50 * 1024 * 1024) as ws:
                cdp = CDP(ws)
                # Find the Ark Chat target
                targets = await cdp.send('Target.getTargets')
                ark_target = next(t for t in targets['targetInfos'] if t['type'] == 'page')
                session = await cdp.send('Target.attachToTarget', {'targetId': ark_target['targetId'], 'flatten': True})

                # We can evaluate on the page target by sending commands with sessionId
                async def eval_page(expr):
                    call_id = cdp._id + 1
                    cdp._id += 1
                    payload = {
                        'id': call_id,
                        'sessionId': session['sessionId'],
                        'method': 'Runtime.evaluate',
                        'params': {'expression': expr, 'awaitPromise': True, 'returnByValue': True}
                    }
                    await cdp.ws.send(json.dumps(payload))
                    while True:
                        raw = await cdp.ws.recv()
                        msg = json.loads(raw)
                        if msg.get('id') == call_id:
                            if 'error' in msg:
                                raise RuntimeError(msg['error']['message'])
                            result = msg.get('result', {}).get('result', {})
                            return result.get('value')

                await asyncio.sleep(2)

                print("--- 1. Testing simple greeting 'Hello' ---")
                res_hello = await eval_page("""(async () => {
                    const {state} = await window.__arkTest.pageHandler.createConversation('local:mlx:llama-3.2-11b-vision-instruct');
                    try {
                        const {response} = await window.__arkTest.pageHandler.sendAgentPrompt({
                            conversationId: state.id,
                            message: 'Hello',
                            images: [],
                            providerCredential: null,
                            steeringInstruction: null
                        });
                        return {
                            success: response.success,
                            toolSteps: (response.steps || []).filter(s => s.stepType === 'tool_call'),
                            reply: response.response
                        };
                    } finally {
                        await window.__arkTest.pageHandler.deleteConversation(state.id);
                    }
                })()""")
                print("Hello result:", res_hello)
                assert len(res_hello['toolSteps']) == 0, f"Expected 0 tool steps for Hello, got {res_hello['toolSteps']}"
                print("PASS: Hello triggered 0 tool calls")

                print("\n--- 2. Testing self-introduction with question: 'My name is Arkapravo Ghosh, what\\'s yours?' ---")
                res_intro = await eval_page("""(async () => {
                    await window.__arkTest.pageHandler.clearAllMemory();
                    const {state} = await window.__arkTest.pageHandler.createConversation('local:mlx:llama-3.2-11b-vision-instruct');
                    try {
                        const {response} = await window.__arkTest.pageHandler.sendAgentPrompt({
                            conversationId: state.id,
                            message: "My name is Arkapravo Ghosh, what's yours?",
                            images: [],
                            providerCredential: null,
                            steeringInstruction: null
                        });
                        const {entries} = await window.__arkTest.pageHandler.getMemoryEntries();
                        const cleanSteps = (response.steps || []).map(s => ({
                            stepType: String(s.stepType || ''),
                            title: String(s.title || ''),
                            detail: String(s.detail || '')
                        }));
                        const cleanEntries = (entries || []).map(e => ({
                            entityName: String(e.entityName || ''),
                            observations: (e.observations || []).map(o => String(o))
                        }));
                        return {
                            success: Boolean(response.success),
                            steps: cleanSteps,
                            reply: String(response.response || ''),
                            entries: cleanEntries
                        };
                    } finally {
                        await window.__arkTest.pageHandler.deleteConversation(state.id);
                    }
                })()""")
                print("Intro reply:", res_intro.get('reply'))
                print("Intro steps count:", len(res_intro.get('steps', [])))
                for s in res_intro.get('steps', []):
                    print(f"  Step: [{s.get('stepType')}] {s.get('title')}: {s.get('detail')}")

                tool_titles = [s['title'] for s in res_intro.get('steps', []) if s.get('stepType') == 'tool_call']
                print("Tool calls:", tool_titles)
                assert 'add_observations' in tool_titles, f"Expected add_observations in {tool_titles}"
                assert any('sequential' in t.lower() for t in tool_titles), f"Expected sequential thinking in {tool_titles}"

                # Check memory file on disk
                memory_file = Path.home() / '.arkbrowser' / 'mcp' / 'memory.jsonl'
                assert memory_file.exists(), f"Memory file does not exist at {memory_file}"
                mem_content = memory_file.read_text()
                print("Memory file content:\n", mem_content)
                assert 'Arkapravo Ghosh' in mem_content, "Expected Arkapravo Ghosh saved into memory.jsonl"

                intro_reply_lower = res_intro.get('reply', '').lower()
                assert 'ark ai' in intro_reply_lower, f"Expected 'Ark AI' in reply to 'what\\'s yours?': {res_intro.get('reply')}"
                assert 'ark assistant' not in intro_reply_lower, f"Must NOT use 'Ark Assistant': {res_intro.get('reply')}"
                # Assert NO memory update announcements in final response text
                for bad_phrase in ['memory updated', 'updated my memory', 'saved to memory', 'stored in memory', 'added to memory', 'saved to my memory', 'added to my memory', 'updated your memory']:
                    assert bad_phrase not in intro_reply_lower, f"Must NOT announce memory update in text ('{bad_phrase}' found in: {res_intro.get('reply')})"
                print("PASS: Introduction saved to memory, sequential thinking executed, Ark AI introduced without memory update announcement!")

                print("\n--- 2b. Testing model query 'What model are you running on?' ---")
                res_model = await eval_page("""(async () => {
                    const {state} = await window.__arkTest.pageHandler.createConversation('local:mlx:llama-3.2-11b-vision-instruct');
                    try {
                        const {response} = await window.__arkTest.pageHandler.sendAgentPrompt({
                            conversationId: state.id,
                            message: "What model are you running on?",
                            images: [],
                            providerCredential: null,
                            steeringInstruction: null
                        });
                        const cleanSteps = (response.steps || []).map(s => ({
                            stepType: String(s.stepType || ''),
                            title: String(s.title || ''),
                            detail: String(s.detail || '')
                        }));
                        return {
                            success: Boolean(response.success),
                            steps: cleanSteps,
                            reply: String(response.response || '')
                        };
                    } finally {
                        await window.__arkTest.pageHandler.deleteConversation(state.id);
                    }
                })()""")
                print("Model query reply:", res_model.get('reply'))
                model_reply_lower = res_model.get('reply', '').lower()
                assert any(m in model_reply_lower for m in ['llama', 'mlx', 'local']), \
                    f"Expected model/provider info in reply: {res_model.get('reply')}"
                model_tools = [s['title'] for s in res_model.get('steps', []) if s.get('stepType') == 'tool_call']
                assert 'add_observations' not in model_tools and 'read_graph' not in model_tools, \
                    f"Model question should not touch memory: {model_tools}"
                print("PASS: Model inquiry answered accurately with model info without touching memory!")

                print("\n--- 3. Testing memory query 'What is my name?' ---")
                res_query = await eval_page("""(async () => {
                    const {state} = await window.__arkTest.pageHandler.createConversation('local:mlx:llama-3.2-11b-vision-instruct');
                    try {
                        const {response} = await window.__arkTest.pageHandler.sendAgentPrompt({
                            conversationId: state.id,
                            message: "What is my name?",
                            images: [],
                            providerCredential: null,
                            steeringInstruction: null
                        });
                        const cleanSteps = (response.steps || []).map(s => ({
                            stepType: String(s.stepType || ''),
                            title: String(s.title || ''),
                            detail: String(s.detail || '')
                        }));
                        return {
                            success: Boolean(response.success),
                            steps: cleanSteps,
                            reply: String(response.response || '')
                        };
                    } finally {
                        await window.__arkTest.pageHandler.deleteConversation(state.id);
                    }
                })()""")
                print("Query reply:", res_query.get('reply'))
                print("Query steps count:", len(res_query.get('steps', [])))
                for s in res_query.get('steps', []):
                    print(f"  Query Step: [{s.get('stepType')}] {s.get('title')}: {s.get('detail')}")
                query_tools = [s['title'] for s in res_query.get('steps', []) if s.get('stepType') == 'tool_call']
                print("Query tool calls:", query_tools)
                assert 'read_graph' in query_tools or 'search_nodes' in query_tools, f"Expected read_graph in {query_tools}"
                assert 'Arkapravo' in res_query.get('reply', ''), f"Expected Arkapravo in reply: {res_query.get('reply')}"
                print("PASS: Memory query read from graph and replied correctly!")

                print("\n--- 3a. Testing pipeline header thought and tool count formatting ---")
                header_format_test = await eval_page("""(() => {
                    const parent = document.createElement('div');
                    const bubble = document.createElement('div');
                    parent.appendChild(bubble);

                    // Case 1: 1 sequential thought + 1 tool (e.g. read_graph + sequentialthinking)
                    const mixedSteps = [
                        {stepType: 'tool_call', title: 'read_graph', detail: '{"query": "name"}', elapsedMs: 120},
                        {stepType: 'observation', title: 'Graph result', detail: 'Found name', elapsedMs: 0},
                        {stepType: 'tool_call', title: 'sequentialthinking', detail: '{"thought": "Formulating answer..."}', elapsedMs: 250},
                        {stepType: 'observation', title: 'Completed thought 1/1', detail: 'Done', elapsedMs: 0}
                    ];
                    window.__arkTest.renderAgentPipeline(parent, bubble, mixedSteps, undefined, false);
                    const headerMixed = parent.querySelector('.pipeline-summary')?.textContent || '';

                    // Case 2: Only sequential thoughts (e.g. 2 thoughts)
                    const thoughtOnlySteps = [
                        {stepType: 'tool_call', title: 'sequential_thinking', detail: '{"thought": "Thought 1"}', elapsedMs: 100},
                        {stepType: 'tool_call', title: 'sequential_thinking', detail: '{"thought": "Thought 2"}', elapsedMs: 100}
                    ];
                    window.__arkTest.renderAgentPipeline(parent, bubble, thoughtOnlySteps, undefined, false);
                    const headerThoughts = parent.querySelector('.pipeline-summary')?.textContent || '';

                    // Case 3: Only tools (e.g. 2 tools)
                    const toolOnlySteps = [
                        {stepType: 'tool_call', title: 'read_graph', detail: '{}', elapsedMs: 100},
                        {stepType: 'tool_call', title: 'search_nodes', detail: '{}', elapsedMs: 100}
                    ];
                    window.__arkTest.renderAgentPipeline(parent, bubble, toolOnlySteps, undefined, false);
                    const headerTools = parent.querySelector('.pipeline-summary')?.textContent || '';

                    return {
                        headerMixed,
                        headerThoughts,
                        headerTools
                    };
                })()""")
                print("Header format test:", header_format_test)
                assert header_format_test['headerMixed'] == '1 thought · 1 tool', \
                    f"Expected '1 thought · 1 tool', got '{header_format_test['headerMixed']}'"
                assert header_format_test['headerThoughts'] == '2 thoughts', \
                    f"Expected '2 thoughts', got '{header_format_test['headerThoughts']}'"
                assert header_format_test['headerTools'] == '2 tools', \
                    f"Expected '2 tools', got '{header_format_test['headerTools']}'"
                print("PASS: Pipeline summary correctly counts thoughts and tools separately ('1 thought · 1 tool')!")

                print("\n--- 3a2. Testing multi-question query from user screenshot ---")
                res_multi = await eval_page("""(async () => {
                    const {state} = await window.__arkTest.pageHandler.createConversation('local:mlx:llama-3.2-11b-vision-instruct');
                    try {
                        const {response} = await window.__arkTest.pageHandler.sendAgentPrompt({
                            conversationId: state.id,
                            message: "Can you tell me my name? Also, what's your name? Which model are you based on? What can you do? Can you reverse a string in python?",
                            images: [],
                            providerCredential: null,
                            steeringInstruction: null
                        });
                        const cleanSteps = (response.steps || []).map(s => ({
                            stepType: String(s.stepType || ''),
                            title: String(s.title || ''),
                            detail: String(s.detail || '')
                        }));
                        return {
                            success: Boolean(response.success),
                            steps: cleanSteps,
                            reply: String(response.response || '')
                        };
                    } finally {
                        await window.__arkTest.pageHandler.deleteConversation(state.id);
                    }
                })()""")
                print("Multi-question reply:\n", res_multi.get('reply'))
                multi_reply_lower = res_multi.get('reply', '').lower()
                multi_tools = [s['title'] for s in res_multi.get('steps', []) if s.get('stepType') == 'tool_call']
                print("Multi-question tool calls:", multi_tools)

                # Tool usage assertions
                assert 'read_graph' in multi_tools or 'search_nodes' in multi_tools, \
                    f"Expected memory read tool in {multi_tools}"
                assert any('sequential' in t.lower() for t in multi_tools), \
                    f"Expected sequential thinking in {multi_tools}"

                # Response completeness assertions:
                # 1. User's name
                assert any(name in multi_reply_lower for name in ['arkapravo', 'ghosh']), \
                    f"Multi-question reply must state user's name (Arkapravo Ghosh): {res_multi.get('reply')}"
                # 2. Assistant's name
                assert 'ark ai' in multi_reply_lower, \
                    f"Multi-question reply must state assistant's name (Ark AI): {res_multi.get('reply')}"
                assert 'ark assistant' not in multi_reply_lower, \
                    f"Must not use 'Ark Assistant': {res_multi.get('reply')}"
                # 3. Model information
                assert any(m in multi_reply_lower for m in ['llama', 'mlx', 'local']), \
                    f"Multi-question reply must state model info: {res_multi.get('reply')}"
                # 4. Capabilities (what can you do)
                assert any(cap in multi_reply_lower for cap in ['help', 'assist', 'capabilities', 'can', 'browse', 'answer', 'code']), \
                    f"Multi-question reply must state capabilities: {res_multi.get('reply')}"
                # 5. Reverse a string in python
                assert ('[::-1]' in res_multi.get('reply', '') or 'reversed(' in multi_reply_lower or 'reverse' in multi_reply_lower) and ('def ' in res_multi.get('reply', '') or 'python' in multi_reply_lower or 'string' in multi_reply_lower), \
                    f"Multi-question reply must provide Python string reversal: {res_multi.get('reply')}"

                print("PASS: Multi-question query answered all 5 questions thoroughly and completely!")

                print("\n--- 3b. Testing inverted query 'Remember my name do you?' in a fresh chat ---")
                res_inverted = await eval_page("""(async () => {
                    const {state} = await window.__arkTest.pageHandler.createConversation('local:mlx:llama-3.2-11b-vision-instruct');
                    try {
                        const {response} = await window.__arkTest.pageHandler.sendAgentPrompt({
                            conversationId: state.id,
                            message: "Remember my name do you?",
                            images: [],
                            providerCredential: null,
                            steeringInstruction: null
                        });
                        const cleanSteps = (response.steps || []).map(s => ({
                            stepType: String(s.stepType || ''),
                            title: String(s.title || ''),
                            detail: String(s.detail || '')
                        }));
                        return {
                            success: Boolean(response.success),
                            steps: cleanSteps,
                            reply: String(response.response || '')
                        };
                    } finally {
                        await window.__arkTest.pageHandler.deleteConversation(state.id);
                    }
                })()""")
                print("Inverted query reply:", res_inverted.get('reply'))
                inverted_tools = [s['title'] for s in res_inverted.get('steps', []) if s.get('stepType') == 'tool_call']
                print("Inverted query tool calls:", inverted_tools)
                assert 'read_graph' in inverted_tools or 'search_nodes' in inverted_tools, f"Expected read_graph, got {inverted_tools}"
                assert 'add_observations' not in inverted_tools, f"Must NOT call add_observations for question! Got {inverted_tools}"
                assert 'Arkapravo' in res_inverted.get('reply', ''), f"Expected Arkapravo in reply: {res_inverted.get('reply')}"
                mem_content_after = (Path.home() / '.arkbrowser' / 'mcp' / 'memory.jsonl').read_text()
                assert 'name do you' not in mem_content_after, "Must not save 'name do you' to memory.jsonl!"
                print("PASS: Inverted query 'Remember my name do you?' fetched memory and did NOT write garbage!")

                print("\n--- 3c. Testing non-biographical sentence 'I am going to Paris tomorrow' ---")
                res_non_bio = await eval_page("""(async () => {
                    const {state} = await window.__arkTest.pageHandler.createConversation('local:mlx:llama-3.2-11b-vision-instruct');
                    try {
                        const {response} = await window.__arkTest.pageHandler.sendAgentPrompt({
                            conversationId: state.id,
                            message: "I am going to Paris tomorrow",
                            images: [],
                            providerCredential: null,
                            steeringInstruction: null
                        });
                        const cleanSteps = (response.steps || []).map(s => ({
                            stepType: String(s.stepType || ''),
                            title: String(s.title || ''),
                            detail: String(s.detail || '')
                        }));
                        return {
                            success: Boolean(response.success),
                            steps: cleanSteps,
                            reply: String(response.response || '')
                        };
                    } finally {
                        await window.__arkTest.pageHandler.deleteConversation(state.id);
                    }
                })()""")
                non_bio_tools = [s['title'] for s in res_non_bio.get('steps', []) if s.get('stepType') == 'tool_call']
                print("Non-bio tool calls:", non_bio_tools)
                assert 'add_observations' not in non_bio_tools, f"Must NOT call add_observations for 'I am going to Paris', got {non_bio_tools}"
                mem_content_paris = (Path.home() / '.arkbrowser' / 'mcp' / 'memory.jsonl').read_text()
                assert 'Paris' not in mem_content_paris, "Must not save 'Paris' as name into memory.jsonl!"
                print("PASS: Non-biographical sentence did not trigger false memory write!")

                print("\n--- 3c2. Testing coding question 'Can you tell me the best ways to check a palindrome using python?' ---")
                res_palindrome = await eval_page("""(async () => {
                    const {state} = await window.__arkTest.pageHandler.createConversation('local:mlx:llama-3.2-11b-vision-instruct');
                    try {
                        const {response} = await window.__arkTest.pageHandler.sendAgentPrompt({
                            conversationId: state.id,
                            message: "Can you tell me the best ways to check a palindrome using python?",
                            images: [],
                            providerCredential: null,
                            steeringInstruction: null
                        });
                        const cleanSteps = (response.steps || []).map(s => ({
                            stepType: String(s.stepType || ''),
                            title: String(s.title || ''),
                            detail: String(s.detail || '')
                        }));
                        return {
                            success: Boolean(response.success),
                            steps: cleanSteps,
                            reply: String(response.response || '')
                        };
                    } finally {
                        await window.__arkTest.pageHandler.deleteConversation(state.id);
                    }
                })()""")
                print("Palindrome reply:", res_palindrome.get('reply')[:200])
                pal_tools = [s['title'] for s in res_palindrome.get('steps', []) if s.get('stepType') == 'tool_call']
                print("Palindrome tool calls:", pal_tools)
                assert 'read_graph' not in pal_tools, "Must NOT fetch memory for general coding questions!"
                assert 'add_observations' not in pal_tools, "Must NOT write memory for general coding questions!"
                for s in res_palindrome.get('steps', []):
                    if 'sequential' in s.get('title', '').lower():
                        assert 'Stored memories' not in s.get('detail', ''), \
                            f"Memory context must not leak into thought: {s.get('detail')}"
                pal_reply = res_palindrome.get('reply', '').lower()
                assert 'rewritten message' not in pal_reply, f"Reply must not contain 'rewritten message': {pal_reply}"
                assert 'palindrome' in pal_reply or 'reverse' in pal_reply, f"Reply should answer palindrome question: {pal_reply}"
                print("PASS: Palindrome query answered cleanly without memory leakage or prompt pollution!")

                print("\n--- 3d. Testing conversational question 'Hey, do you remember my name?' in a fresh chat ---")
                res_hey_remember = await eval_page("""(async () => {
                    const {state} = await window.__arkTest.pageHandler.createConversation('local:mlx:llama-3.2-11b-vision-instruct');
                    try {
                        const {response} = await window.__arkTest.pageHandler.sendAgentPrompt({
                            conversationId: state.id,
                            message: "Hey, do you remember my name?",
                            images: [],
                            providerCredential: null,
                            steeringInstruction: null
                        });
                        const cleanSteps = (response.steps || []).map(s => ({
                            stepType: String(s.stepType || ''),
                            title: String(s.title || ''),
                            detail: String(s.detail || '')
                        }));
                        return {
                            success: Boolean(response.success),
                            steps: cleanSteps,
                            reply: String(response.response || '')
                        };
                    } finally {
                        await window.__arkTest.pageHandler.deleteConversation(state.id);
                    }
                })()""")
                print("Hey remember reply:", res_hey_remember.get('reply'))
                hey_tools = [s['title'] for s in res_hey_remember.get('steps', []) if s.get('stepType') == 'tool_call']
                print("Hey remember tool calls:", hey_tools)
                assert 'read_graph' in hey_tools or 'search_nodes' in hey_tools, f"Expected read_graph, got {hey_tools}"
                assert 'Arkapravo' in res_hey_remember.get('reply', ''), f"Expected Arkapravo in reply: {res_hey_remember.get('reply')}"
                print("PASS: 'Hey, do you remember my name?' answered accurately with the user's name!")

                print("\n--- 4. Testing sidebar switching without refresh ---")
                res_switch = await eval_page("""(async () => {
                    const {state: convA} = await window.__arkTest.pageHandler.createConversation('local:mlx:llama-3.2-11b-vision-instruct');
                    const {state: convB} = await window.__arkTest.pageHandler.createConversation('local:mlx:llama-3.2-11b-vision-instruct');
                    try {
                        // Switch to convA
                        const {state: switchedA} = await window.__arkTest.pageHandler.switchConversation(convA.id);
                        // Switch to convB
                        const {state: switchedB} = await window.__arkTest.pageHandler.switchConversation(convB.id);
                        return {
                            switchedAId: switchedA ? switchedA.id : null,
                            switchedBId: switchedB ? switchedB.id : null,
                            expectedA: convA.id,
                            expectedB: convB.id
                        };
                    } finally {
                        await window.__arkTest.pageHandler.deleteConversation(convA.id);
                        await window.__arkTest.pageHandler.deleteConversation(convB.id);
                    }
                })()""")
                print("Switch test result:", res_switch)
                assert res_switch['switchedAId'] == res_switch['expectedA']
                assert res_switch['switchedBId'] == res_switch['expectedB']
                print("PASS: Sidebar chat switching switches seamlessly without page reload!")

                print("\n--- 4b. Testing memory query after deleting/clearing memory ---")
                res_cleared, res_followup = await eval_page("""(async () => {
                    await window.__arkTest.pageHandler.clearAllMemory();
                    const {state} = await window.__arkTest.pageHandler.createConversation('local:mlx:llama-3.2-11b-vision-instruct');
                    try {
                        const {response: r1} = await window.__arkTest.pageHandler.sendAgentPrompt({
                            conversationId: state.id,
                            message: "Do you know my name?",
                            images: [],
                            providerCredential: null,
                            steeringInstruction: null
                        });
                        const cleanSteps1 = (r1.steps || []).map(s => ({
                            stepType: String(s.stepType || ''),
                            title: String(s.title || ''),
                            detail: String(s.detail || '')
                        }));

                        // Follow-up: provide name directly in reply to assistant's invitation
                        const {response: r2} = await window.__arkTest.pageHandler.sendAgentPrompt({
                            conversationId: state.id,
                            message: "Arkapravo Ghosh",
                            images: [],
                            providerCredential: null,
                            steeringInstruction: null
                        });
                        const cleanSteps2 = (r2.steps || []).map(s => ({
                            stepType: String(s.stepType || ''),
                            title: String(s.title || ''),
                            detail: String(s.detail || '')
                        }));

                        return [
                            {
                                success: Boolean(r1.success),
                                steps: cleanSteps1,
                                reply: String(r1.response || '')
                            },
                            {
                                success: Boolean(r2.success),
                                steps: cleanSteps2,
                                reply: String(r2.response || '')
                            }
                        ];
                    } finally {
                        await window.__arkTest.pageHandler.deleteConversation(state.id);
                    }
                })()""")
                print("Cleared memory query reply:", res_cleared.get('reply'))
                cleared_tools = [s['title'] for s in res_cleared.get('steps', []) if s.get('stepType') == 'tool_call']
                print("Cleared memory query tool calls:", cleared_tools)
                assert 'read_graph' in cleared_tools or 'search_nodes' in cleared_tools, f"Expected read_graph, got {cleared_tools}"
                reply_lower = res_cleared.get('reply', '').lower()
                assert 'ark assistant' not in reply_lower or 'your name is ark assistant' not in reply_lower, \
                    f"Must NOT hallucinate 'Ark Assistant' as user's name: {res_cleared.get('reply')}"
                assert any(w in reply_lower for w in ['not', "don't", "dont", 'no', 'remember', 'tell me']), \
                    f"Expected polite statement of unremembered name: {res_cleared.get('reply')}"
                print("PASS: Empty/cleared memory handled truthfully without hallucinating user's name!")

                print("\n--- 4b2. Testing compound query: 'Can you tell me the best ways to check a palindrome using python? Also, what's my name? Lemme see if you remember my name.' ---")
                res_compound = await eval_page("""(async () => {
                    const {state} = await window.__arkTest.pageHandler.createConversation('local:mlx:llama-3.2-11b-vision-instruct');
                    try {
                        const {response} = await window.__arkTest.pageHandler.sendAgentPrompt({
                            conversationId: state.id,
                            message: "Can you tell me the best ways to check a palindrome using python? Also, what's my name? Lemme see if you remember my name.",
                            images: [],
                            providerCredential: null,
                            steeringInstruction: null
                        });
                        const cleanSteps = (response.steps || []).map(s => ({
                            stepType: String(s.stepType || ''),
                            title: String(s.title || ''),
                            detail: String(s.detail || '')
                        }));
                        return {
                            success: Boolean(response.success),
                            steps: cleanSteps,
                            reply: String(response.response || '')
                        };
                    } finally {
                        await window.__arkTest.pageHandler.deleteConversation(state.id);
                    }
                })()""")
                print("Compound reply:", res_compound.get('reply'))
                compound_tools = [s['title'] for s in res_compound.get('steps', []) if s.get('stepType') == 'tool_call']
                print("Compound tool calls:", compound_tools)
                assert 'read_graph' in compound_tools or 'search_nodes' in compound_tools, f"Expected read_graph in {compound_tools}"
                comp_reply_lower = res_compound.get('reply', '').lower()
                assert any(w in comp_reply_lower for w in ['not', "don't", "dont", 'no', 'remember', 'tell me']), \
                    f"Expected statement that name is not known: {res_compound.get('reply')}"
                assert 'palindrome' in comp_reply_lower or 'reverse' in comp_reply_lower or 'string' in comp_reply_lower or '[::-1]' in comp_reply_lower, \
                    f"Must answer palindrome question as well: {res_compound.get('reply')}"
                assert "i'm here to assist you with checking palindromes" not in comp_reply_lower, \
                    f"Must actually provide the palindrome answer rather than deferring: {res_compound.get('reply')}"
                print("PASS: Compound query answered BOTH the memory check AND the palindrome question!")

                print("\n--- 4c. Testing raw name response 'Arkapravo Ghosh' after assistant invitation ---")
                print("Followup reply:", res_followup.get('reply'))
                followup_tools = [s['title'] for s in res_followup.get('steps', []) if s.get('stepType') == 'tool_call']
                print("Followup tool calls:", followup_tools)
                assert 'add_observations' in followup_tools, f"Expected add_observations in followup tools: {followup_tools}"
                assert any('sequential' in t.lower() for t in followup_tools), f"Expected sequential thinking in {followup_tools}"
                mem_after_followup = (Path.home() / '.arkbrowser' / 'mcp' / 'memory.jsonl').read_text()
                assert 'Arkapravo Ghosh' in mem_after_followup, "Expected Arkapravo Ghosh saved to memory.jsonl after name reply!"
                assert any(name in res_followup.get('reply', '') for name in ['Arkapravo', 'Arkpravo', 'Ghosh']), \
                    f"Expected greeting with name: {res_followup.get('reply')}"
                print("PASS: Raw name response saved into memory and acknowledged warmly!")

                print("\nALL TARGETED USER FLOW VERIFICATION TESTS PASSED SUCCESSFULLY!")

        finally:
            proc.terminate()
            proc.wait()

if __name__ == '__main__':
    asyncio.run(main())
