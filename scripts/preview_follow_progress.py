#!/usr/bin/env python3
"""隔离的 iOS 进度卡验收服务；仅合成任务，不读健康库、不连接 DSH。"""
import json
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pivis_health.config import Config
from pivis_health import web


def main():
    with tempfile.TemporaryDirectory(prefix="phealth-progress-review-") as home:
        cfg = Config(data_dir=Path(home), follow_enabled=True, sim_mode=True)
        tools = SimpleNamespace(cfg=cfg, _now=lambda: datetime.now().astimezone())
        path = cfg.data_dir / "follow/jobs/jreview.json"
        path.parent.mkdir(parents=True)
        started = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 125))

        def update(state):
            values = {
                "voice": {"state": "running", "step": "配音", "progress": 0.62},
                "render": {"state": "running", "step": "出片 80%", "progress": 0.82},
                "done": {"state": "done", "progress": 1, "result": {"verify_ok": True}},
                "rejected": {"state": "done", "progress": 1, "result": {"verify_ok": False}},
                "failed": {"state": "failed", "progress": 0.72},
            }
            path.write_text(json.dumps({"started": started, **values[state]}))
        update("voice")
        base = web.make_handler(cfg, tools)

        class Handler(base):
            offline = False

            def do_POST(self):
                if self.path.startswith("/test/"):
                    state = self.path.rsplit("/", 1)[-1]
                    if state in ("offline", "online"):
                        type(self).offline = state == "offline"
                    elif state in ("voice", "render", "done", "rejected", "failed"):
                        update(state)
                    else:
                        self._json({"error": "not_found"}, 404)
                        return
                    self._json({"ok": True})
                elif self.offline:
                    self._json({"error": "temporarily_unavailable"}, 503)
                else:
                    super().do_POST()

        port = int(sys.argv[1]) if len(sys.argv) > 1 else 18959
        server = web.QuietServer(("127.0.0.1", port), Handler)
        print(f"Synthetic progress review ready on loopback port {port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
