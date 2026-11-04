#!/usr/bin/env python3
"""Прямой вызов Doop MCP из шелла (HTTP/1.1, bearer из mcp-tokens/doop.json).

Hermes-клиент иногда теряет соединение с MCP-сервером; этот скрипт работает
напрямую и не зависит от состояния сессии.

  python3 tools/doop_mcp.py list-tools
  python3 tools/doop_mcp.py call get_canvas '{"canvas_id":"pY87uNTgj1","agent_name":"Hermes"}'
"""
import json
import sys
import pathlib
import http.client
import urllib.request

URL = "https://doop.design/mcp"
TOKENS = pathlib.Path.home() / ".hermes/profiles/geekovski/mcp-tokens/doop.json"
SESSION = None


def _post(payload, token, session=None):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(URL, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json, text/event-stream")
    req.add_header("Authorization", "Bearer " + token)
    if session:
        req.add_header("Mcp-Session-Id", session)
    with urllib.request.urlopen(req, timeout=120) as r:
        body = r.read().decode()
        sid = r.headers.get("Mcp-Session-Id")
        ctype = r.headers.get("Content-Type", "")
    # SSE: берём последнюю строку data:
    if "text/event-stream" in ctype or body.lstrip().startswith("event:") or body.lstrip().startswith("data:"):
        chunks = [ln[5:].strip() for ln in body.splitlines() if ln.startswith("data:")]
        body = chunks[-1] if chunks else "{}"
    return json.loads(body), sid


def open_session():
    global SESSION
    token = json.loads(TOKENS.read_text())["access_token"]
    init, sid = _post({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "hermes-cli", "version": "1.0"}},
    }, token)
    SESSION = sid
    # уведомление initialized
    try:
        _post({"jsonrpc": "2.0", "method": "notifications/initialized"}, token, sid)
    except Exception:
        pass
    return token, init


def call(name, arguments):
    token, init = open_session()
    resp, _ = _post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                     "params": {"name": name, "arguments": arguments}}, token, SESSION)
    return resp


def list_tools():
    token, init = open_session()
    resp, _ = _post({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, token, SESSION)
    return [t["name"] for t in resp.get("result", {}).get("tools", [])]


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list-tools"
    if cmd == "list-tools":
        print("\n".join(list_tools()))
    elif cmd == "call":
        tool = sys.argv[2]
        args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        out = call(tool, args)
        res = out.get("result", out)
        # MCP возвращает content[].text с JSON внутри
        if isinstance(res, dict) and "content" in res:
            for c in res["content"]:
                if c.get("type") == "text":
                    print(c["text"][:4000])
        else:
            print(json.dumps(res, ensure_ascii=False)[:4000])
    else:
        print(__doc__)
