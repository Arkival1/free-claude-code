"""A stand-in for llama.cpp's llama-server in router mode, for tests.

It reads the presets file Studio writes, lists each model with a status,
loads and unloads on request, and answers chat completions with timings,
the same shapes the real router returns.
"""

import argparse
import configparser
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def main() -> None:
    if "--list-devices" in sys.argv:
        print("Available devices:")
        print("  Vulkan0: AMD Radeon RX 580 Series (8192 MiB, 7800 MiB free)")
        return
    parser = argparse.ArgumentParser()
    parser.add_argument("--models-preset", required=True)
    parser.add_argument("--models-max", type=int, default=4)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    presets = configparser.ConfigParser(strict=False)
    with open(args.models_preset, encoding="utf-8") as handle:
        presets.read_string("[top]\n" + handle.read())
    models = [name for name in presets.sections() if name not in {"top", "*"}]
    states = dict.fromkeys(models, "unloaded")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            print("request", self.path, flush=True)

        def _send(self, body: object, status: int = 200) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict:
            length = int(self.headers.get("content-length") or 0)
            return json.loads(self.rfile.read(length) or b"{}")

        def do_GET(self) -> None:
            path = self.path.split("?")[0]
            if path == "/health":
                return self._send({"status": "ok"})
            if path in {"/models", "/v1/models"}:
                return self._send(
                    {
                        "data": [
                            {
                                "id": name,
                                "status": {
                                    "value": states[name],
                                    "args": [
                                        f"ctx-size={presets[name].get('ctx-size')}"
                                    ],
                                },
                            }
                            for name in models
                        ]
                    }
                )
            return self._send({"error": "not found"}, 404)

        def do_POST(self) -> None:
            body = self._body()
            name = str(body.get("model") or "")
            if self.path in {"/models/load", "/models/unload"}:
                if name not in states:
                    return self._send({"error": "unknown model"}, 400)
                if self.path == "/models/load":
                    for other, state in states.items():
                        if (
                            state == "loaded"
                            and len([s for s in states.values() if s == "loaded"])
                            >= args.models_max
                        ):
                            states[other] = "unloaded"
                states[name] = "loaded" if self.path == "/models/load" else "unloaded"
                return self._send({"success": True})
            if self.path == "/crash":
                print("ggml_vulkan: device lost", flush=True)
                os._exit(3)
            if self.path == "/v1/chat/completions":
                states[name] = "loaded"
                return self._send(
                    {
                        "model": name,
                        "choices": [
                            {
                                "message": {"content": f"Hi from {name}."},
                                "finish_reason": "stop",
                            }
                        ],
                        "timings": {
                            "prompt_per_second": 250.0,
                            "predicted_per_second": 42.5,
                            "predicted_n": 5,
                        },
                    }
                )
            return self._send({"error": "not found"}, 404)

    print(f"fake llama-server on {args.port} with {models}", flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
