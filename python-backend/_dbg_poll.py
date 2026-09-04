import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core.logger import get_logger
from app.services import videoClient as vc

log = get_logger("lmd.dbg")

cfg = {"provider": "kling", "base_url": "https://api.klingai.com", "api_key": "k"}
body = {"code": 1001, "message": "鉴权失败"}


def fetch(url, headers):
    return 200, json.dumps(body)


# 临时把 except 里的 error 打出来：直接调用内部逻辑定位
try:
    out = vc.poll_video_task(log, 1, "t2v:a", cfg, max_attempts=1, interval_ms=0, fetch_json=fetch)
    print("OUT:", out)
except Exception as e:
    import traceback
    traceback.print_exc()
