"""/api/v1/audio/* — 契约精确翻译 backend-node/src/routes/audio.js。

端点：
- POST /audio/extract        单条分镜 TTS（对白 → audio_local_path；旁白 → narration_audio_local_path）
- POST /audio/extract/batch  批量分镜 TTS（恒取对白字段）

Node 行为要点：
- 文本回退：body.text 为空时按 storyboard_id 从 storyboards 读取 dialogue / narration
- tts_kind: String(tts_kind || 'dialogue').toLowerCase() === 'narration' → narration，其余一律 dialogue
- storageBase 直接用 getStoragePath()（与 /upload/image 不同，**不做** projects/ 分层，落盘为 audio/ 平铺）
- 写库失败被 Node 的 try/catch(_) 静默吞掉，响应仍为成功（此处用 SAVEPOINT 复刻，
  避免 SQLAlchemy 因语句失败把整个事务置为需回滚状态）
- url 由固定前缀 '/static/' 拼接（不读配置 base_url）
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.core import config as cfgmod
from app.core.logger import get_logger
from app.core.response import HttpError, bad_request, success, timestamp
from app.db.session import execute, fetch_one, get_db
from app.services import ttsService
from app.services.libraryCommon import to_int_id

router = APIRouter(tags=["audio"])
log = get_logger("lmd.audio")

# 内存态配置（等价 Node app.js 启动时 loadConfig 一次并闭包传递）
_CFG: dict[str, Any] = {}


def init_config(cfg: dict[str, Any]) -> None:
    global _CFG
    _CFG = cfg


def _safe_update(db: Session, sql: str, params: dict) -> None:
    """等价 Node 的 try { db.prepare(...).run() } catch (_) {}。

    用 SAVEPOINT 包裹：语句失败只回滚该保存点，外层事务仍可提交，响应依旧成功。
    """
    try:
        with db.begin_nested():
            execute(db, sql, params)
    except Exception as e:
        log.warning("audio: 写回分镜音频路径失败（已忽略）", extra={"error": str(e)})


def _storage_base() -> str:
    return str(cfgmod.storage_local_path(_CFG))


def _normalize_kind(tts_kind: Any) -> str:
    """Node: String(tts_kind || 'dialogue').toLowerCase() === 'narration'。"""
    return "narration" if str(tts_kind or "dialogue").lower() == "narration" else "dialogue"


def _is_blank(v: Any) -> bool:
    return not v or not str(v).strip()


@router.post("/audio/extract")
def extract(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    body = payload or {}
    storyboard_id = body.get("storyboard_id")
    text = body.get("text")
    tts_kind = body.get("tts_kind")

    if not text and not storyboard_id:
        raise bad_request("请提供 storyboard_id 或 text")

    kind = _normalize_kind(tts_kind)
    tts_text = text

    if kind == "narration":
        if _is_blank(tts_text) and storyboard_id:
            row = fetch_one(
                db,
                "SELECT narration FROM storyboards WHERE id = :id AND deleted_at IS NULL",
                {"id": to_int_id(storyboard_id)},
            )
            tts_text = row.get("narration") if row else None
        if _is_blank(tts_text):
            raise bad_request("分镜解说旁白为空，无法合成语音")
    else:
        if _is_blank(tts_text) and storyboard_id:
            row = fetch_one(
                db,
                "SELECT dialogue FROM storyboards WHERE id = :id AND deleted_at IS NULL",
                {"id": to_int_id(storyboard_id)},
            )
            tts_text = row.get("dialogue") if row else None
        if _is_blank(tts_text):
            raise bad_request("分镜对白为空，无法合成语音")

    try:
        result = ttsService.synthesize(
            db,
            log,
            {
                "text": tts_text,
                "storyboard_id": storyboard_id or None,
                "storage_base": _storage_base(),
            },
        )
        local_path = result.get("local_path")

        if storyboard_id and local_path:
            column = "narration_audio_local_path" if kind == "narration" else "audio_local_path"
            _safe_update(
                db,
                f"UPDATE storyboards SET {column} = :path, updated_at = :updated_at WHERE id = :id",
                {"path": local_path, "updated_at": timestamp(), "id": to_int_id(storyboard_id)},
            )
    except HttpError:
        raise
    except Exception as e:
        log.error("audio extract", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", str(e)) from e

    return success(
        {
            "local_path": local_path,
            "url": f"/static/{local_path}" if local_path else "",
            "tts_kind": kind,
        }
    )


@router.post("/audio/extract/batch")
def extract_batch(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    body = payload or {}
    storyboard_ids = body.get("storyboard_ids")
    if not isinstance(storyboard_ids, list) or len(storyboard_ids) == 0:
        raise bad_request("storyboard_ids 不能为空")

    storage_base = _storage_base()
    results: list[dict] = []

    for sb_id in storyboard_ids:
        row = fetch_one(
            db,
            "SELECT id, dialogue FROM storyboards WHERE id = :id AND deleted_at IS NULL",
            {"id": to_int_id(sb_id)},
        )
        dialogue = (row or {}).get("dialogue")
        if not row or not (dialogue and str(dialogue).strip()):
            results.append({"storyboard_id": sb_id, "error": "对白为空"})
            continue
        try:
            result = ttsService.synthesize(
                db,
                log,
                {"text": dialogue, "storyboard_id": row["id"], "storage_base": storage_base},
            )
            local_path = result.get("local_path")
            if local_path:
                _safe_update(
                    db,
                    "UPDATE storyboards SET audio_local_path = :path, updated_at = :updated_at WHERE id = :id",
                    {"path": local_path, "updated_at": timestamp(), "id": row["id"]},
                )
            results.append({"storyboard_id": sb_id, "local_path": local_path})
        except Exception as e:
            results.append({"storyboard_id": sb_id, "error": str(e)})

    return success(results)
