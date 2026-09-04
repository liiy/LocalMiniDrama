"""分镜首帧/尾帧参考图与 storyboards、image_generations 的绑定。
契约与逻辑严格对齐 backend-node/src/services/storyboardFrameBinding.js。

frame_type: storyboard_first | storyboard_last | first | last | tail | null（null 视为首帧/主图，兼容旧数据）
"""
from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.response import timestamp
from app.db.session import execute

log = get_logger("lmd.storyboardFrameBinding")


def bind_storyboard_frame_image(
    db: Session,
    storyboard_id: Any,
    frame_type: Any,
    image_gen_id: Any,
    image_url: Any,
    local_path: Any,
) -> None:
    """等价 Node bindStoryboardFrameImage。

    绑定首帧/主图或尾帧参考图至 storyboards 表。
    """
    if storyboard_id is None:
        return
    try:
        sid = int(storyboard_id)
    except (ValueError, TypeError):
        return

    now = timestamp()
    url = str(image_url).strip() if image_url is not None and str(image_url).strip() else None
    lp = str(local_path).strip() if local_path is not None and str(local_path).strip() else None

    ig_id: int | None = None
    if image_gen_id is not None:
        try:
            ig_id = int(image_gen_id)
        except (ValueError, TypeError):
            ig_id = None

    ft = str(frame_type).strip() if frame_type is not None and str(frame_type).strip() else None
    # 归一化常见别名，确保尾帧能正确路由
    if ft in ("storyboard_last", "tail", "last_frame"):
        ft = "last"
    if ft in ("storyboard_first", "first_frame"):
        ft = "first"

    is_last = ft == "last"
    if is_last:
        execute(
            db,
            """UPDATE storyboards
               SET last_frame_image_url = :url,
                   last_frame_local_path = :lp,
                   last_frame_image_id = :ig_id,
                   updated_at = :now
               WHERE id = :sid AND deleted_at IS NULL""",
            {"url": url, "lp": lp, "ig_id": ig_id, "now": now, "sid": sid},
        )
        log.info(
            "[绑定] 尾帧图片已正确绑定到 storyboards.last_frame_*（不会污染主图或历史）",
            extra={"storyboard_id": sid, "image_gen_id": ig_id},
        )
        return

    # 首帧或普通分镜图：写入主图/首帧字段
    execute(
        db,
        """UPDATE storyboards
           SET image_url = :url,
               local_path = :lp,
               first_frame_image_id = :ig_id,
               updated_at = :now
           WHERE id = :sid AND deleted_at IS NULL""",
        {"url": url, "lp": lp, "ig_id": ig_id, "now": now, "sid": sid},
    )
    log.info(
        "[绑定] 首帧/主图已正确绑定到 storyboards",
        extra={"storyboard_id": sid, "image_gen_id": ig_id},
    )
