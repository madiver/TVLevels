"""Bounded stdio JSON-RPC without background readers or automatic retries."""
import json
import math
import os
import select
import time


class MCPTimeoutError(RuntimeError):
    pass


class StdioRPC:
    def __init__(self, process, timeout=30.0):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('MCP timeout must be finite and positive')
        self.process = process
        self.timeout = timeout
        self.sequence = 0
        self.buffer = b''
        self.write_failed = False

    def deadline(self, timeout):
        duration = self.timeout if timeout is None else timeout
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError('MCP timeout must be finite and positive')
        return time.monotonic() + duration

    def wait(self, stream, deadline, label, writing=False):
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MCPTimeoutError(f'TradingView MCP timed out while {label}. The action was not retried.')
            try:
                readable, writable, _ = select.select(
                    [] if writing else [stream], [stream] if writing else [], [], remaining)
            except InterruptedError:
                continue
            if readable or writable:
                return

    def _send(self, message, deadline):
        if self.write_failed:
            raise RuntimeError('TradingView MCP input stalled; the connection cannot be reused.')
        stream = self.process.stdin.fileno()
        os.set_blocking(stream, False)
        payload = memoryview((json.dumps(message) + '\n').encode('utf-8'))
        try:
            while payload:
                self.wait(stream, deadline, 'sending a request', writing=True)
                try:
                    written = os.write(stream, payload)
                except BlockingIOError:
                    continue
                if not written:
                    raise RuntimeError('TradingView MCP disconnected')
                payload = payload[written:]
        except (MCPTimeoutError, OSError):
            # A partially written JSON frame must never be followed by another.
            self.write_failed = True
            raise

    def send(self, message, timeout=None):
        try:
            self._send(message, self.deadline(timeout))
        except OSError as error:
            raise RuntimeError('TradingView MCP disconnected while sending a request') from error

    def request(self, method, params, timeout=None):
        deadline = self.deadline(timeout)
        self.sequence += 1
        request_id = self.sequence
        label = params.get('name', method)
        try:
            self._send({'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params}, deadline)
            stream = self.process.stdout.fileno()
            os.set_blocking(stream, False)
            while True:
                # Notifications and late responses share one total deadline.
                if time.monotonic() >= deadline:
                    raise MCPTimeoutError(f'TradingView MCP timed out waiting for {label}. The action was not retried.')
                if b'\n' not in self.buffer:
                    self.wait(stream, deadline, f'waiting for {label}')
                    try:
                        data = os.read(stream, 65536)
                    except BlockingIOError:
                        continue
                    if not data:
                        raise RuntimeError('TradingView MCP server disconnected')
                    self.buffer += data
                    continue
                line, self.buffer = self.buffer.split(b'\n', 1)
                if not line.strip():
                    continue
                try:
                    response = json.loads(line)
                except (ValueError, UnicodeDecodeError) as error:
                    raise RuntimeError('TradingView MCP returned invalid JSON') from error
                if not isinstance(response, dict):
                    raise RuntimeError('TradingView MCP returned an invalid response')
                if response.get('id') != request_id:
                    continue
                if 'error' in response:
                    raise RuntimeError(str(response['error']))
                if 'result' not in response:
                    raise RuntimeError('TradingView MCP response has no result')
                return response['result']
        except MCPTimeoutError:
            # initialize cannot be cancelled. Tool cancellation is best effort;
            # leave the process and pane binding available for restoration.
            if method != 'initialize' and not self.write_failed:
                try:
                    self.send({'jsonrpc': '2.0', 'method': 'notifications/cancelled',
                               'params': {'requestId': request_id, 'reason': 'Client response timeout'}}, timeout=0.1)
                except (OSError, RuntimeError):
                    pass
            raise
        except OSError as error:
            raise RuntimeError('TradingView MCP server disconnected') from error
