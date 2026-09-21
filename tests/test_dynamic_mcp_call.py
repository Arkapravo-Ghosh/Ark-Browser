#!/usr/bin/env python3
# Copyright 2026 Arkapravo Ghosh
"""Live verification test for dynamic MCP server tool execution (RivalSearchMCP)."""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from agent_test import CDP

async def main():
    binary = ROOT / 'chromium/src/out/ArkDev/Ark Browser.app/Contents/MacOS/Ark Browser'
    artifacts = ROOT / 'test-results' / 'dynamic_mcp'
    artifacts.mkdir(parents=True, exist_ok=True)
    log_file = (artifacts / 'browser.log').open('w')

    with tempfile.TemporaryDirectory(dir=artifacts, prefix='ark-mcp-test-', ignore_cleanup_errors=True) as profile_dir:
        profile = Path(profile_dir)
        cmd = [
            str(binary),
            '--headless=new',
            '--no-sandbox',
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
                await asyncio.sleep(0.1)

            assert endpoint.exists(), "DevTools port file not created"
            lines = endpoint.read_text().splitlines()
            ws_url = f"ws://127.0.0.1:{lines[0]}{lines[1]}"

            import websockets
            async with websockets.connect(ws_url, max_size=50 * 1024 * 1024) as ws:
                cdp = CDP(ws)
                targets = await cdp.call('Target.getTargets')
                ark_target = next(t for t in targets['targetInfos'] if t['type'] == 'page')
                session = await cdp.attach_page(ark_target['targetId'])

                await asyncio.sleep(2.0)

                print("\n--- Step 1: Add or Verify RivalSearchMCP ---")
                await cdp.evaluate(session, """(async () => {
                    await window.__arkTest.pageHandler.deleteMcpServer('custom_calc_test');
                })()""")
                servers = await cdp.evaluate(session, """(async () => {
                    const {servers} = await window.__arkTest.pageHandler.getMcpServers();
                    return servers;
                })()""")
                print(f"Registered servers: {[s['name'] for s in servers]}")

                has_rival = any(s['name'] == 'RivalSearchMCP' for s in servers)
                if not has_rival:
                    print("Adding RivalSearchMCP...")
                    add_res = await cdp.evaluate(session, """(async () => {
                        const {success} = await window.__arkTest.pageHandler.addOrUpdateMcpServer({
                            id: 'rival_search_test',
                            name: 'RivalSearchMCP',
                            description: 'Remote HTTP / SSE MCP server',
                            transportType: 'http',
                            commandOrUrl: 'https://RivalSearchMCP.fastmcp.app/mcp',
                            args: [],
                            enabled: true,
                            isPreinstalled: false,
                            policy: 'auto_allow',
                            tools: []
                        });
                        return success;
                    })()""")
                    print("Added RivalSearchMCP result:", add_res)
                    assert add_res is True

                    # Re-fetch servers
                    servers = await cdp.evaluate(session, """(async () => {
                        const {servers} = await window.__arkTest.pageHandler.getMcpServers();
                        return servers;
                    })()""")

                rival_server = next(s for s in servers if s['name'] == 'RivalSearchMCP')
                print("RivalSearchMCP tools discovered:", rival_server.get('tools', []))
                assert len(rival_server.get('tools', [])) > 0, "Expected tools to be dynamically discovered!"
                assert 'web_search' in rival_server['tools'], "Expected web_search in discovered tools!"
                print("PASS: RivalSearchMCP has dynamically discovered tools:", rival_server['tools'])

                print("\n--- Step 2: Test User Prompt 'Try to use rival search to find who won the 2024 super bowl' ---")
                agent_res = await cdp.evaluate(session, """(async () => {
                    const {state} = await window.__arkTest.pageHandler.createConversation('local:mlx:llama-3.2-11b-vision-instruct');
                    try {
                        const {response} = await window.__arkTest.pageHandler.sendAgentPrompt({
                            conversationId: state.id,
                            message: "Try to use rival search to find who won the 2024 super bowl",
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

                print("Agent response success:", agent_res.get('success'))
                print("Agent reply preview:\n", agent_res.get('reply')[:400] + "...")
                steps = agent_res.get('steps', [])
                print(f"Total steps: {len(steps)}")
                for idx, s in enumerate(steps):
                    print(f"  [{idx+1}] {s['stepType']} | {s['title']} | detail snippet: {s['detail'][:120]}...")

                tool_calls = [s['title'] for s in steps if s['stepType'] == 'tool_call']
                observations = [s['title'] for s in steps if s['stepType'] == 'observation']
                print("Tool calls executed:", tool_calls)
                print("Observations received:", observations)

                assert 'web_search' in tool_calls or any('search' in tc.lower() for tc in tool_calls), \
                    f"Expected web_search tool call, but got: {tool_calls}"
                assert any('web_search' in obs.lower() or 'search' in obs.lower() for obs in observations), \
                    f"Expected observation from web_search, but got: {observations}"

                reply_lower = agent_res.get('reply', '').lower()
                assert any(keyword in reply_lower for keyword in ['chiefs', 'kansas city', '49ers', 'super bowl']), \
                    f"Expected Super Bowl winner info in synthesized answer, got: {agent_res.get('reply')}"
                print("PASS: Tool was dynamically called, executed against remote MCP, and results synthesized into response!")

                print("\n--- Step 3: Verify Greetings Still Do Not Trigger Tools ---")
                greeting_res = await cdp.evaluate(session, """(async () => {
                    const {state} = await window.__arkTest.pageHandler.createConversation('local:mlx:llama-3.2-11b-vision-instruct');
                    try {
                        const {response} = await window.__arkTest.pageHandler.sendAgentPrompt({
                            conversationId: state.id,
                            message: "Hello, good morning!",
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

                greeting_tool_calls = [s['title'] for s in greeting_res.get('steps', []) if s['stepType'] == 'tool_call']
                print("Greeting tool calls:", greeting_tool_calls)
                assert len(greeting_tool_calls) == 0, f"Expected 0 tool calls for greeting, got: {greeting_tool_calls}"
                print("PASS: Greeting correctly executed with 0 tool calls!")

                print("\n--- Step 4: Test Multi-Turn Follow-up ('Can\'t you use Rival Search MCP?') ---")
                conv_id = await cdp.evaluate(session, """(async () => {
                    const {state} = await window.__arkTest.pageHandler.createConversation('local:mlx:llama-3.2-11b-vision-instruct');
                    return state.id;
                })()""")

                try:
                    # Turn 1
                    t1_res = await cdp.evaluate(session, f"""(async () => {{
                        const {{response}} = await window.__arkTest.pageHandler.sendAgentPrompt({{
                            conversationId: '{conv_id}',
                            message: "Hey, what about the weather in Bengaluru right now?",
                            images: [],
                            providerCredential: null,
                            steeringInstruction: null
                        }});
                        return {{
                            success: Boolean(response.success),
                            reply: String(response.response || '')
                        }};
                    }})()""")
                    print("Turn 1 reply preview:", t1_res.get('reply')[:150] + "...")

                    # Turn 2: Follow-up asking to use Rival Search MCP
                    multiturn_res = await cdp.evaluate(session, f"""(async () => {{
                        const {{response}} = await window.__arkTest.pageHandler.sendAgentPrompt({{
                            conversationId: '{conv_id}',
                            message: "Can't you use Rival Search MCP?",
                            images: [],
                            providerCredential: null,
                            steeringInstruction: null
                        }});
                        const cleanSteps = (response.steps || []).map(s => ({{
                            stepType: String(s.stepType || ''),
                            title: String(s.title || ''),
                            detail: String(s.detail || '')
                        }}));
                        return {{
                            success: Boolean(response.success),
                            steps: cleanSteps,
                            reply: String(response.response || '')
                        }};
                    }})()""")
                finally:
                    await cdp.evaluate(session, f"""(async () => {{
                        await window.__arkTest.pageHandler.deleteConversation('{conv_id}');
                    }})()""")

                print("Multi-turn Turn 2 reply preview:\n", multiturn_res.get('reply')[:400] + "...")
                m_steps = multiturn_res.get('steps', [])
                for idx, s in enumerate(m_steps):
                    print(f"  [{idx+1}] {s['stepType']} | {s['title']} | detail snippet: {s['detail'][:120]}...")
                m_tool_calls = [s['title'] for s in m_steps if s['stepType'] == 'tool_call']
                print("Multi-turn Turn 2 tool calls:", m_tool_calls)
                assert 'web_search' in m_tool_calls or any('search' in tc.lower() for tc in m_tool_calls), \
                    f"Expected web_search on follow-up, got: {m_tool_calls}"
                m_detail = " ".join([s['detail'] for s in m_steps if s['stepType'] == 'tool_call']).lower()
                assert 'bengaluru' in m_detail or 'weather' in m_detail, \
                    f"Expected query in detail to reference Bengaluru/weather, got: {m_detail}"
                print("PASS: Multi-turn follow-up successfully resolved topic from history and invoked Rival Search MCP!")

                print("\n--- Step 5: Test Direct Request ('Use web search to compare price...') ---")
                price_res = await cdp.evaluate(session, """(async () => {
                    const {state} = await window.__arkTest.pageHandler.createConversation('local:mlx:llama-3.2-11b-vision-instruct');
                    try {
                        const {response} = await window.__arkTest.pageHandler.sendAgentPrompt({
                            conversationId: state.id,
                            message: "Use web search to compare price of Monster Ultra (350 ml) in BlinkIt and Zepto",
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

                print("Price test reply preview:\n", price_res.get('reply')[:400] + "...")
                p_steps = price_res.get('steps', [])
                for idx, s in enumerate(p_steps):
                    print(f"  [{idx+1}] {s['stepType']} | {s['title']} | detail snippet: {s['detail'][:120]}...")
                p_tool_calls = [s['title'] for s in p_steps if s['stepType'] == 'tool_call']
                print("Price test tool calls:", p_tool_calls)
                assert 'web_search' in p_tool_calls or any('search' in tc.lower() for tc in p_tool_calls), \
                    f"Expected web_search on price comparison, got: {p_tool_calls}"
                print("PASS: Direct web search tool request invoked correctly!")

                print("\n--- Step 6: Temporarily Disable RivalSearchMCP and Test Inability to Search ---")
                # Preserve the user's server configuration. The earlier version
                # deleted this real profile-scoped entry and could leave the
                # browser unable to search after the test.
                disable_res = await cdp.evaluate(session, """(async () => {
                    const {servers} = await window.__arkTest.pageHandler.getMcpServers();
                    const rival = servers.find(s => s.name === 'RivalSearchMCP' || s.id === 'rival_search_test');
                    if (rival) {
                        const {success} = await window.__arkTest.pageHandler.toggleMcpServer(rival.id, false);
                        return success;
                    }
                    return true;
                })()""")
                print("Disabled RivalSearchMCP result:", disable_res)

                # Verify RivalSearchMCP remains registered but is disabled.
                servers_after_disable = await cdp.evaluate(session, """(async () => {
                    const {servers} = await window.__arkTest.pageHandler.getMcpServers();
                    return servers;
                })()""")
                assert any(s['name'] == 'RivalSearchMCP' and not s['enabled'] for s in servers_after_disable), \
                    "RivalSearchMCP was not disabled!"

                # Query: "Hey, can you do a Web Search for arkapravo.in?"
                no_search_res = await cdp.evaluate(session, """(async () => {
                    const {state} = await window.__arkTest.pageHandler.createConversation('local:mlx:llama-3.2-11b-vision-instruct');
                    try {
                        const {response} = await window.__arkTest.pageHandler.sendAgentPrompt({
                            conversationId: state.id,
                            message: "Hey, can you do a Web Search for arkapravo.in?",
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

                reenable_res = await cdp.evaluate(session, """(async () => {
                    const {servers} = await window.__arkTest.pageHandler.getMcpServers();
                    const rival = servers.find(s => s.name === 'RivalSearchMCP' || s.id === 'rival_search_test');
                    if (!rival) return false;
                    const {success} = await window.__arkTest.pageHandler.toggleMcpServer(rival.id, true);
                    return success;
                })()""")
                assert reenable_res is True, "RivalSearchMCP was not restored after disabled-state test"

                print("No-search test reply:\n", no_search_res.get('reply'))
                ns_steps = no_search_res.get('steps', [])
                for idx, s in enumerate(ns_steps):
                    print(f"  [{idx+1}] {s['stepType']} | {s['title']} | detail snippet: {s['detail'][:120]}...")
                ns_tool_calls = [s['title'] for s in ns_steps if s['stepType'] == 'tool_call']
                print("No-search tool calls:", ns_tool_calls)

                # Must not call web_search
                assert 'web_search' not in ns_tool_calls, \
                    f"Expected NO web_search tool call when RivalSearchMCP is removed, got: {ns_tool_calls}"

                # Reply must NEVER leak raw <tool_call> tags
                reply_text = no_search_res.get('reply', '')
                assert '<tool_call>' not in reply_text, \
                    f"Raw <tool_call> tag leaked in reply: {reply_text}"
                assert '```tool_call' not in reply_text, \
                    f"Raw ```tool_call tag leaked in reply: {reply_text}"

                # Reply must clearly convey that web search is unavailable
                reply_lower = reply_text.lower()
                assert any(phrase in reply_lower for phrase in [
                    'cannot', "can't", 'unable', 'no web search', 'not currently available',
                    'mcp', 'install', 'plugins', 'no tools'
                ]), f"Expected explanation that web search is unavailable, got: {reply_text}"
                print("PASS: When RivalSearchMCP was removed, model cleanly explained web search is unavailable and 0 tool calls leaked!")

                print("\n--- Step 7: Test Dynamic Custom MCP Server (Claude/Cursor compatible stdio) ---")
                custom_script = ROOT / 'tests' / 'test_custom_mcp_server.cjs'
                add_custom_res = await cdp.evaluate(session, f"""(async () => {{
                    const {{success}} = await window.__arkTest.pageHandler.addOrUpdateMcpServer({{
                        id: 'custom_calc_test',
                        name: 'CustomCalcMCP',
                        description: 'Custom stdio MCP server for calculations',
                        transportType: 'stdio',
                        commandOrUrl: 'node',
                        args: ['{custom_script}'],
                        enabled: true,
                        isPreinstalled: false,
                        policy: 'auto_allow',
                        tools: []
                    }});
                    return success;
                }})()""")
                print("Added CustomCalcMCP result:", add_custom_res)
                assert add_custom_res is True

                # Check discovered tools
                servers_with_custom = await cdp.evaluate(session, """(async () => {
                    const {servers} = await window.__arkTest.pageHandler.getMcpServers();
                    return servers;
                })()""")
                custom_server = next((s for s in servers_with_custom if s['id'] == 'custom_calc_test'), None)
                assert custom_server is not None, "CustomCalcMCP not found in servers!"
                print("CustomCalcMCP discovered tools:", custom_server.get('tools', []))
                assert 'calculate_magic_multiplier' in custom_server.get('tools', []), \
                    f"Expected calculate_magic_multiplier in discovered tools, got: {custom_server.get('tools', [])}"
                print("PASS: Custom MCP server tools dynamically discovered!")

                try:
                    # Test invoking the custom MCP tool
                    custom_agent_res = await cdp.evaluate(session, """(async () => {
                        const {state} = await window.__arkTest.pageHandler.createConversation('local:mlx:llama-3.2-11b-vision-instruct');
                        try {
                            const {response} = await window.__arkTest.pageHandler.sendAgentPrompt({
                                conversationId: state.id,
                                message: "Please use the calculate_magic_multiplier tool to calculate the magic multiplier for a=6 and b=7",
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

                    print("Custom MCP reply preview:\n", custom_agent_res.get('reply')[:400] + "...")
                    c_steps = custom_agent_res.get('steps', [])
                    for idx, s in enumerate(c_steps):
                        print(f"  [{idx+1}] {s['stepType']} | {s['title']} | detail snippet: {s['detail'][:120]}...")
                    c_tool_calls = [s['title'] for s in c_steps if s['stepType'] == 'tool_call']
                    print("Custom MCP tool calls executed:", c_tool_calls)
                    assert 'calculate_magic_multiplier' in c_tool_calls, \
                        f"Expected calculate_magic_multiplier in tool calls, got: {c_tool_calls}"

                    # Check observations
                    c_obs = [s for s in c_steps if s['stepType'] == 'observation' and 'calculate_magic_multiplier' in s['title']]
                    assert len(c_obs) > 0, f"Expected observation from calculate_magic_multiplier, got: {c_steps}"
                    assert 'MAGIC-42' in c_obs[0]['detail'] or '42' in c_obs[0]['detail'], \
                        f"Expected 42 / MAGIC-42 in observation detail, got: {c_obs[0]['detail']}"

                    # Check synthesized reply
                    c_reply = custom_agent_res.get('reply', '')
                    assert '42' in c_reply or 'magic' in c_reply.lower(), \
                        f"Expected 42 or magic in synthesized reply, got: {c_reply}"
                    print("PASS: Custom MCP tool dynamically called and result synthesized!")
                finally:
                    # Clean up custom server
                    await cdp.evaluate(session, """(async () => {
                        await window.__arkTest.pageHandler.deleteMcpServer('custom_calc_test');
                    })()""")
                    print("Cleaned up CustomCalcMCP.")

                print("\n--- Step 8: Test Weather MCP (Multi-tool / Non-Search MCP Server) ---")
                weather_script = ROOT / 'tests' / 'test_weather_mcp.cjs'
                add_weather_res = await cdp.evaluate(session, f"""(async () => {{
                    const {{success}} = await window.__arkTest.pageHandler.addOrUpdateMcpServer({{
                        id: 'weather_mcp_test',
                        name: 'Weather MCP',
                        description: 'Custom weather server with location search and forecast',
                        transportType: 'stdio',
                        commandOrUrl: 'node',
                        args: ['{weather_script}'],
                        enabled: true,
                        isPreinstalled: false,
                        policy: 'auto_allow',
                        tools: []
                    }});
                    return success;
                }})()""")
                print("Added Weather MCP result:", add_weather_res)
                assert add_weather_res is True

                # Check discovered tools
                servers_with_weather = await cdp.evaluate(session, """(async () => {
                    const {servers} = await window.__arkTest.pageHandler.getMcpServers();
                    return servers;
                })()""")
                weather_server = next((s for s in servers_with_weather if s['id'] == 'weather_mcp_test'), None)
                assert weather_server is not None, "Weather MCP not found in servers!"
                print("Weather MCP discovered tools:", weather_server.get('tools', []))
                assert 'search_location' in weather_server.get('tools', []), \
                    f"Expected search_location in tools, got: {weather_server.get('tools', [])}"

                try:
                    # Test invoking the weather MCP tool with the exact user query
                    weather_agent_res = await cdp.evaluate(session, """(async () => {
                        const {state} = await window.__arkTest.pageHandler.createConversation('local:mlx:llama-3.2-11b-vision-instruct');
                        try {
                            const {response} = await window.__arkTest.pageHandler.sendAgentPrompt({
                                conversationId: state.id,
                                message: "Can you check Kolkata weather (current) using weather MCP?",
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

                    print("Weather MCP reply preview:\n", weather_agent_res.get('reply')[:400] + "...")
                    w_steps = weather_agent_res.get('steps', [])
                    for idx, s in enumerate(w_steps):
                        print(f"  [{idx+1}] {s['stepType']} | {s['title']} | detail snippet: {s['detail'][:140]}...")
                    w_tool_calls = [s['title'] for s in w_steps if s['stepType'] == 'tool_call']
                    print("Weather MCP tool calls executed:", w_tool_calls)

                    # Verify that search_location was called
                    assert 'search_location' in w_tool_calls, \
                        f"Expected search_location in tool calls, got: {w_tool_calls}"

                    # Verify that search_location did NOT receive the entire prompt string!
                    for s in w_steps:
                        if s['stepType'] == 'tool_call' and s['title'] == 'search_location':
                            assert 'Can you check Kolkata weather (current) using weather MCP' not in s['detail'], \
                                f"search_location was called with the full conversational prompt! Detail: {s['detail']}"
                            assert 'Kolkata' in s['detail'] or 'kolkata' in s['detail'], \
                                f"search_location was expected to receive Kolkata as query, got: {s['detail']}"

                    # Verify that no OpenMeteo error occurred
                    for s in w_steps:
                        if s['stepType'] == 'observation' or s['stepType'] == 'error':
                            assert 'OpenMeteo API Error: No locations found matching "Can you check' not in s['detail'], \
                                f"OpenMeteo location error triggered: {s['detail']}"

                    # Verify observation received Kolkata coordinates
                    obs_details = " ".join(s['detail'] for s in w_steps if s['stepType'] == 'observation')
                    assert '22.5726' in obs_details or '88.3639' in obs_details or 'Kolkata' in obs_details, \
                        f"Expected coordinates or Kolkata in observation details, got: {obs_details}"

                    # Verify final response
                    w_reply = weather_agent_res.get('reply', '')
                    assert '<tool_call>' not in w_reply and '</tool_call>' not in w_reply, \
                        f"Raw tool call leaked in response: {w_reply}"
                    print("PASS: Weather MCP executed dynamically without treating it as web search or dumping full prompt!")

                    print("\n--- Step 9: Compound Weather + Rival Search request and memory-admission regression ---")
                    compound_res = await cdp.evaluate(session, """(async () => {
                        const {state} = await window.__arkTest.pageHandler.createConversation('local:mlx:llama-3.2-11b-vision-instruct');
                        try {
                            const {response} = await window.__arkTest.pageHandler.sendAgentPrompt({
                                conversationId: state.id,
                                message: "Use Weather MCP to tell me what's the weather is on Bengaluru. Also, using Rival Search MCP, tell me the news about MDR charges on UPI and its details.",
                                images: [],
                                providerCredential: null,
                                steeringInstruction: null
                            });
                            return {
                                success: Boolean(response.success),
                                reply: String(response.response || ''),
                                steps: (response.steps || []).map(s => ({
                                    stepType: String(s.stepType || ''),
                                    title: String(s.title || ''),
                                    detail: String(s.detail || ''),
                                    serverName: String(s.serverName || ''),
                                    toolName: String(s.toolName || '')
                                }))
                            };
                        } finally {
                            await window.__arkTest.pageHandler.deleteConversation(state.id);
                        }
                    })()""")
                    compound_steps = compound_res.get('steps', [])
                    compound_calls = [
                        s for s in compound_steps if s['stepType'] == 'tool_call'
                    ]
                    compound_observations = [
                        s for s in compound_steps if s['stepType'] == 'observation'
                    ]
                    print("Compound tool calls:", [
                        f"{s['serverName']}::{s['title']}" for s in compound_calls
                    ])
                    assert compound_res.get('success'), compound_res
                    assert not any(s['title'] in {'add_observations', 'create_entities'} for s in compound_calls), \
                        f"'its details' was misclassified as user identity: {compound_calls}"
                    assert any('weather' in s['serverName'].lower() for s in compound_calls), \
                        f"Weather MCP was not used: {compound_calls}"
                    assert any(s['title'] == 'web_search' and 'rival' in s['serverName'].lower() for s in compound_calls), \
                        f"Rival Search MCP was not used: {compound_calls}"
                    assert any('weather' in s['serverName'].lower() for s in compound_observations), \
                        f"No Weather MCP observation: {compound_observations}"
                    assert any('rival' in s['serverName'].lower() for s in compound_observations), \
                        f"No Rival Search observation: {compound_observations}"
                    assert 'hello details' not in compound_res.get('reply', '').lower(), compound_res
                    print("PASS: Compound request used both named MCPs and did not corrupt memory with 'details'.")
                finally:
                    # Clean up weather server
                    await cdp.evaluate(session, """(async () => {
                        await window.__arkTest.pageHandler.deleteMcpServer('weather_mcp_test');
                    })()""")
                    print("Cleaned up Weather MCP.")

                print("\nALL DYNAMIC MCP TOOL INVOCATION TESTS (INCLUDING COMPOUND WEATHER + RIVAL SEARCH) PASSED PERFECTLY!")

        finally:
            proc.terminate()
            proc.wait()

if __name__ == '__main__':
    asyncio.run(main())
