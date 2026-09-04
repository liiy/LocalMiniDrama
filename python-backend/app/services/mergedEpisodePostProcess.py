"""整集合并后的后处理：对白 TTS 轨、解说旁白轨+SRT、右下角文字水印（可组合）。

严格对应 backend-node/src/services/mergedEpisodePostProcess.js。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db.session import fetch_one
from app.services import ttsService
from app.utils.ffmpegPath import get_ffmpeg_path, get_ffprobe_path


def ffprobe_duration_sec(file_path: str) -> float | None:
    probe = get_ffprobe_path()
    try:
        r = subprocess.run(
            [probe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", file_path],
            capture_output=True,
            text=True,
            check=False,
        )
        if r.returncode != 0:
            return None
        out = (r.stdout or "").strip()
        val = float(out)
        return val if val > 0 else None
    except Exception:
        return None


def format_srt_timestamp(ms: float | int) -> str:
    if ms is None or ms < 0:
        ms = 0
    ms = int(ms)
    h = ms // 3600000
    m = (ms % 3600000) // 60000
    s = (ms % 60000) // 1000
    z = ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{z:03d}"


def build_atempo_chain(factor: float) -> str | None:
    if factor is None or factor <= 0:
        return None
    if abs(factor - 1.0) < 0.002:
        return None
    parts: list[str] = []
    f = factor
    while f > 2.001:
        parts.append("atempo=2")
        f /= 2.0
    while f < 0.499:
        parts.append("atempo=0.5")
        f /= 0.5
    parts.append(f"atempo={min(2.0, max(0.5, f)):.4f}")
    return ",".join(parts)


def escape_ffmpeg_path(abs_path: str) -> str:
    s = Path(abs_path).resolve().as_posix()
    if len(s) >= 2 and s[1] == ":":
        s = s[0] + "\\:" + s[2:]
    return s.replace("'", "\\'")


def run_ffmpeg(args: list[str], log: Any, tag: str) -> bool:
    bin_path = get_ffmpeg_path()
    try:
        r = subprocess.run(
            [bin_path, *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if r.returncode != 0:
            stderr_snippet = (r.stderr or "")[-1000:]
            if log:
                log.warn("merged post: ffmpeg failed", extra={"tag": tag, "stderr": stderr_snippet})
            return False
        return True
    except Exception as e:
        if log:
            log.warn("merged post: ffmpeg spawn", extra={"tag": tag, "error": str(e)})
        return False


def write_silence_mp3(slot_sec: float, out_path: str, log: Any) -> bool:
    return run_ffmpeg(
        ["-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", str(slot_sec), "-c:a", "libmp3lame", "-q:a", "6", out_path],
        log,
        "silence",
    )


def fit_audio_to_slot(input_path: str, slot_sec: float, out_path: str, log: Any) -> bool:
    d = ffprobe_duration_sec(input_path)
    if d is None or d <= 0.01:
        return False
    eps = 0.06
    if d > slot_sec + eps:
        factor = d / slot_sec
        chain = build_atempo_chain(factor)
        af = chain or "anull"
        return run_ffmpeg(
            ["-y", "-i", input_path, "-af", af, "-t", str(slot_sec), "-c:a", "libmp3lame", "-q:a", "4", out_path],
            log,
            "fit_speed",
        )
    if d < slot_sec - eps:
        pad = slot_sec - d
        return run_ffmpeg(
            ["-y", "-i", input_path, "-af", f"apad=pad_dur={pad}", "-t", str(slot_sec), "-c:a", "libmp3lame", "-q:a", "4", out_path],
            log,
            "fit_pad",
        )
    try:
        shutil.copyfile(input_path, out_path)
        return True
    except Exception:
        return run_ffmpeg(
            ["-y", "-i", input_path, "-t", str(slot_sec), "-c:a", "libmp3lame", "-q:a", "4", out_path],
            log,
            "fit_copy",
        )


def concat_mp3_list(segment_paths: list[str], out_path: str, log: Any) -> bool:
    out_dir = os.path.dirname(out_path)
    list_file = os.path.join(out_dir, f"mix_concat_{int(time.time() * 1000)}.txt")
    try:
        lines = []
        for p in segment_paths:
            norm = Path(p).resolve().as_posix()
            escaped = norm.replace("'", "'\\''")
            lines.append(f"file '{escaped}'")
        with open(list_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return run_ffmpeg(
            ["-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c:a", "libmp3lame", "-q:a", "4", out_path],
            log,
            "concat_mix",
        )
    finally:
        try:
            if os.path.exists(list_file):
                os.remove(list_file)
        except Exception:
            pass


def align_audio_to_video_duration(in_mp3: str, video_dur: float, out_path: str, log: Any) -> bool:
    n = ffprobe_duration_sec(in_mp3)
    if n is None or video_dur <= 0.1:
        return False
    eps = 0.08
    if n > video_dur + eps:
        factor = n / video_dur
        chain = build_atempo_chain(factor)
        if not chain:
            try:
                shutil.copyfile(in_mp3, out_path)
                return True
            except Exception:
                return False
        return run_ffmpeg(
            ["-y", "-i", in_mp3, "-af", chain, "-t", str(video_dur), "-c:a", "libmp3lame", "-q:a", "4", out_path],
            log,
            "align_speed",
        )
    if n < video_dur - eps:
        pad = video_dur - n
        return run_ffmpeg(
            ["-y", "-i", in_mp3, "-af", f"apad=pad_dur={pad}", "-t", str(video_dur), "-c:a", "libmp3lame", "-q:a", "4", out_path],
            log,
            "align_pad",
        )
    try:
        shutil.copyfile(in_mp3, out_path)
        return True
    except Exception:
        return False


def amix_two_tracks(path_a: str, path_b: str, slot_sec: float, out_path: str, log: Any) -> bool:
    return run_ffmpeg(
        [
            "-y", "-i", path_a, "-i", path_b,
            "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=2[aout]",
            "-map", "[aout]",
            "-t", str(slot_sec),
            "-c:a", "libmp3lame", "-q:a", "4",
            out_path,
        ],
        log,
        "amix_seg",
    )


def get_drawtext_font_option() -> str:
    candidates = []
    if sys.platform == "win32":
        root = os.environ.get("SystemRoot") or "C:\\Windows"
        candidates.extend([
            os.path.join(root, "Fonts", "msyh.ttc"),
            os.path.join(root, "Fonts", "msyhbd.ttc"),
            os.path.join(root, "Fonts", "simhei.ttf"),
        ])
    candidates.extend(["/System/Library/Fonts/PingFang.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"])
    for p in candidates:
        if p and os.path.exists(p):
            return f":fontfile='{escape_ffmpeg_path(p)}'"
    return ""


def ffprobe_has_audio(file_path: str) -> bool:
    probe = get_ffprobe_path()
    try:
        r = subprocess.run(
            [probe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", file_path],
            capture_output=True,
            text=True,
            check=False,
        )
        return r.returncode == 0 and len((r.stdout or "").strip()) > 0
    except Exception:
        return False


def run_merged_episode_post_process(db: Session, log: Any, opts: dict[str, Any]) -> dict[str, Any]:
    """等价 Node runMergedEpisodePostProcess。

    opts 包含:
      mergedAbsPath: 合并后的绝对路径
      storageRoot: 存储根目录绝对路径
      scenes: 分镜列表 [{scene_id, duration}, ...]
      episodeId: 剧集 ID
      mergeOpts: { burn_dialogue_audio, burn_narration_subtitles, watermark_text }
    """
    merged_abs_path = opts.get("mergedAbsPath") or opts.get("merged_abs_path")
    storage_root = opts.get("storageRoot") or opts.get("storage_root")
    scenes = opts.get("scenes")
    episode_id = opts.get("episodeId") or opts.get("episode_id")
    merge_opts = opts.get("mergeOpts") or opts.get("merge_opts") or {}

    want_dial = bool(merge_opts.get("burn_dialogue_audio"))
    want_narr = bool(merge_opts.get("burn_narration_subtitles"))
    raw_wm = merge_opts.get("watermark_text")
    watermark_text = str(raw_wm).strip()[:200] if raw_wm and str(raw_wm).strip() else ""

    if not merged_abs_path or not os.path.exists(merged_abs_path) or not isinstance(scenes, list) or len(scenes) == 0:
        return {"ok": False, "error": "无效合成参数"}

    need_audio = want_dial or want_narr
    if not need_audio and not watermark_text:
        return {"ok": False, "error": "NO_POST_OPTS"}

    video_dur = ffprobe_duration_sec(merged_abs_path)
    if video_dur is None:
        return {"ok": False, "error": "无法读取合成视频时长"}

    temp_root = os.path.join(tempfile.gettempdir(), "drama-merged-post", str(episode_id or 0), str(int(time.time() * 1000)))
    os.makedirs(temp_root, exist_ok=True)

    try:
        aligned_audio_path = None
        srt_path = None
        srt_lines: list[str] = []

        if need_audio:
            t_ms = 0
            srt_idx = 1
            segment_files: list[str] = []

            for i, sc in enumerate(scenes):
                sb_id = int(sc.get("scene_id") or 0)
                slot_sec = max(0.2, float(sc.get("duration") or 5))
                row = fetch_one(
                    db,
                    "SELECT dialogue, narration, audio_local_path, narration_audio_local_path FROM storyboards WHERE id = :id AND deleted_at IS NULL",
                    {"id": sb_id},
                )

                narr_text = str(row.get("narration") or "").strip() if row and row.get("narration") else ""
                if want_narr and narr_text:
                    dur_ms = round(slot_sec * 1000)
                    srt_lines.extend([
                        str(srt_idx),
                        f"{format_srt_timestamp(t_ms)} --> {format_srt_timestamp(t_ms + dur_ms)}",
                        narr_text,
                        "",
                    ])
                    srt_idx += 1
                t_ms += round(slot_sec * 1000)

                dia_fit = os.path.join(temp_root, f"dia_fit_{i}.mp3")
                narr_fit = os.path.join(temp_root, f"narr_fit_{i}.mp3")
                seg_out = os.path.join(temp_root, f"seg_mix_{i}.mp3")

                if want_dial:
                    rel = str(row.get("audio_local_path") or "").strip() if row and row.get("audio_local_path") else ""
                    src_abs = os.path.join(storage_root, *rel.split("/")) if rel else None
                    if src_abs and os.path.exists(src_abs):
                        if not fit_audio_to_slot(src_abs, slot_sec, dia_fit, log):
                            return {"ok": False, "error": f"对白配音时长对齐失败 #{i}"}
                    elif not write_silence_mp3(slot_sec, dia_fit, log):
                        return {"ok": False, "error": f"对白静音片段失败 #{i}"}

                if want_narr:
                    if not narr_text:
                        if not write_silence_mp3(slot_sec, narr_fit, log):
                            return {"ok": False, "error": f"旁白静音片段失败 #{i}"}
                    else:
                        seg_raw = os.path.join(temp_root, f"narr_raw_{i}.mp3")
                        try:
                            synth = ttsService.synthesize(
                                db,
                                log,
                                {
                                    "text": narr_text,
                                    "storyboard_id": None,
                                    "storage_base": storage_root,
                                },
                            )
                        except Exception as e:
                            if log:
                                log.warn("merged post: narration TTS failed", extra={"segment": i, "error": str(e)})
                            return {"ok": False, "error": f"解说旁白 TTS 失败：{e}"}
                        narr_abs = os.path.join(storage_root, *str(synth.get("local_path") or "").split("/"))
                        if not os.path.exists(narr_abs):
                            return {"ok": False, "error": "旁白 TTS 文件不存在"}
                        try:
                            shutil.copyfile(narr_abs, seg_raw)
                        except Exception:
                            return {"ok": False, "error": "复制旁白 TTS 失败"}
                        if not fit_audio_to_slot(seg_raw, slot_sec, narr_fit, log):
                            return {"ok": False, "error": f"旁白时长对齐失败 #{i}"}

                if want_dial and want_narr:
                    if not amix_two_tracks(dia_fit, narr_fit, slot_sec, seg_out, log):
                        return {"ok": False, "error": f"对白与旁白混音失败 #{i}"}
                elif want_dial:
                    try:
                        shutil.copyfile(dia_fit, seg_out)
                    except Exception:
                        return {"ok": False, "error": f"对白片段复制失败 #{i}"}
                elif want_narr:
                    try:
                        shutil.copyfile(narr_fit, seg_out)
                    except Exception:
                        return {"ok": False, "error": f"旁白片段复制失败 #{i}"}

                segment_files.append(seg_out)

            concat_out = os.path.join(temp_root, "full_mix.mp3")
            if not concat_mp3_list(segment_files, concat_out, log):
                return {"ok": False, "error": "音轨拼接失败"}

            aligned_audio_path = os.path.join(temp_root, "aligned_mix.mp3")
            if not align_audio_to_video_duration(concat_out, video_dur, aligned_audio_path, log):
                return {"ok": False, "error": "音轨与视频总时长对齐失败"}

            if want_narr and srt_lines:
                stem = Path(merged_abs_path).stem
                srt_path = os.path.join(os.path.dirname(merged_abs_path), f"{stem}_narration.srt")
                with open(srt_path, "w", encoding="utf-8-sig") as f:
                    f.write("\n".join(srt_lines) + "\n")

        stem = Path(merged_abs_path).stem
        out_abs = os.path.join(os.path.dirname(merged_abs_path), f"{stem}_post.mp4")

        has_subs = bool(srt_path and os.path.exists(srt_path))
        has_wm = bool(watermark_text)

        vf_parts: list[str] = []
        if has_subs and srt_path:
            sub_esc = escape_ffmpeg_path(srt_path)
            vf_parts.append(f"subtitles='{sub_esc}':charenc=UTF-8")
        if has_wm:
            wm_file = os.path.join(temp_root, "watermark.txt")
            with open(wm_file, "w", encoding="utf-8") as f:
                f.write(watermark_text)
            wm_esc = escape_ffmpeg_path(wm_file)
            font_opt = get_drawtext_font_option()
            vf_parts.append(
                f"drawtext=textfile='{wm_esc}':reload=1{font_opt}:x=w-tw-16:y=h-th-16:fontsize=22:fontcolor=white@0.82:borderw=2:bordercolor=black@0.55"
            )

        filter_complex = ""
        if len(vf_parts) == 1:
            filter_complex = f"[0:v]{vf_parts[0]}[vout]"
        elif len(vf_parts) == 2:
            filter_complex = f"[0:v]{vf_parts[0]}[vx];[vx]{vf_parts[1]}[vout]"

        if need_audio:
            if not aligned_audio_path or not os.path.exists(aligned_audio_path):
                return {"ok": False, "error": "内部错误：缺少对齐音轨"}
            args = ["-y", "-i", merged_abs_path, "-i", aligned_audio_path]
            if filter_complex:
                args.extend(["-filter_complex", filter_complex, "-map", "[vout]", "-map", "1:a"])
            else:
                args.extend(["-map", "0:v", "-map", "1:a"])
            args.extend([
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", out_abs,
            ])
            if not run_ffmpeg(args, log, "mux_av"):
                return {"ok": False, "error": "烧录字幕/水印或混音失败（请确认 ffmpeg 含 libx264）"}
        else:
            if not filter_complex:
                return {"ok": False, "error": "内部错误：仅水印但无滤镜链"}
            args = ["-y", "-i", merged_abs_path, "-filter_complex", filter_complex, "-map", "[vout]"]
            if ffprobe_has_audio(merged_abs_path):
                args.extend(["-map", "0:a", "-c:a", "copy"])
            else:
                args.append("-an")
            args.extend(["-c:v", "libx264", "-preset", "fast", "-crf", "23", "-movflags", "+faststart", out_abs])
            if not run_ffmpeg(args, log, "watermark_only"):
                return {"ok": False, "error": "水印烧录失败"}

        if not os.path.exists(out_abs):
            return {"ok": False, "error": "输出文件未生成"}

        rel_from_root = Path(out_abs).resolve().relative_to(Path(storage_root).resolve()).as_posix()

        try:
            if os.path.exists(merged_abs_path) and out_abs != merged_abs_path:
                os.remove(merged_abs_path)
        except Exception as e:
            if log:
                log.warn("merged post: could not remove intermediate", extra={"error": str(e)})

        if log:
            log.info("merged post: done", extra={"episode_id": episode_id, "video": rel_from_root})
        return {"ok": True, "relativePath": rel_from_root}

    except Exception as e:
        if log:
            log.warn("merged post: exception", extra={"error": str(e)})
        return {"ok": False, "error": str(e)}
    finally:
        try:
            shutil.rmtree(temp_root, ignore_errors=True)
        except Exception:
            pass
