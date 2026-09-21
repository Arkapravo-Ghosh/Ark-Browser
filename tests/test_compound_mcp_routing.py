#!/usr/bin/env python3
# Copyright 2026 Arkapravo Ghosh
"""Regression test for explicit multi-server routing and duplicate tool names."""

import asyncio
from pathlib import Path

from agent_test import browser, default_binary


ROOT = Path(__file__).resolve().parents[1]


async def run() -> None:
    artifacts = ROOT / 'test-results' / 'compound-mcp-routing'
    artifacts.mkdir(parents=True, exist_ok=True)
    weather_script = ROOT / 'tests' / 'test_weather_mcp.cjs'

    async with browser(default_binary(), artifacts) as cdp:
        page = await cdp.first_page()
        await cdp.navigate(page, 'ark://ark-chat/#chat')
        await cdp.evaluate(page, f"""(async () => {{
            const module = await import('./ark.mojom-webui.js');
            const handler = module.PageHandler.getRemote();
            await handler.deleteMcpServer('weather_mcp_test');
            const result = await handler.addOrUpdateMcpServer({{
                id: 'weather_mcp_test',
                name: 'Weather MCP',
                description: 'Deterministic weather routing fixture',
                transportType: 'stdio',
                commandOrUrl: 'node',
                args: [{str(weather_script)!r}],
                enabled: true,
                isPreinstalled: false,
                policy: 'auto_allow',
                tools: [],
            }});
            if (!result.success) throw new Error('Could not add Weather MCP');
        }})()""")

        try:
            result = await cdp.evaluate(page, """(async () => {
                const module = await import('./ark.mojom-webui.js');
                const handler = module.PageHandler.getRemote();
                const servers = (await handler.getMcpServers()).servers;
                const rival = servers.find(server => server.name === 'RivalSearchMCP');
                if (!rival || !rival.enabled) {
                    throw new Error('RivalSearchMCP must be installed and enabled');
                }
                const created = await handler.createConversation(
                    'local:mlx:llama-3.2-11b-vision-instruct');
                try {
                    const {response} = await handler.sendAgentPrompt({
                        conversationId: created.state.id,
                        message: "Use Weather MCP to tell me what's the weather is on Bengaluru. Also, using Rival Search MCP, tell me the news about MDR charges on UPI and its details.",
                        images: [],
                        providerCredential: null,
                        steeringInstruction: null,
                    });
                    return {
                        success: response.success,
                        text: response.response,
                        steps: response.steps.map(step => ({
                            type: step.stepType,
                            title: step.title,
                            serverId: step.serverId,
                            serverName: step.serverName,
                        })),
                    };
                } finally {
                    await handler.deleteConversation(created.state.id);
                }
            })()""")
        finally:
            await cdp.evaluate(page, """(async () => {
                const module = await import('./ark.mojom-webui.js');
                await module.PageHandler.getRemote().deleteMcpServer(
                    'weather_mcp_test');
            })()""")

    calls = [step for step in result['steps'] if step['type'] == 'tool_call']
    observations = [
        step for step in result['steps'] if step['type'] == 'observation']
    assert result['success'], result
    assert any(step['serverId'] == 'weather_mcp_test' for step in calls), calls
    assert any(
        step['serverName'] == 'RivalSearchMCP' for step in calls), calls
    assert any(
        step['serverId'] == 'weather_mcp_test' for step in observations), observations
    assert any(
        step['serverId'] == 'weather_mcp_test' and
        step['title'] == 'Received get_current_weather result'
        for step in observations), observations
    assert any(
        step['serverName'] == 'RivalSearchMCP'
        for step in observations), observations
    assert not any(
        step['title'] in {'add_observations', 'create_entities'} for step in calls), calls
    assert 'hello details' not in result['text'].lower(), result
    print('PASS: exact compound prompt completed current weather and Rival '
          'search on the explicitly named servers, preserved duplicate-tool '
          'identity, and did not write bogus memory.')


if __name__ == '__main__':
    asyncio.run(run())
