"""Real stdio failure cases using disposable servers, never a live chart."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from daily_levels import MCP, run
from mcp_transport import MCPTimeoutError, StdioRPC
from test_daily_levels import Fake


class TransportTests(unittest.TestCase):
    def server(self, script):
        process = subprocess.Popen([sys.executable, '-u', '-c', script],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        def close():
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            process.stdin.close()
            process.stdout.close()
        self.addCleanup(close)
        return process

    def test_timeout_keeps_connection_available_for_cleanup_and_cancels_only_tool(self):
        process = self.server('''import json,sys
cancelled=[]
for line in sys.stdin:
    message=json.loads(line)
    if message['method']=='notifications/cancelled':
        cancelled.append(message['params']['requestId']); continue
    if message['method']=='stall': continue
    print(json.dumps({'id':message['id'],'result':cancelled}),flush=True)
''')
        rpc = StdioRPC(process, timeout=0.15)
        start = time.monotonic()
        with self.assertRaises(MCPTimeoutError):
            rpc.request('stall', {})
        self.assertLess(time.monotonic()-start, 1.5)
        self.assertIsNone(process.poll())
        self.assertEqual(rpc.request('restore', {}, timeout=2), [1])

    def test_late_response_cannot_be_mistaken_for_restoration_response(self):
        process = self.server('''import json,sys
late=None
for line in sys.stdin:
    message=json.loads(line)
    if 'id' not in message: continue
    if message['method']=='stall': late=message['id']; continue
    if late is not None:
        print(json.dumps({'id':late,'result':'old response'}),flush=True); late=None
    print(json.dumps({'id':message['id'],'result':'restored'}),flush=True)
''')
        rpc = StdioRPC(process, timeout=0.15)
        with self.assertRaises(MCPTimeoutError): rpc.request('stall', {})
        self.assertEqual(rpc.request('restore', {}, timeout=2), 'restored')

    def test_partial_json_line_has_a_deadline(self):
        process = self.server('''import sys,time
sys.stdin.readline()
sys.stdout.write('{"id":1,"result":'); sys.stdout.flush()
time.sleep(20)
''')
        rpc = StdioRPC(process, timeout=0.15)
        with self.assertRaises(MCPTimeoutError): rpc.request('partial', {})

    def test_unread_stdin_cannot_block_a_large_request_indefinitely(self):
        process = self.server('import time; time.sleep(20)')
        rpc = StdioRPC(process, timeout=0.15)
        start = time.monotonic()
        with self.assertRaises(MCPTimeoutError): rpc.request('large', {'value':'x'*2_000_000})
        self.assertLess(time.monotonic()-start, 1.5)
        with self.assertRaisesRegex(RuntimeError, 'cannot be reused'):
            rpc.request('restore', {})

    def test_unsolicited_messages_do_not_reset_deadline(self):
        process = self.server('''import json,sys,time
sys.stdin.readline()
while True:
    print(json.dumps({'method':'notifications/progress','params':{}}),flush=True)
    time.sleep(.01)
''')
        rpc = StdioRPC(process, timeout=0.15)
        start = time.monotonic()
        with self.assertRaises(MCPTimeoutError): rpc.request('noisy', {})
        self.assertLess(time.monotonic()-start, 1.5)

    def test_server_exit_is_reported_without_waiting_for_deadline(self):
        process = self.server('import sys; sys.stdin.readline()')
        rpc = StdioRPC(process, timeout=2)
        with self.assertRaisesRegex(RuntimeError, 'disconnected'):
            rpc.request('exit', {})

    def test_failed_initialization_closes_process_without_cancelling_initialize(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/'src').mkdir()
            (root/'src/server.js').write_text('// fixture')
            (root/'package.json').write_text('{}')
            trace=root/'messages.jsonl'
            script='''import sys
with open(sys.argv[1],'a') as trace:
    for line in sys.stdin:
        trace.write(line); trace.flush()
'''
            process=subprocess.Popen([sys.executable,'-u','-c',script,str(trace)],
                                     stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
            self.addCleanup(lambda: process.poll() is None and process.kill())
            with patch.dict('os.environ', {'TVLEVELS_MCP_ROOT':str(root)}), \
                    patch('daily_levels.subprocess.Popen',return_value=process):
                with self.assertRaises(MCPTimeoutError): MCP(root,startup_timeout=0.3)
            self.assertIsNotNone(process.poll())
            self.assertTrue(process.stdin.closed)
            messages=[json.loads(line) for line in trace.read_text().splitlines()]
            self.assertEqual([message['method'] for message in messages], ['initialize'])


class RestorationAfterTimeoutTests(unittest.TestCase):
    def test_timeout_after_timeframe_change_still_restores_session_and_timeframe(self):
        class TimedOut(Fake):
            def call(self,name,**arguments):
                if name=='data_get_ohlcv':
                    raise MCPTimeoutError('simulated bridge timeout')
                return super().call(name,**arguments)
        client=TimedOut()
        with self.assertRaisesRegex(MCPTimeoutError,'simulated bridge timeout'):
            run(client,enabled_types=['gap'])
        self.assertEqual((client.resolution,client.session),('5','regular'))

    def test_unresponsive_restoration_is_explicit_and_not_masked_by_release(self):
        class Unresponsive(Fake):
            stalled=False
            def call(self,name,**arguments):
                if name=='data_get_ohlcv': self.stalled=True
                if self.stalled: raise MCPTimeoutError('bridge unavailable')
                return super().call(name,**arguments)
            def release(self): raise MCPTimeoutError('release failed')
        with self.assertRaisesRegex(RuntimeError,'restoration could not be verified'):
            run(Unresponsive(),enabled_types=['gap'])
