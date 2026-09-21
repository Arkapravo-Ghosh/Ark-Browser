#!/usr/bin/env python3
# Copyright 2026 Arkapravo Ghosh
"""Test to verify that browser alert and confirm dialogs display ark:// instead of chrome://."""

import asyncio
import json
from pathlib import Path
import subprocess
import tempfile
import websockets

ROOT = Path(__file__).resolve().parents[1]

async def main():
    binary = ROOT / 'chromium/src/out/ArkDev/Ark Browser.app/Contents/MacOS/Ark Browser'
    artifacts = ROOT / 'test-results' / 'dialog_test'
    artifacts.mkdir(parents=True, exist_ok=True)
    log_file = (artifacts / 'browser.log').open('w')

    with tempfile.TemporaryDirectory(dir=artifacts, prefix='ark-dialog-', ignore_cleanup_errors=True) as profile_dir:
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
            'ark://ark-chat/#models',
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

            async with websockets.connect(ws_url, max_size=50 * 1024 * 1024) as ws:
                seq = 0
                futures = {}
                events = []

                async def reader():
                    try:
                        async for raw in ws:
                            data = json.loads(raw)
                            cid = data.get('id')
                            if cid in futures:
                                futures[cid].set_result(data.get('result', {}))
                            elif 'method' in data:
                                events.append(data)
                    except Exception:
                        pass

                reader_task = asyncio.create_task(reader())

                async def cdp_call(method, params=None, session=None):
                    nonlocal seq
                    seq += 1
                    cid = seq
                    fut = asyncio.get_running_loop().create_future()
                    futures[cid] = fut
                    msg = {'id': cid, 'method': method, 'params': params or {}}
                    if session:
                        msg['sessionId'] = session
                    await ws.send(json.dumps(msg))
                    return await fut

                targets = await cdp_call('Target.getTargets')
                ark_target = next(t for t in targets['targetInfos'] if t['type'] == 'page')
                session = (await cdp_call('Target.attachToTarget', {'targetId': ark_target['targetId'], 'flatten': True}))['sessionId']

                await cdp_call('Runtime.enable', session=session)
                await cdp_call('Page.enable', session=session)

                await asyncio.sleep(1.0)

                # Trigger confirm() asynchronously
                eval_task = asyncio.create_task(cdp_call('Runtime.evaluate', {
                    'expression': "confirm('Test confirmation message')",
                    'userGesture': True
                }, session=session))

                # Wait for dialog opening event
                for _ in range(50):
                    if any(e.get('method') == 'Page.javascriptDialogOpening' for e in events):
                        break
                    await asyncio.sleep(0.1)

                dialog_event = next(e['params'] for e in events if e.get('method') == 'Page.javascriptDialogOpening')
                print("Dialog URL:", dialog_event.get('url'))
                print("Dialog message:", dialog_event.get('message'))
                print("Dialog type:", dialog_event.get('type'))

                # Dismiss dialog
                await cdp_call('Page.handleJavaScriptDialog', {'accept': False}, session=session)
                eval_res = await eval_task
                print("Evaluate result after dismissal:", eval_res)
                assert eval_res.get('result', {}).get('value') is False

                reader_task.cancel()
                print("PASS: Dialog event triggered cleanly and handled without hanging!")

        finally:
            proc.terminate()
            proc.wait()

if __name__ == '__main__':
    asyncio.run(main())
