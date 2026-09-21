#!/usr/bin/env python3
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from agent_test import CDP, browser

async def main():
    binary = ROOT / 'chromium/src/out/ArkDev/Ark Browser.app/Contents/MacOS/Ark Browser'
    artifacts = ROOT / 'test-results' / 'mcp_modal'
    artifacts.mkdir(parents=True, exist_ok=True)

    async with browser(binary, artifacts) as cdp:
        page = await cdp.first_page()
        await cdp.navigate(page, 'ark://ark-chat/#models')
        await asyncio.sleep(1.5)

        # Click MCP Plugins tab
        await cdp.evaluate(page, """(() => {
            const mcpTab = document.getElementById('mcp-tab');
            if (mcpTab) mcpTab.click();
        })()""")
        await asyncio.sleep(0.5)

        # Open Add Custom MCP Server modal
        await cdp.evaluate(page, """(() => {
            const btn = document.getElementById('add-mcp-btn');
            if (btn) btn.click();
        })()""")
        await asyncio.sleep(0.5)

        # Check dialog dimensions and flex layout
        dialog_info = await cdp.evaluate(page, """(() => {
            const dialog = document.getElementById('mcp-add-dialog');
            const form = document.getElementById('mcp-add-form');
            const cliPanel = document.getElementById('mcp-cli-panel');
            const rect = dialog.getBoundingClientRect();
            const formStyle = window.getComputedStyle(form);
            return {
                width: rect.width,
                height: rect.height,
                formFlexDirection: formStyle.flexDirection,
                cliPanelDisplay: window.getComputedStyle(cliPanel).display,
                dialogOpen: dialog.open
            };
        })()""")
        print("Dialog layout check:", dialog_info)
        assert dialog_info['dialogOpen'] is True
        assert dialog_info['width'] >= 500, f"Expected width >= 500px, got {dialog_info['width']}"
        assert dialog_info['formFlexDirection'] == 'column', f"Expected column flex, got {dialog_info['formFlexDirection']}"

        # Populate CLI fields for preview
        await cdp.evaluate(page, """(() => {
            document.getElementById('mcp-name-input').value = 'Weather Tools';
            document.getElementById('mcp-cmd-input').value = 'npx -y @modelcontextprotocol/server-weather';
            document.getElementById('mcp-args-input').value = '--units imperial';
            document.getElementById('mcp-env-input').value = 'API_KEY=ark_demo_key_xyz';
            document.getElementById('mcp-tools-input').value = 'get_weather, get_forecast';
        })()""")
        await asyncio.sleep(0.3)

        # Take screenshot of CLI mode
        cli_screenshot = artifacts / '01_mcp_modal_cli_mode.png'
        await cdp.screenshot(page, cli_screenshot)
        print(f"Captured CLI mode screenshot: {cli_screenshot}")

        # Switch to JSON mode tab
        await cdp.evaluate(page, """(() => {
            document.getElementById('mcp-tab-json').click();
        })()""")
        await asyncio.sleep(0.5)

        json_screenshot = artifacts / '02_mcp_modal_json_mode.png'
        await cdp.screenshot(page, json_screenshot)
        print(f"Captured JSON mode screenshot: {json_screenshot}")

        # Test tokenizeCommandLine via __arkTest
        token_tests = await cdp.evaluate(page, """(() => {
            const tokenize = window.__arkTest.tokenizeCommandLine;
            return {
                simple: tokenize('npx -y server-weather'),
                quoted: tokenize('python3 "my script.py" --flag="hello world"'),
                singleQuoted: tokenize("node 'spaced path/app.js' arg1")
            };
        })()""")
        print("Tokenizer tests:", token_tests)
        assert token_tests['simple']['command'] == 'npx'
        assert token_tests['simple']['args'] == ['-y', 'server-weather']
        assert token_tests['quoted']['command'] == 'python3'
        assert token_tests['quoted']['args'] == ['my script.py', '--flag=hello world']
        assert token_tests['singleQuoted']['command'] == 'node'
        assert token_tests['singleQuoted']['args'] == ['spaced path/app.js', 'arg1']

        # Test adding command-less / remote HTTP server via JSON
        await cdp.evaluate(page, """(() => {
            const jsonArea = document.getElementById('mcp-json-input');
            jsonArea.value = JSON.stringify({
                "mcpServers": {
                    "RivalSearchMCP": {
                        "url": "https://RivalSearchMCP.fastmcp.app/mcp"
                    }
                }
            }, null, 2);
        })()""")
        await asyncio.sleep(0.3)

        # Submit the form
        await cdp.evaluate(page, """(() => {
            document.getElementById('mcp-save-btn').click();
        })()""")
        await cdp.wait_for(page, "!document.getElementById('mcp-add-dialog').open", timeout=15)
        await asyncio.sleep(0.5)

        # Verify dialog closed and server was added
        added_server_info = await cdp.evaluate(page, """(() => {
            const dialog = document.getElementById('mcp-add-dialog');
            const cards = Array.from(document.querySelectorAll('#mcp-server-list .mcp-card'));
            const rivalCard = cards.find(c => c.querySelector('h3') && c.querySelector('h3').textContent.includes('RivalSearchMCP'));
            if (!rivalCard) {
                return { dialogOpen: dialog.open, found: false };
            }
            const desc = rivalCard.querySelector('.mcp-desc') ? rivalCard.querySelector('.mcp-desc').textContent : '';
            const tag = rivalCard.querySelector('.mcp-meta .tag') ? rivalCard.querySelector('.mcp-meta .tag').textContent : '';
            return {
                dialogOpen: dialog.open,
                found: true,
                title: rivalCard.querySelector('h3').textContent,
                description: desc,
                transportTag: tag
            };
        })()""")
        print("Added remote MCP server check:", added_server_info)
        assert added_server_info['dialogOpen'] is False, "Dialog should be closed after submission"
        assert added_server_info['found'] is True, "RivalSearchMCP should be present in the server list"
        assert 'Remote HTTP / SSE MCP server' in added_server_info['description']
        assert added_server_info['transportTag'] == 'http'

        list_screenshot = artifacts / '03_mcp_list_remote_added.png'
        await cdp.screenshot(page, list_screenshot)
        print(f"Captured remote server in list screenshot: {list_screenshot}")

        # Clean up added server
        await cdp.evaluate(page, """(async () => {
            const handler = window.__arkTest ? window.__arkTest.pageHandler : null;
            if (handler) {
                const {servers} = await handler.getMcpServers();
                const rival = servers.find(s => s.name === 'RivalSearchMCP');
                if (rival) {
                    await handler.deleteMcpServer(rival.id);
                }
            }
        })()""")
        await asyncio.sleep(0.5)

        print("ALL MCP MODAL UI CHECKS PASSED!")

if __name__ == '__main__':
    asyncio.run(main())
