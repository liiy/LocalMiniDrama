"""解析 ffmpeg / ffprobe 可执行路径。查找优先级：
1. 环境变量 FFMPEG_PATH / FFPROBE_PATH
2. os.getcwd()/tools/ffmpeg/  ← 打包后 cwd = userData/backend，用户可在此放置 ffmpeg
3. sys.executable 同级目录/tools/ffmpeg/   ← 用户把 ffmpeg 放在 exe 旁边的 tools/ffmpeg 目录
4. sys.executable 同级目录（直接放在 exe 旁边）
5. 源码目录 python-backend/tools/ffmpeg/ 或 backend-node/tools/ffmpeg/（开发时）
6. 系统 PATH 中的 ffmpeg（兜底）
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

IS_WIN = sys.platform == "win32"
FFMPEG_NAME = "ffmpeg.exe" if IS_WIN else "ffmpeg"
FFPROBE_NAME = "ffprobe.exe" if IS_WIN else "ffprobe"

# python-backend 根目录
BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
TOOLS_FFMPEG_DIR = BACKEND_ROOT / "tools" / "ffmpeg"


def get_candidate_paths(name: str) -> list[Path]:
    """返回所有候选查找路径（按优先级排列，不含环境变量）。"""
    candidates: list[Path] = []
    # 1. cwd / tools / ffmpeg
    try:
        candidates.append(Path.cwd() / "tools" / "ffmpeg" / name)
    except Exception:
        pass

    # 2. exe 同级/tools/ffmpeg 及 exe 同级直接放
    try:
        exe_dir = Path(sys.executable).parent
        candidates.append(exe_dir / "tools" / "ffmpeg" / name)
        candidates.append(exe_dir / name)
    except Exception:
        pass

    # 3. 本服务 tools/ffmpeg（开发时）
    candidates.append(TOOLS_FFMPEG_DIR / name)

    # 4. 项目根目录下的 tools/ffmpeg 或 backend-node/tools/ffmpeg
    repo_root = BACKEND_ROOT.parent
    if (repo_root / "tools" / "ffmpeg" / name).exists():
        candidates.append(repo_root / "tools" / "ffmpeg" / name)
    if (repo_root / "backend-node" / "tools" / "ffmpeg" / name).exists():
        candidates.append(repo_root / "backend-node" / "tools" / "ffmpeg" / name)

    return candidates


def resolve_ffmpeg_bin(name: str) -> str:
    """按优先级解析二进制路径；若未命中则返回 name（由系统 PATH 兜底）。"""
    env_var = "FFMPEG_PATH" if name == FFMPEG_NAME else "FFPROBE_PATH"
    from_env = os.environ.get(env_var, "").strip()
    if from_env and os.path.exists(from_env):
        return from_env

    for p in get_candidate_paths(name):
        if p.exists() and p.is_file():
            return str(p)

    which_path = shutil.which(name)
    if which_path:
        return which_path

    return name


def get_ffmpeg_path() -> str:
    """返回 ffmpeg 可执行路径。"""
    return resolve_ffmpeg_bin(FFMPEG_NAME)


def get_ffprobe_path() -> str:
    """返回 ffprobe 可执行路径。"""
    return resolve_ffmpeg_bin(FFPROBE_NAME)


def has_local_ffmpeg() -> bool:
    """是否能找到本地 ffmpeg（找到任意候选路径、环境变量或系统 PATH 中存在即为 true）。"""
    from_env = os.environ.get("FFMPEG_PATH", "").strip()
    if from_env and os.path.exists(from_env):
        return True

    for p in get_candidate_paths(FFMPEG_NAME):
        if p.exists() and p.is_file():
            return True

    if shutil.which(FFMPEG_NAME):
        return True

    try:
        res = subprocess.run(
            [FFMPEG_NAME, "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=5,
        )
        if res.returncode == 0:
            return True
    except Exception:
        pass

    return False
