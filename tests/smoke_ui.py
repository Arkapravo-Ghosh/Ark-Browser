#!/usr/bin/env python3
# Copyright 2026 Arkapravo Ghosh
"""Exercise the compiled Ark browser using disposable profiles and DevTools.

Requires Python 3 and websockets. No provider credentials or external requests.
Run from the workspace: python3 tests/smoke_ui.py
"""
import argparse
import asyncio
import base64
import contextlib
import http.server
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time

import websockets

ROOT = Path(__file__).resolve().parents[1]


class LocalPage(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'<!doctype html><title>Ark navigation smoke</title><h1>Browsing works</h1>'
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


class CDP:
    def __init__(self, ws):
        self.ws = ws
        self.sequence = 0
        self.events = []

    async def call(self, method, params=None, session=None):
        self.sequence += 1
        request_id = self.sequence
        message = {'id': request_id, 'method': method, 'params': params or {}}
        if session:
            message['sessionId'] = session
        await self.ws.send(json.dumps(message))
        while True:
            data = json.loads(await asyncio.wait_for(self.ws.recv(), 40))
            if data.get('id') == request_id:
                if 'error' in data:
                    raise AssertionError(f'{method}: {data["error"]}')
                return data.get('result', {})
            if 'method' in data:
                self.events.append(data)

    async def attach_page(self, target):
        session = (await self.call('Target.attachToTarget', {
            'targetId': target, 'flatten': True}))['sessionId']
        await self.call('Runtime.enable', session=session)
        await self.call('Page.enable', session=session)
        await self.call('Network.enable', session=session)
        # Keep the test offline. The sole allowed web destination is its local
        # fixture; external search navigation is verified via its requested URL.
        await self.call('Network.setBlockedURLs', {'urls': ['https://*']}, session)
        return session

    async def first_page(self):
        targets = (await self.call('Target.getTargets'))['targetInfos']
        target = next(item['targetId'] for item in targets if item['type'] == 'page')
        return await self.attach_page(target)

    async def page(self, context=None):
        params = {'url': 'about:blank'}
        if context:
            params['browserContextId'] = context
        target = (await self.call('Target.createTarget', params))['targetId']
        return await self.attach_page(target)

    async def evaluate(self, session, expression):
        result = await self.call('Runtime.evaluate', {
            'expression': expression, 'awaitPromise': True, 'returnByValue': True,
            'userGesture': True}, session)
        if 'exceptionDetails' in result:
            raise AssertionError(result['exceptionDetails'])
        return result.get('result', {}).get('value')

    async def wait_for(self, session, expression, timeout=25):
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

    async def screenshot(self, session, path, width, height):
        await self.call('Emulation.setDeviceMetricsOverride', {
            'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': False}, session)
        await asyncio.sleep(.3)
        assert await self.evaluate(session,
            'document.documentElement.scrollWidth <= innerWidth'), 'Horizontal overflow'
        shot = await self.call('Page.captureScreenshot', {'format': 'png'}, session)
        path.write_bytes(base64.b64decode(shot['data']))


def check(value, name, results):
    assert value, name
    results.append(name)
    print(f'PASS {name}', flush=True)


@contextlib.asynccontextmanager
async def browser(binary, artifacts, extra=()):
    with tempfile.TemporaryDirectory(dir=artifacts, prefix='ark-ui-smoke-') as directory:
        profile = Path(directory)
        log = (artifacts / ('browser-disabled.log' if extra else 'browser.log')).open('w')
        process = subprocess.Popen([
            str(binary), '--headless=new', '--no-first-run', '--no-default-browser-check',
            '--disable-background-networking', '--disable-component-update',
            '--disable-sync', '--remote-debugging-port=0', f'--user-data-dir={profile}',
            *extra], stdout=log, stderr=log)
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


async def run(args):
    artifacts = args.artifacts.resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    results = []
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), LocalPage)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        async with browser(args.binary.resolve(), artifacts) as cdp:
            ready = "!!document.querySelector('#provider-grid .provider-card')"
            page = await cdp.first_page()
            await cdp.wait_for(page, ready)
            await cdp.wait_for(page, "document.documentElement.dataset.storageReady === 'true'")
            await asyncio.sleep(3)
            check(await cdp.evaluate(page, "!!document.querySelector('#home-page') && !document.querySelector('#main-frame-error')"),
                  'Cold browser startup remains on the Ark new tab', results)
            check(await cdp.evaluate(page, "location.host === 'ark-chat' && !document.querySelector('#home-page').hidden"),
                  'ark://newtab loads the Ark UI through native routing', results)
            check(await cdp.evaluate(page, "document.querySelector('#home-title').textContent.includes('Welcome to Ark')"),
                  'First opening displays Welcome to Ark', results)
            await cdp.call('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-color-scheme', 'value': 'light'}]}, session=page)
            await cdp.screenshot(page, artifacts / 'new-tab-light.png', 1440, 1000)
            check(await cdp.evaluate(page, "document.querySelector('.send-button').disabled"),
                  'Sending is unavailable without a model', results)
            check(await cdp.evaluate(page, "[...document.querySelectorAll('a[href]')].every(a => !a.getAttribute('href').startsWith('chrome://'))"),
                  'All product internal links use ark://', results)
            await cdp.evaluate(page, "document.querySelector('[data-prompt]').click()")
            check(await cdp.evaluate(page, "document.querySelector('#draft').value.startsWith('Help me think')"),
                  'Suggestion creates an unsent draft', results)
            test_draft = '<script>window.arkInjected = true</script> My unsent thought'
            await cdp.evaluate(page, f"document.querySelector('#draft').value = {json.dumps(test_draft)}; document.querySelector('#draft').dispatchEvent(new Event('input'))")
            for route in ['models', 'advanced', 'chat', 'home']:
                await cdp.evaluate(page, f"location.hash = {json.dumps(route)}")
                await cdp.wait_for(page, f"!document.querySelector('#{route}-page').hidden")
            check(await cdp.evaluate(page, f"document.querySelector('#draft').value === {json.dumps(test_draft)} && !window.arkInjected"),
                  'Draft survives route changes and is rendered as text', results)
            await cdp.call('Page.reload', session=page)
            await cdp.wait_for(page, ready)
            await cdp.wait_for(page, f"document.querySelector('#draft').value === {json.dumps(test_draft)}")
            check(await cdp.evaluate(page, f"document.querySelector('#draft').value === {json.dumps(test_draft)}"),
                  'Draft survives reload in the same tab session', results)
            await cdp.evaluate(page, "document.querySelector('#clear-draft').click(); document.querySelector('#clear-dialog').close('cancel')")
            check(await cdp.evaluate(page, "document.querySelector('#draft').value.length > 0"),
                  'Cancel preserves draft', results)
            await cdp.evaluate(page, "document.querySelector('#clear-draft').click(); document.querySelector('#clear-dialog').close('clear')")
            await cdp.wait_for(page, "!document.querySelector('#draft').value")
            await asyncio.sleep(.3)
            check(await cdp.evaluate(page, "document.querySelector('#clear-draft').disabled"),
                  'Clear removes the draft and updates controls', results)
            await cdp.evaluate(page, "document.querySelector('[data-prompt]').click()")
            await asyncio.sleep(.3)
            await cdp.evaluate(page, "document.querySelector('#clear-draft').click()")
            await cdp.call('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': 'Escape', 'code': 'Escape', 'windowsVirtualKeyCode': 27}, page)
            await cdp.wait_for(page, "!document.querySelector('#clear-dialog').open")
            check(await cdp.evaluate(page, "document.querySelector('#draft').value.length > 0"),
                  'Escape never reuses a previous clear confirmation', results)
            await asyncio.sleep(.3)
            await cdp.evaluate(page, "location.hash = 'models'")
            await cdp.wait_for(page, "!document.querySelector('#models-page').hidden")
            check(await cdp.evaluate(page, "document.querySelectorAll('.provider-card').length === 5"),
                  'All five planned cloud connections are described', results)
            await cdp.screenshot(page, artifacts / 'models-light.png', 1440, 1000)
            await cdp.evaluate(page, "document.querySelector('#local-tab').click()")
            check(await cdp.evaluate(page, "!document.querySelector('#local-models').hidden && document.querySelector('#cloud-models').hidden"),
                  'Local model tab shows truthful uninstalled state', results)
            await cdp.evaluate(page, "location.hash = 'advanced'")
            await cdp.wait_for(page, "!document.querySelector('#advanced-page').hidden")
            check(await cdp.evaluate(page, "document.querySelectorAll('.parameter-row').length === 17"),
                  'Advanced options explain all 17 specified parameters', results)
            await cdp.evaluate(page, "location.hash = 'about'")
            await cdp.wait_for(page, "!document.querySelector('#about-page').hidden")
            check(await cdp.evaluate(page, "document.querySelector('#about-page').textContent.includes('© 2026 Arkapravo Ghosh') && document.querySelector('#about-page').textContent.includes('Based on Chromium')"),
                  'About names Arkapravo Ghosh and retains Chromium attribution', results)
            await cdp.evaluate(page, "location.hash = 'home'")
            await cdp.call('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-color-scheme', 'value': 'dark'}]}, session=page)
            await cdp.wait_for(page, "!document.querySelector('#home-page').hidden")
            await cdp.screenshot(page, artifacts / 'new-tab-dark.png', 1440, 1000)
            check(await cdp.evaluate(page, "getComputedStyle(document.body).backgroundColor === 'rgb(30, 35, 31)'"),
                  'Dark appearance changes rendered palette', results)
            await cdp.call('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-color-scheme', 'value': 'light'}]}, session=page)
            await cdp.screenshot(page, artifacts / 'new-tab-narrow.png', 390, 844)
            check(await cdp.evaluate(page, "getComputedStyle(document.querySelector('.mobile-nav')).display !== 'none'"),
                  'Narrow layout keeps workspace navigation available', results)
            second = await cdp.page()
            await cdp.navigate(second, 'ark://ark-chat/', ready)
            await cdp.wait_for(second, "document.querySelector('#draft').value.length > 0")
            check(await cdp.evaluate(second, "document.querySelector('#draft').value.startsWith('Help me think')"),
                  'A separate Ark surface reads the profile conversation draft', results)
            ai_query = 'I need to buy Nike shoes, show me a few'
            await cdp.evaluate(second, f"location.hash = 'home'; document.querySelector('#ai-mode').click(); document.querySelector('#search-input').value = {json.dumps(ai_query)}; document.querySelector('#search-form').requestSubmit()")
            await cdp.wait_for(second, "document.querySelector('#search-status').textContent === 'Opened in AI sidebar.'")
            check(True, 'New-tab Ask AI mode hands its query to the AI sidebar', results)
            context = (await cdp.call('Target.createBrowserContext'))['browserContextId']
            private = await cdp.page(context)
            await cdp.navigate(private, 'ark://newtab/')
            check(await cdp.evaluate(private, "location.host !== 'ark-chat'"),
                  'Private new tabs keep Chromium’s incognito landing page', results)
            await cdp.navigate(private, 'ark://ark-chat/', ready)
            await cdp.wait_for(private, "document.documentElement.dataset.storageReady === 'true'")
            check(await cdp.evaluate(private, "document.querySelector('#draft').value === ''"),
                  'Private context has a separate in-memory conversation', results)
            await cdp.call('Target.disposeBrowserContext', {'browserContextId': context})
            # Test the native Mojo boundary directly, including inputs bypassing
            # HTML validation. No unsupported scheme should execute or navigate.
            for invalid in ['', ' ' * 8, 'x' * 4097, 'javascript:alert(1)', 'data:text/html,unsafe', 'file:///etc/hosts']:
                result = await cdp.evaluate(second, f"(async () => {{ const {{PageHandler}} = await import('./ark.mojom-webui.js'); return (await PageHandler.getRemote().navigate({json.dumps(invalid)})).success; }})()")
                check(result is False, f'Native navigation rejects {invalid[:30]!r}', results)
            local_url = f'http://127.0.0.1:{server.server_port}/from-ark'
            await cdp.evaluate(second, f"document.querySelector('#web-mode').click(); document.querySelector('#search-input').value = {json.dumps(local_url)}; document.querySelector('#search-form').requestSubmit()")
            await cdp.wait_for(second, "document.title === 'Ark navigation smoke'")
            check(True, 'Native search field opens an ordinary web page', results)

            # Test reverse rewrite for ark://newtab and chrome://newtab, and internal URL navigation
            await cdp.navigate(second, 'ark://newtab/')
            await cdp.wait_for(second, "location.host === 'ark-chat'")
            history = await cdp.call('Page.getNavigationHistory', session=second)
            current_entry = history.get('entries', [])[history.get('currentIndex', 0)]
            check(current_entry.get('userTypedURL') == 'ark://newtab/',
                  'New Tab Page accepts ark://newtab/ navigation', results)

            await cdp.evaluate(second, "document.querySelector('#web-mode').click(); document.querySelector('#search-input').value = 'ark://settings'; document.querySelector('#search-form').requestSubmit()")
            await cdp.wait_for(second, "location.host === 'settings'")
            check(True, 'Native search field navigates to internal ark:// URLs', results)

            await cdp.navigate(second, 'chrome://newtab/')
            await cdp.wait_for(second, "location.host === 'ark-chat'")
            check(True, 'chrome://newtab navigates to Ark New Tab Page', results)
            # Exercise canonical built-in controllers through the new scheme.
            for host, title in [('settings', 'Settings'), ('history', 'History'), ('downloads', 'Downloads'), ('bookmarks', 'Bookmarks'), ('version', 'About Version'), ('credits', 'Credits')]:
                await cdp.navigate(second, f'ark://{host}/')
                await cdp.wait_for(second, f"location.host === {json.dumps(host)}")
                check(await cdp.evaluate(second, "!document.querySelector('#main-frame-error') && (document.body.children.length > 0 || document.body.innerText.length > 0)"),
                      f'ark://{host} resolves to the real Chromium page', results)
            await cdp.navigate(second, 'ark://chrome-urls/')
            await cdp.wait_for(second, "!!document.querySelector('chrome-urls-app')?.shadowRoot?.querySelector('a')")
            check(await cdp.evaluate(second, "[...document.querySelector('chrome-urls-app').shadowRoot.querySelectorAll('a')].every(a => !a.textContent.includes('chrome://') && !a.getAttribute('href').startsWith('chrome://'))"),
                  'Built-in page directory exposes only ark:// links', results)

            await cdp.navigate(second, 'ark://settings/')
            await cdp.wait_for(second, "!!document.querySelector('settings-ui')?.shadowRoot?.querySelector('#leftMenu')?.shadowRoot?.querySelector('#extensionsLink')")
            ext_href = await cdp.evaluate(second, "document.querySelector('settings-ui').shadowRoot.querySelector('#leftMenu').shadowRoot.querySelector('#extensionsLink').getAttribute('href')")
            check(ext_href == 'ark://extensions', f'Settings extensions link points to ark://extensions (got {ext_href})', results)

            await cdp.navigate(second, 'ark://history/')
            await cdp.wait_for(second, "!!document.querySelector('history-app')?.shadowRoot?.querySelector('#contentSideBar')?.shadowRoot?.querySelector('#clear-browsing-data')")
            cbd_href = await cdp.evaluate(second, "document.querySelector('history-app').shadowRoot.querySelector('#contentSideBar').shadowRoot.querySelector('#clear-browsing-data').getAttribute('href')")
            check(cbd_href == 'ark://settings/clearBrowserData', f'History clear browsing data link points to ark://settings/clearBrowserData (got {cbd_href})', results)

            await cdp.navigate(second, 'ark://settings/help')
            await cdp.wait_for(second, "!!document.querySelector('settings-ui')?.shadowRoot?.querySelector('settings-main')?.shadowRoot?.querySelector('settings-about-page')?.shadowRoot?.querySelector('a[href*=\"credits\"]')")
            credits_href = await cdp.evaluate(second, "document.querySelector('settings-ui').shadowRoot.querySelector('settings-main').shadowRoot.querySelector('settings-about-page').shadowRoot.querySelector('a[href*=\"credits\"]').getAttribute('href')")
            check(credits_href == 'ark://credits/', f'About page open source license link points to ark://credits/ (got {credits_href})', results)
            await cdp.evaluate(second, "document.querySelector('settings-ui').shadowRoot.querySelector('settings-main').shadowRoot.querySelector('settings-about-page').shadowRoot.querySelector('a[href*=\"credits\"]').click()")
            await asyncio.sleep(2)
            targets = (await cdp.call('Target.getTargets'))['targetInfos']
            credits_target = next((t for t in targets if 'credits' in t['url'] or 'credits' in t['title'].lower()), None)
            check(credits_target is not None and 'blocked' not in credits_target['url'],
                  'About page open source license link navigates to credits without being blocked', results)

            await cdp.navigate(second, 'chrome://customize-chrome-side-panel.top-chrome/')
            await cdp.wait_for(second, "!!document.querySelector('customize-chrome-app')?.shadowRoot?.querySelector('customize-chrome-appearance')?.shadowRoot?.querySelector('cr-theme-color-picker')?.shadowRoot?.querySelector('cr-grid')")
            first_color_info = await cdp.evaluate(second, """(() => {
                const picker = document.querySelector('customize-chrome-app').shadowRoot
                    .querySelector('customize-chrome-appearance').shadowRoot
                    .querySelector('cr-theme-color-picker').shadowRoot;
                const grid = picker.querySelector('cr-grid');
                const first = grid.children[0];
                return {
                    title: first?.getAttribute('title'),
                    checked: first?.hasAttribute('checked'),
                    totalChildren: grid?.children.length
                };
            })()""")
            check(first_color_info and first_color_info.get('title') == 'Viridian' and first_color_info.get('checked') is True and first_color_info.get('totalChildren') == 16,
                  'Viridian theme is default and positioned first in appearance settings', results)

            # Autofill page check: Related Google Services and Smarter form understanding must not be present
            await cdp.navigate(second, 'ark://settings/autofill')
            await cdp.wait_for(second, "!!document.querySelector('settings-ui')?.shadowRoot?.querySelector('settings-main')?.shadowRoot?.querySelector('settings-autofill-page-index')?.shadowRoot?.querySelector('settings-autofill-page')")
            autofill_info = await cdp.evaluate(second, """(() => {
                const autofillPage = document.querySelector('settings-ui')?.shadowRoot
                    ?.querySelector('settings-main')?.shadowRoot
                    ?.querySelector('settings-autofill-page-index')?.shadowRoot
                    ?.querySelector('settings-autofill-page')?.shadowRoot;
                if (!autofillPage) return null;
                const text = autofillPage.textContent || '';
                const card = autofillPage.querySelector('collapsible-autofill-settings-card');
                const cardText = card ? (card.shadowRoot?.textContent || '') : '';
                return {
                    hasRelatedServices: text.includes('Related Google Services') ||
                        text.includes('Google Wallet') ||
                        text.includes('Google Account') ||
                        !!autofillPage.querySelector('#passwordManagerRelatedService') ||
                        !!autofillPage.querySelector('#googleWalletRelatedService'),
                    hasSmarterForm: cardText.includes('Smarter form understanding') ||
                        !!card?.shadowRoot?.querySelector('#optInToggle'),
                    hasWhenOn: cardText.includes('When on'),
                    hasThingsToConsider: cardText.includes('Things to consider') ||
                        cardText.includes('securely processing data on Google') ||
                        !!card?.shadowRoot?.querySelector('.settings-columned-section')
                };
            })()""")
            check(autofill_info and not autofill_info.get('hasRelatedServices'),
                  'Autofill settings page does not contain Related Google Services section', results)
            check(autofill_info and not autofill_info.get('hasSmarterForm'),
                  'Autofill settings page does not contain Smarter form understanding section', results)
            check(autofill_info and not autofill_info.get('hasWhenOn') and not autofill_info.get('hasThingsToConsider'),
                  'Autofill settings page does not contain When on and Things to consider sections', results)
            # Expand the card to screenshot
            await cdp.evaluate(second, """(() => {
                const card = document.querySelector('settings-ui')?.shadowRoot
                    ?.querySelector('settings-main')?.shadowRoot
                    ?.querySelector('settings-autofill-page-index')?.shadowRoot
                    ?.querySelector('settings-autofill-page')?.shadowRoot
                    ?.querySelector('collapsible-autofill-settings-card');
                card?.shadowRoot?.querySelector('cr-expand-button')?.click();
            })()""")
            await asyncio.sleep(0.5)
            await cdp.screenshot(second, artifacts / 'autofill_settings.png', 1440, 1000)

            # Appearance page check: "Ark Browser Panels" is present and "Chrome Panels" is absent
            await cdp.navigate(second, 'ark://settings/appearance')
            await cdp.wait_for(second, "!!document.querySelector('settings-ui')?.shadowRoot?.querySelector('settings-main')?.shadowRoot?.querySelector('settings-appearance-page-index')?.shadowRoot?.querySelector('settings-appearance-page')")
            appearance_has_ark_panels = await cdp.evaluate(second, """(() => {
                const appPage = document.querySelector('settings-ui')?.shadowRoot
                    ?.querySelector('settings-main')?.shadowRoot
                    ?.querySelector('settings-appearance-page-index')?.shadowRoot
                    ?.querySelector('settings-appearance-page')?.shadowRoot;
                if (!appPage) return false;
                const text = appPage.textContent || '';
                return text.includes('Ark Browser Panels') && !text.includes('Chrome Panels');
            })()""")
            check(appearance_has_ark_panels,
                  'Appearance settings renames Chrome Panels to Ark Browser Panels', results)

            # Search engines page check:
            # 1. "part of Ark Browser" instead of "part of Chrome"
            # 2. "add search engines to Ark Browser" instead of "add search engines to Chrome"
            # 3. Gemini shortcut is not prebuilt in search engines
            await cdp.navigate(second, 'ark://settings/searchEngines')
            await cdp.wait_for(second, """(() => {
                const sp = document.querySelector('settings-ui')?.shadowRoot
                    ?.querySelector('settings-main')?.shadowRoot
                    ?.querySelector('settings-search-page-index')?.shadowRoot
                    ?.querySelector('settings-search-engines-page');
                return !!sp && !!sp.shadowRoot && (sp.shadowRoot.textContent || '').length > 0;
            })()""")
            search_page_info = await cdp.evaluate(second, """(async () => {
                const searchPage = document.querySelector('settings-ui')?.shadowRoot
                    ?.querySelector('settings-main')?.shadowRoot
                    ?.querySelector('settings-search-page-index')?.shadowRoot
                    ?.querySelector('settings-search-engines-page');
                if (!searchPage || !searchPage.shadowRoot) return null;
                const text = searchPage.shadowRoot.textContent || '';
                let extExplanation = '';
                try {
                    const {loadTimeData} = await import('chrome://resources/js/load_time_data.js');
                    extExplanation = loadTimeData.getString('searchEnginesExtensionExplanation');
                } catch (e) {
                    extExplanation = e.toString();
                }
                return {
                    hasArkPart: text.includes('part of Ark Browser'),
                    hasChromePart: text.includes('part of Chrome'),
                    extExplanation: extExplanation,
                    hasArkExtension: extExplanation.includes('add search engines to Ark Browser'),
                    hasChromeExtension: extExplanation.includes('Chrome'),
                    hasGemini: text.toLowerCase().includes('gemini')
                };
            })()""")
            check(search_page_info and search_page_info.get('hasArkPart') and not search_page_info.get('hasChromePart'),
                  'Search engines page explains "part of Ark Browser" instead of "part of Chrome"', results)
            check(search_page_info and search_page_info.get('hasArkExtension') and not search_page_info.get('hasChromeExtension'),
                  'Search engines extension string explains "add search engines to Ark Browser"', results)
            check(search_page_info and not search_page_info.get('hasGemini'),
                  'Gemini shortcut is not prebuilt on search engines page', results)

            errors = [e for e in cdp.events if e['method'] == 'Runtime.exceptionThrown'
                      and 'ark' in json.dumps(e)]
            check(not errors, 'No uncaught Ark renderer exceptions', results)
        async with browser(args.binary.resolve(), artifacts, ['--disable-features=ArkUI']) as cdp:
            page = await cdp.page()
            await cdp.navigate(page, 'ark://newtab/')
            check(await cdp.evaluate(page, "location.host !== 'ark-chat'"),
                  'ArkUI feature opt-out restores the Chromium new tab', results)
            await cdp.navigate(page, 'ark://settings/')
            await cdp.wait_for(page, "location.host === 'settings'")
            check(True, 'ark:// internal scheme remains usable when UI preview is disabled', results)
    finally:
        server.shutdown()
        server.server_close()
    (artifacts / 'results.json').write_text(json.dumps({'passed': results}, indent=2) + '\n')
    print(f'{len(results)} checks passed. Screenshots and logs: {artifacts}')


def default_binary() -> Path:
    ark_bin = ROOT / 'chromium/src/out/ArkDev/Ark Browser.app/Contents/MacOS/Ark Browser'
    cr_bin = ROOT / 'chromium/src/out/ArkDev/Chromium.app/Contents/MacOS/Chromium'
    return ark_bin if ark_bin.exists() else cr_bin


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=default_binary())
    parser.add_argument('--artifacts', type=Path, default=ROOT / 'test-results')
    asyncio.run(run(parser.parse_args()))
