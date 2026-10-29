#!/usr/bin/env python3
"""Exercise the packaged ACP runtime with loopback-only synthetic peers."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import threading
import time


class Fixture(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(405)
        self.end_headers()

    def do_DELETE(self):
        self.send_response(204)
        self.end_headers()

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))))
        if self.path == "/mcp":
            return self.mcp(body)
        if self.path == "/v1/messages":
            return self.model(body)
        self.send_response(404)
        self.end_headers()

    def mcp(self, request):
        authorized = self.headers.get("Authorization") == "Bearer synthetic-mcp-token"
        method = request.get("method", "")
        self.server.mcp_calls.append((method, authorized))
        if not authorized:
            self.send_response(401)
            self.end_headers()
            return
        if "id" not in request:
            self.send_response(202)
            self.end_headers()
            return
        if method == "initialize":
            result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}, "serverInfo": {"name": "fixture", "version": "1"}}
        elif method == "tools/list":
            result = {"tools": [{"name": "ping", "description": "Synthetic fixture", "inputSchema": {"type": "object", "properties": {}}}]}
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": "SYNTHETIC_MCP_OK"}], "isError": False}
        else:
            result = {}
        payload = json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Mcp-Session-Id", "fixture-session")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def model(self, request):
        self.server.model_attempts += 1
        if self.headers.get("x-api-key") != "synthetic-model-key":
            self.send_response(401)
            self.end_headers()
            return
        self.server.model_calls.append(request)
        number = len(self.server.model_calls)
        events = [{"type": "message_start", "message": {"id": "fixture-message", "type": "message", "role": "assistant", "model": "fixture-model", "content": [], "usage": {"input_tokens": 3, "output_tokens": 0}}}]
        if number in (1, 2):
            name = "mcp__fixture__ping" if number == 1 else "bash"
            if name not in [item.get("name", "") for item in request.get("tools", [])]:
                self.send_response(422)
                self.end_headers()
                return
            args = {} if number == 1 else {"description": "Check synthetic credential environment", "command": "if [ -n \"${DEEPSEEK_API_KEY+x}\" ]; then printf SHELL_ENV_LEAKED; else printf SHELL_ENV_CLEAN; fi"}
            events += [
                {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "fixture-call-" + str(number), "name": name, "input": {}}},
                {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": json.dumps(args)}},
                {"type": "content_block_stop", "index": 0},
            ]
            reason = "tool_use"
        else:
            if number == 3:
                values = []
                def collect(value):
                    if isinstance(value, dict):
                        if value.get("type") == "tool_result":
                            values.append(json.dumps(value))
                        for child in value.values():
                            collect(child)
                    elif isinstance(value, list):
                        for child in value:
                            collect(child)
                collect(request)
                if not any("SHELL_ENV_CLEAN" in value for value in values) or any("SHELL_ENV_LEAKED" in value for value in values):
                    self.send_response(422)
                    self.end_headers()
                    return
            answer = "FIRST_RESULT" if number == 3 else "RESUMED_RESULT"
            events += [
                {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": answer}},
                {"type": "content_block_stop", "index": 0},
            ]
            reason = "end_turn"
        events += [{"type": "message_delta", "delta": {"stop_reason": reason, "stop_sequence": None}, "usage": {"output_tokens": 2}}, {"type": "message_stop"}]
        payload = "".join("event: " + item["type"] + "\ndata: " + json.dumps(item) + "\n\n" for item in events).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class ACPError(RuntimeError):
    def __init__(self, error):
        super().__init__("ACP request was rejected")
        self.code = error.get("code")
        self.detail = error.get("message", "")


class Peer:
    def __init__(self, argv, workspace, environment):
        self.stderr = tempfile.TemporaryFile()
        self.process = subprocess.Popen(argv, cwd=workspace, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr, start_new_session=True)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.buffer = b""
        self.updates = []

    def request(self, request_id, method, params):
        self.write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + 90
        while True:
            while b"\n" in self.buffer:
                raw, self.buffer = self.buffer.split(b"\n", 1)
                message = json.loads(raw)
                if message.get("method") == "session/request_permission" and "id" in message:
                    self.write({"jsonrpc": "2.0", "id": message["id"], "result": {"outcome": {"outcome": "cancelled"}}})
                    raise RuntimeError("unexpected permission prompt under full access")
                if message.get("method") == "session/update":
                    self.updates.append(message.get("params", {}))
                if message.get("id") == request_id:
                    if "error" in message:
                        raise ACPError(message["error"])
                    return message["result"]
            if not self.selector.select(max(0, deadline - time.monotonic())):
                raise TimeoutError(method)
            block = os.read(self.process.stdout.fileno(), 65536)
            if not block:
                raise RuntimeError(f"ACP exited during {method}")
            self.buffer += block

    def write(self, value):
        self.process.stdin.write((json.dumps(value) + "\n").encode())
        self.process.stdin.flush()

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=10)
        self.selector.close()
        self.process.stdout.close()
        self.stderr.close()


def initialize(peer):
    value = peer.request(1, "initialize", {"protocolVersion": 1, "clientCapabilities": {}})
    if "resume" not in value.get("agentCapabilities", {}).get("sessionCapabilities", {}):
        raise RuntimeError("session resume not advertised")


def main():
    stage, policy = (Path(value).resolve(strict=True) for value in sys.argv[1:])
    runtime = stage / "node_modules/@deepseek-ai/dsh/lib/bin.js"
    if not runtime.is_file():
        raise RuntimeError("packaged dsh entry is missing")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    server.daemon_threads = True
    server.mcp_calls, server.model_calls, server.model_attempts = [], [], 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="dsh-ci-qualification-") as root:
            root = Path(root)
            home, workspace = root / "home", root / "workspace"
            home.mkdir(mode=0o700)
            workspace.mkdir()
            (workspace / ".env").write_text("DEEPSEEK_API_KEY=unapproved-synthetic-project-key\n")
            (home / ".env").write_text("DEEPSEEK_API_KEY=unapproved-synthetic-home-key\n")
            base = f"http://127.0.0.1:{server.server_address[1]}"
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "DSH_HOME": str(home),
                   "DSH_ENV_INHERITED_ONLY": "1", "DSH_HIDE_DEEPSEEK_API_KEY": "1", "DSH_PERMISSION_MODE": "danger-full-access",
                   "DSH_TELEMETRY_DISABLED": "1", "DSH_TELEMETRY_MODE": "DISABLED", "DEEPSEEK_BASE_URL": base + "/v1"}
            argv = ["node", str(runtime), "--profile", "acp", "--patch", str(policy)]
            peer = Peer(argv, workspace, env)
            try:
                initialize(peer)
                session = peer.request(2, "session/new", {"cwd": str(workspace), "mcpServers": []})["sessionId"]
                try:
                    peer.request(3, "session/prompt", {"sessionId": session, "prompt": [{"type": "text", "text": "NO_KEY_PROBE"}]})
                except ACPError as error:
                    detail = error.detail.lower()
                    if error.code != -32603 or "credential" not in detail or "api key" not in detail:
                        raise RuntimeError("no-key prompt failed for a different reason") from error
                else:
                    raise RuntimeError("no-key prompt was not refused")
                if server.model_attempts:
                    raise RuntimeError("workspace or home dotenv supplied a credential")
            finally:
                peer.close()
            env["DEEPSEEK_API_KEY"] = "synthetic-model-key"
            servers = [{"type": "http", "name": "fixture", "url": base + "/mcp", "headers": [{"name": "Authorization", "value": "Bearer synthetic-mcp-token"}]}]
            peer = Peer(argv, workspace, env)
            try:
                initialize(peer)
                session = peer.request(2, "session/new", {"cwd": str(workspace), "mcpServers": servers})["sessionId"]
                result = peer.request(3, "session/prompt", {"sessionId": session, "prompt": [{"type": "text", "text": "FIRST_USER_MARKER"}]})
                if result.get("stopReason") != "end_turn" or "FIRST_RESULT" not in json.dumps(peer.updates):
                    raise RuntimeError("first synthetic turn did not complete")
                peer.request(4, "session/close", {"sessionId": session})
            finally:
                peer.close()
            peer = Peer(argv, workspace, env)
            try:
                initialize(peer)
                peer.request(2, "session/resume", {"sessionId": session, "cwd": str(workspace), "mcpServers": servers})
                result = peer.request(3, "session/prompt", {"sessionId": session, "prompt": [{"type": "text", "text": "SECOND_USER_MARKER"}]})
                if result.get("stopReason") != "end_turn" or "RESUMED_RESULT" not in json.dumps(peer.updates):
                    raise RuntimeError("resumed synthetic turn did not complete")
            finally:
                peer.close()
            if ("tools/call", True) not in server.mcp_calls or len(server.model_calls) < 4:
                raise RuntimeError("authenticated MCP call or model steps were missing")
            if "FIRST_USER_MARKER" not in json.dumps(server.model_calls[-1]):
                raise RuntimeError("resumed model request lacks its earlier context")
            if any("dsh_session_log" in call or "dsh_plugin_packages" in call for call in server.model_calls):
                raise RuntimeError("private Harness metadata reached the model")
            print("ACP_SYNTHETIC_OK: model, MCP, shell environment, close, resume and context")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()
