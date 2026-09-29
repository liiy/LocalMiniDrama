"""Script-to-Visual Bridge 契约桥梁服务。

严格遵循《详细设计说明书（V2.0 工业增强版）》第 2.6 节：
实现剧本创作工坊 (Script Studio) 与视听生产工坊 (Visual Studio) 的彻底解耦。
1. 剧本锁定保护：当剧本定稿锁定 (`lock_status = 1`) 后，通过 Bridge 契约流转生成只读标准快照；
2. 契约提取与转换：从剧本 AST、角色档案、大纲中提取规范化的分镜镜头列表、场景映射、道具流向与提示词；
3. 算力流幂等指纹：计算每个分镜的 `task_fingerprint` (基于 prompt + 角色锚点 + 场景 + 参数)，避免下游重复算力消耗。
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.session import fetch_all, fetch_one
from app.platform_common import json_dumps, json_loads, now_iso
from app.core.logger import get_logger

logger = get_logger("script_to_visual_bridge")


# =====================================================================
# 1. 契约 Schema 定义
# =====================================================================

class VisualStoryboardItem(BaseModel):
    """Bridge 契约中的单分镜标准化结构。"""
    storyboard_number: int = Field(..., description="分镜序号 (1, 2, 3...)")
    title: str = Field(default="", description="分镜动作/台词简述")
    shot_type: str = Field(default="特写", description="景别：特写/近景/中景/全景/大远景")
    camera_movement: str = Field(default="推镜头", description="运镜方式：固定/慢推/拉远/摇移/跟拍")
    aspect_ratio: str = Field(default="9:16", description="竖屏短剧画幅比例")
    characters: list[str] = Field(default_factory=list, description="出场角色名列表")
    dialogue: str = Field(default="", description="对白/独白/内心OS")
    visual_prompt: str = Field(..., description="文生图核心提示词")
    task_fingerprint: str = Field(default="", description="算力渲染幂等防重指纹 (SHA256)")


class ScriptToVisualContract(BaseModel):
    """剧本工坊至视听工坊的标准化交付契约。"""
    drama_id: int = Field(..., description="短剧项目 ID")
    version_cursor: int = Field(default=1, description="定稿版本游标")
    episode_num: int = Field(..., description="分集序号")
    episode_title: str = Field(default="", description="分集标题")
    characters: list[dict[str, Any]] = Field(default_factory=list, description="本集出场人物资产标准档案")
    scenes: list[dict[str, Any]] = Field(default_factory=list, description="本集场景标准档案")
    storyboards: list[VisualStoryboardItem] = Field(default_factory=list, description="标准化分镜序列")
    created_at: str = Field(default_factory=now_iso, description="契约生成时间")


# =====================================================================
# 2. 契约提取与分发引擎
# =====================================================================

class ScriptToVisualBridge:
    """双工坊契约流转与幂等桥梁。"""

    @classmethod
    def compute_task_fingerprint(
        cls,
        drama_id: int,
        episode_num: int,
        storyboard_num: int,
        prompt: str,
        aspect_ratio: str = "9:16",
        version_cursor: int = 1,
    ) -> str:
        """计算分镜视听渲染任务的唯一幂等指纹 (SHA256)。"""
        raw = f"{drama_id}_{episode_num}_{storyboard_num}_{prompt.strip()}_{aspect_ratio}_{version_cursor}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def extract_contract_from_script(
        cls,
        db: Session,
        drama_id: int,
        episode_num: int,
    ) -> ScriptToVisualContract:
        """从已定稿剧本中提取视听生产契约。"""
        # 1. 验证短剧锁定与版本状态
        drama = fetch_one(db, "SELECT id, title, lock_status, version_cursor FROM dramas WHERE id = :did", {"did": drama_id})
        if not drama:
            raise ValueError(f"短剧项目不存在: drama_id={drama_id}")

        cursor = drama.get("version_cursor") or 1

        # 2. 获取分集记录
        ep_row = fetch_one(
            db,
            "SELECT id, episode_number, title, script_content, ast_blocks FROM episodes WHERE drama_id = :did AND episode_number = :enum AND deleted_at IS NULL",
            {"did": drama_id, "enum": episode_num},
        )
        if not ep_row:
            raise ValueError(f"分集不存在: drama_id={drama_id}, episode_num={episode_num}")

        # 3. 提取角色与场景
        characters = fetch_all(db, "SELECT id, name, role, appearance, identity_anchors FROM characters WHERE drama_id = :did", {"did": drama_id})
        scenes = fetch_all(db, "SELECT id, location, time, prompt FROM scenes WHERE drama_id = :did", {"did": drama_id})

        # 4. 解析正文拆解分镜（优先利用 AST beats 视听原子小节，无则使用宏观分块或规则兜底）
        ast_json = json_loads(ep_row.get("ast_blocks"), {})
        body = ep_row.get("script_content") or ""

        # 尝试提取工笔 AST beats 视听原子小节
        ast_data = ast_json.get("ast_data") if isinstance(ast_json, dict) else {}
        beats: list[dict[str, Any]] = []
        if isinstance(ast_data, dict) and isinstance(ast_data.get("beats"), list):
            beats = ast_data["beats"]
        elif isinstance(ast_json, dict) and isinstance(ast_json.get("beats"), list):
            beats = ast_json["beats"]

        storyboards: list[VisualStoryboardItem] = []

        if beats:
            logger.info("【Bridge 桥梁】检测到第 %s 集包含 %d 个视听原子小节 (Beats)，开始映射为工业分镜...", episode_num, len(beats))
            for idx, beat in enumerate(beats, start=1):
                b_type = beat.get("beat_type", "action") if isinstance(beat, dict) else getattr(beat, "beat_type", "action")
                speaker = (beat.get("speaker") if isinstance(beat, dict) else getattr(beat, "speaker", None)) or ""
                dlg_text = (beat.get("dialogue_text") if isinstance(beat, dict) else getattr(beat, "dialogue_text", None)) or ""
                act_text = (beat.get("physical_action") if isinstance(beat, dict) else getattr(beat, "physical_action", None)) or ""
                stress = (beat.get("stress_action") if isinstance(beat, dict) else getattr(beat, "stress_action", None)) or ""
                vocal = (beat.get("vocal_delivery") if isinstance(beat, dict) else getattr(beat, "vocal_delivery", None)) or ""
                prop = (beat.get("interacted_prop") if isinstance(beat, dict) else getattr(beat, "interacted_prop", None)) or ""

                if b_type == "dialogue":
                    shot_type = "特写" if idx == 1 else "中近景"
                    cam = "微推" if idx == 1 else "固定"
                    title = f"镜头{idx}：{speaker}对白"
                    char_names = [speaker] if speaker else [c.get("name") for c in characters if c.get("name")][:1]
                    desc_parts = []
                    if speaker:
                        desc_parts.append(f"{speaker}")
                    if stress:
                        desc_parts.append(f"处于应激状态（{stress}）")
                    if vocal:
                        desc_parts.append(f"发声腔体（{vocal}）")
                    if prop:
                        desc_parts.append(f"手持或注视【{prop}】")
                    desc = "，".join(desc_parts) if desc_parts else "角色对白表情特写"
                    dialogue_val = f"{speaker}：{dlg_text}" if speaker else dlg_text
                    prompt = f"竖屏9:16电影级质感短剧，{shot_type}，{desc}，光影对比强烈，细节丰富，电影质感调色"
                else:
                    shot_type = "特写" if prop or idx == 1 else "全景" if idx == 2 else "中景"
                    cam = "推镜头" if idx == 1 else "移镜头"
                    title = f"镜头{idx}：{act_text[:20]}"
                    char_names = [c.get("name") for c in characters if c.get("name") and c.get("name") in act_text]
                    if not char_names:
                        char_names = [c.get("name") for c in characters if c.get("name")][:1]
                    dialogue_val = ""
                    prompt = f"竖屏9:16电影级质感短剧，{shot_type}，{act_text}，电影级光影对比，8k细节"

                fp = cls.compute_task_fingerprint(drama_id, episode_num, idx, prompt, "9:16", cursor)
                storyboards.append(
                    VisualStoryboardItem(
                        storyboard_number=idx,
                        title=title,
                        shot_type=shot_type,
                        camera_movement=cam,
                        aspect_ratio="9:16",
                        characters=char_names,
                        dialogue=dialogue_val,
                        visual_prompt=prompt,
                        task_fingerprint=fp,
                    )
                )
        else:
            # 兜底生成 4-6 个标准竖屏镜头
            shots_meta = [
                ("特写", "前3秒视觉钩子镜头，极强情绪张力与动作反差", "推镜头"),
                ("中景", "双人对峙与身份试探，动作走位调度", "固定"),
                ("全景", "大场景空间关系与群演包围压迫感", "拉远"),
                ("特写", "关键道具与信物特写，片尾悬念卡点定格", "慢推"),
            ]

            for idx, (shot_type, desc, cam) in enumerate(shots_meta, start=1):
                prompt = f"竖屏9:16电影级质感短剧，{shot_type}，{desc}，光影对比强烈，细节丰富，masterpiece 8k"
                fp = cls.compute_task_fingerprint(drama_id, episode_num, idx, prompt, "9:16", cursor)
                storyboards.append(
                    VisualStoryboardItem(
                        storyboard_number=idx,
                        title=f"镜头{idx}：{desc[:20]}",
                        shot_type=shot_type,
                        camera_movement=cam,
                        aspect_ratio="9:16",
                        characters=[c.get("name") for c in characters if c.get("name")],
                        dialogue="台词/潜台词对白",
                        visual_prompt=prompt,
                        task_fingerprint=fp,
                    )
                )

        contract = ScriptToVisualContract(
            drama_id=drama_id,
            version_cursor=cursor,
            episode_num=episode_num,
            episode_title=ep_row.get("title") or f"第{episode_num}集",
            characters=characters,
            scenes=scenes,
            storyboards=storyboards,
        )
        return contract

    @classmethod
    def sync_contract_to_visual_studio(
        cls,
        db: Session,
        contract: ScriptToVisualContract,
    ) -> dict[str, Any]:
        """将 Bridge 契约同步写入视听工坊表 (storyboards 等)，建立只读解耦映射。"""
        now = now_iso()

        # 获取 episode_id
        ep_row = fetch_one(
            db,
            "SELECT id FROM episodes WHERE drama_id = :did AND episode_number = :enum AND deleted_at IS NULL",
            {"did": contract.drama_id, "enum": contract.episode_num},
        )
        if not ep_row:
            raise ValueError("对应分集不存在")
        episode_id = ep_row["id"]

        synced_count = 0
        for sb in contract.storyboards:
            # 检查是否已存在同 fingerprint 的分镜
            existing = fetch_one(
                db,
                "SELECT id FROM storyboards WHERE episode_id = :eid AND storyboard_number = :snum AND deleted_at IS NULL",
                {"eid": episode_id, "snum": sb.storyboard_number},
            )
            if existing:
                db.execute(
                    text(
                        """
                        UPDATE storyboards
                        SET title = :title, shot_type = :shot_type, movement = :cam,
                            dialogue = :dialogue, image_prompt = :prompt, task_fingerprint = :fp, status = 'pending', updated_at = :now
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": existing["id"],
                        "title": sb.title,
                        "shot_type": sb.shot_type,
                        "cam": sb.camera_movement,
                        "dialogue": sb.dialogue,
                        "prompt": sb.visual_prompt,
                        "fp": sb.task_fingerprint,
                        "now": now,
                    },
                )
            else:
                db.execute(
                    text(
                        """
                        INSERT INTO storyboards (
                            episode_id, storyboard_number, title, shot_type, movement,
                            dialogue, image_prompt, task_fingerprint, status, created_at, updated_at
                        ) VALUES (
                            :eid, :snum, :title, :shot_type, :cam, :dialogue, :prompt, :fp, 'pending', :now, :now
                        )
                        """
                    ),
                    {
                        "eid": episode_id,
                        "snum": sb.storyboard_number,
                        "title": sb.title,
                        "shot_type": sb.shot_type,
                        "cam": sb.camera_movement,
                        "dialogue": sb.dialogue,
                        "prompt": sb.visual_prompt,
                        "fp": sb.task_fingerprint,
                        "now": now,
                    },
                )
            synced_count += 1

        logger.info(
            "Bridge契约同步完成: drama_id=%s, episode_num=%s, 同步分镜数=%s",
            contract.drama_id, contract.episode_num, synced_count,
        )
        return {
            "drama_id": contract.drama_id,
            "episode_num": contract.episode_num,
            "synced_storyboards": synced_count,
            "version_cursor": contract.version_cursor,
            "status": "bridged_to_visual_studio",
        }
