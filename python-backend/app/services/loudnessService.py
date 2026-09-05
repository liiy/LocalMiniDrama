"""音频响度测量与智能归一化服务（Loudness Normalization & Multi-track Mixer）。
支持：
1. 集成 pyloudnorm / FFmpeg loudnorm 滤镜进行音频响度测量与目标 EBU R128 (-23 LUFS / -16 LUFS) 响度调平；
2. 对白、旁白、BGM 与音效 (SFX) 多轨智能压制 (Audio Ducking) 与响度平衡，避免 BGM 压住人声。
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Any
from pathlib import Path

from app.core.logger import get_logger
from app.utils.ffmpegPath import get_ffmpeg_path, get_ffprobe_path

log = get_logger("lmd.loudnorm")

TARGET_LUFS_STANDARD = -16.0  # 互联网短视频/短剧标准响度目标 (LUFS)
TARGET_LRA_STANDARD = 7.0     # 响度范围 (Loudness Range)
TARGET_TP_STANDARD = -1.5     # 真实峰值上限 (True Peak, dBTP)


def normalize_audio_loudness(
    input_path: str,
    output_path: str,
    target_lufs: float = TARGET_LUFS_STANDARD,
    target_tp: float = TARGET_TP_STANDARD,
    target_lra: float = TARGET_LRA_STANDARD,
) -> bool:
    """使用 FFmpeg loudnorm 滤镜或 pyloudnorm 对单轨音频进行双通道 EBU R128 响度归一化。"""
    if not os.path.exists(input_path):
        log.warning("Audio file does not exist: %s", input_path)
        return False

    # 优先尝试使用 pyloudnorm (若已安装并支持 numpy/soundfile)
    try:
        import soundfile as sf
        import pyloudnorm as pyln
        data, rate = sf.read(input_path)
        meter = pyln.Meter(rate)  # 创建 BS.1770 计量器
        loudness = meter.integrated_loudness(data)
        # 响度归一化
        normalized_audio = pyln.normalize.loudness(data, loudness, target_lufs)
        sf.write(output_path, normalized_audio, rate)
        log.info(f"Normalized audio via pyloudnorm: {input_path} -> {output_path} (original={loudness:.2f} LUFS, target={target_lufs} LUFS)")
        return True
    except Exception:
        # Fallback 到 FFmpeg 的 loudnorm 滤镜
        pass

    bin_path = get_ffmpeg_path()
    try:
        loudnorm_filter = f"loudnorm=I={target_lufs}:TP={target_tp}:LRA={target_lra}"
        args = [
            bin_path,
            "-y",
            "-i", input_path,
            "-af", loudnorm_filter,
            "-c:a", "libmp3lame",
            "-q:a", "2",
            output_path,
        ]
        res = subprocess.run(args, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            log.warning("FFmpeg loudnorm failed: %s", res.stderr[-500:] if res.stderr else "")
            return False
        return os.path.exists(output_path)
    except Exception as e:
        log.error("Failed to run loudnorm: %s", e)
        return False


def mix_multitrack_with_ducking(
    voice_audio_path: str | None,
    bgm_audio_path: str | None,
    sfx_audio_path: str | None,
    output_path: str,
    target_duration: float,
    bgm_volume: float = 0.35,
    ducking_attenuation_db: float = -12.0,
) -> bool:
    """多轨智能混音与 Audio Ducking：当存在人声对白时，自动侧链压缩 (sidechaincompress) 调低 BGM 音量。"""
    bin_path = get_ffmpeg_path()
    inputs = []
    filter_complex_parts = []

    has_voice = bool(voice_audio_path and os.path.exists(voice_audio_path))
    has_bgm = bool(bgm_audio_path and os.path.exists(bgm_audio_path))
    has_sfx = bool(sfx_audio_path and os.path.exists(sfx_audio_path))

    if not has_voice and not has_bgm and not has_sfx:
        log.warning("No audio tracks provided for mixing")
        return False

    if has_voice and not has_bgm and not has_sfx:
        # 单独为人声进行响度归一化并输出
        return normalize_audio_loudness(voice_audio_path, output_path)

    # 构建多输入参数与滤镜图
    idx = 0
    voice_idx = None
    bgm_idx = None
    sfx_idx = None

    if has_voice:
        inputs.extend(["-i", voice_audio_path])
        voice_idx = idx
        idx += 1
    if has_bgm:
        inputs.extend(["-i", bgm_audio_path])
        bgm_idx = idx
        idx += 1
    if has_sfx:
        inputs.extend(["-i", sfx_audio_path])
        sfx_idx = idx
        idx += 1

    mix_inputs_count = idx
    # 如果既有人声又有 BGM，应用 sidechaincompress 或 volume ducking
    if has_voice and has_bgm:
        # [bgm]volume + [voice]sidechain
        filter_str = (
            f"[{bgm_idx}:a]volume={bgm_volume}[bgm_vol];"
            f"[{bgm_vol}][{voice_idx}:a]sidechaincompress=threshold=0.12:ratio=4:attack=20:release=350[bgm_ducked];"
        )
        if has_sfx:
            filter_str += f"[{voice_idx}:a][bgm_ducked][{sfx_idx}:a]amix=inputs=3:duration=first:dropout_transition=2[mixed];[mixed]loudnorm=I={TARGET_LUFS_STANDARD}[aout]"
        else:
            filter_str += f"[{voice_idx}:a][bgm_ducked]amix=inputs=2:duration=first:dropout_transition=2[mixed];[mixed]loudnorm=I={TARGET_LUFS_STANDARD}[aout]"
    else:
        # 无需侧链的普通 amix
        amix_ins = "".join(f"[{i}:a]" for i in range(mix_inputs_count))
        filter_str = f"{amix_ins}amix=inputs={mix_inputs_count}:duration=first:dropout_transition=2[mixed];[mixed]loudnorm=I={TARGET_LUFS_STANDARD}[aout]"

    args = [
        bin_path,
        "-y",
        *inputs,
        "-filter_complex", filter_str,
        "-map", "[aout]",
        "-t", str(target_duration),
        "-c:a", "libmp3lame",
        "-q:a", "2",
        output_path,
    ]

    try:
        res = subprocess.run(args, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            log.warning("Multi-track ducking mix failed: %s", res.stderr[-500:] if res.stderr else "")
            return False
        return os.path.exists(output_path)
    except Exception as e:
        log.error("Failed to run multi-track mix: %s", e)
        return False
