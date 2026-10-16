# -*- coding: utf-8 -*-
"""多模态资产真理层与注册清单契约。

本模块属于短剧工作流核心状态机契约子领域。
"""
from __future__ import annotations

import logging
import operator
from enum import Enum
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger("app.schemas.states.asset")

from app.schemas.states.base import AssetState, AssetGenerationMode
from app.schemas.states.audio import MasterVoiceCardModel


class ReusedAssetModel(BaseModel):
    """【规则编号: RULE-VI-06】阶段 6 已核准复用资产模型。"""
    model_config = ConfigDict(extra="allow")

    asset_id: str = Field(..., description="已注册四段式资产ID (如 CHAR_LIN_BASE_PORTRAIT)")
    type: str = Field(default="character_base_identity", description="资产类别标识")
    usage_in_current_ep: str = Field(default="", description="声明该老资产在本集中的具体用途")
    status: str = Field(default="APPROVED", description="核准状态，固定为 APPROVED")
    lifecycle_status: AssetState | str = Field(default=AssetState.APPROVED, description="资产生命周期状态")
    semantic_hash: str | None = Field(default=None, description="资产语义特征哈希指纹 (SHA-256)")
    aliases: list[str] = Field(default_factory=list, description="资产关联别名/代称列表")
    tags: list[str] = Field(default_factory=list, description="检索或分类标签")

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)


class NewlyGeneratedAssetModel(BaseModel):
    """【规则编号: RULE-VI-06】阶段 6 增量单项视听资产模型。"""
    model_config = ConfigDict(extra="allow")

    asset_id: str = Field(..., description="四段式标准资产ID (如 CHAR_LIN_4V_FRONT_FULL, PROP_01_ACTION)")
    asset_category: str = Field(
        default="character_tier1_base",
        description="资产分级枚举 (character_tier1_base, character_tier2_performance, character_tier3_special, env_tier1_primary, env_tier2_transitional, prop_tier1_hero等)"
    )
    script_inference_trigger: str = Field(..., description="剧本逆向推理铁证长句，写明触发动作行动词依据")
    generation_method: str = Field(
        default="text_to_image",
        description="生图/生音算法模式 (text_to_image, image_to_image_outpainting, image_to_image_pose, inpainting_local_edit, relighting)"
    )
    input_source_image: str | None = Field(default=None, description="图生图底图来源资产ID，纯文生图填 null")
    identity_reference: str | None = Field(default=None, description="角色肖像身份基准ID，角色图必填")
    denoising_strength: float | None = Field(default=None, description="图生图重绘幅度 (0.30 ~ 0.60)")
    aspect_ratio: str = Field(default="9:16", description="单项素材专用画幅比例 (如 4:5, 1:1, 9:16)")
    image_prompt: str = Field(default="", description="完整英文生图Prompt，带风格介质参数与 --style raw")
    status: str = Field(default="APPROVED", description="新生成并通过审核的资产状态，固定为 APPROVED")
    lifecycle_status: AssetState | str = Field(default=AssetState.READY, description="资产生命周期状态 (DRAFT/READY/QUEUED/RENDERED/APPROVED)")
    semantic_hash: str | None = Field(default=None, description="资产语义特征哈希指纹 (SHA-256)")
    aliases: list[str] = Field(default_factory=list, description="资产别名/代称列表")
    tags: list[str] = Field(default_factory=list, description="检索或分类标签")

    # 扩展属性，兼容底图依赖与工作流
    parent_asset_id: str | None = Field(default=None, description="父级资产ID")
    recommended_denoise: float | None = Field(default=None, description="推荐重绘幅度")
    workflow_note: str = Field(default="", description="工作流管线说明")
    visual_prompt: str = Field(default="", description="生图Prompt别名")

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)


class EpisodeResourceManifest(BaseModel):
    """阶段 6 产出：本集视听资源引单 (Episode Resource Manifest)。
    
    严格对齐 SKILL1.md v10.0.0 阶段 6 数据契约：
    - 角色三级 (tier1_base / tier2_performance / tier3_special)
    - 场景两级 (tier1_primary / tier2_transitional)
    - 道具三级 (tier1_hero / tier2_anchor / tier3_atmospheric)
    支持嵌套树状契约与平铺字段双向序列化/反序列化。
    """
    model_config = ConfigDict(extra="allow")

    episode_num: int = Field(default=1, description="集数编号")
    episode_title: str = Field(default="", description="单集爆款标题")
    aspect_ratio: str = Field(default="9:16", description="单集视听画幅比例")

    # 平铺存储（一级/二级/三级）
    characters_tier_1: list[dict[str, Any]] = Field(default_factory=list, description="一级身份基础资产 (base_portrait, base_costume, master_voice)")
    characters_tier_2: list[dict[str, Any]] = Field(default_factory=list, description="二级叙事表现资产（angle_views, script_emotions）")
    characters_tier_3: list[dict[str, Any]] = Field(default_factory=list, description="三级镜头专项资产（special_macro, status_branch）")
    environments_primary: list[dict[str, Any]] = Field(default_factory=list, description="一级核心主场景 (wide_shot, insert_shot, lighting_state)")
    environments_transitional: list[dict[str, Any]] = Field(default_factory=list, description="二级过渡次场景 (keyframe_asset)")
    props_narrative: list[dict[str, Any]] = Field(default_factory=list, description="一级核心叙事物证 (static_asset, action_asset, haptic_resistance)")
    props_anchors: list[dict[str, Any]] = Field(default_factory=list, description="二级角色锚定道具 (attached_character_macro)")
    props_ambient: list[dict[str, Any]] = Field(default_factory=list, description="三级环境气氛杂物 (item_name, scene, motion_note 零独立生图)")

    approved_character_ids: list[str | int] = Field(default_factory=list, description="已核准复用的角色ID列表")
    approved_scene_ids: list[str | int] = Field(default_factory=list, description="已核准复用的场景ID列表")
    approved_prop_ids: list[str | int] = Field(default_factory=list, description="已核准复用的道具ID列表")

    # 阶段 6 增量视听生成包与演化血统
    newly_discovered_characters: list[dict[str, Any]] = Field(default_factory=list, description="本集发现并按阶段2标准11维补录的新角色列表")
    newly_discovered_scenes: list[dict[str, Any]] = Field(default_factory=list, description="本集发现并按阶段3标准补录的新场景列表")
    newly_discovered_props: list[dict[str, Any]] = Field(default_factory=list, description="本集发现并按阶段3标准补录的新道具列表")
    newly_generated_assets: list[dict[str, Any]] = Field(default_factory=list, description="本集新增视听资产包")
    new_character_master_voice_cards: list[dict[str, Any]] = Field(default_factory=list, description="本集新建角色主音色母卡")
    lineage_dag: dict[str, Any] = Field(default_factory=dict, description="本集资产演进继承DAG")
    reused_existing_assets: list[dict[str, Any]] = Field(default_factory=list, description="本集复用历史资产清单")

    @classmethod
    def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> "EpisodeResourceManifest":
        if isinstance(obj, dict):
            obj = dict(obj)
            # 1. 角色层级解析
            chars_val = obj.get("characters") or obj.get("character_assets")
            if isinstance(chars_val, dict):
                if not obj.get("characters_tier_1"):
                    obj["characters_tier_1"] = chars_val.get("tier1_base") or chars_val.get("tier_1") or []
                if not obj.get("characters_tier_2"):
                    obj["characters_tier_2"] = chars_val.get("tier2_performance") or chars_val.get("tier_2") or []
                if not obj.get("characters_tier_3"):
                    obj["characters_tier_3"] = chars_val.get("tier3_special") or chars_val.get("tier_3") or []
            elif isinstance(chars_val, list) and not obj.get("characters_tier_1"):
                t1, t2, t3 = [], [], []
                for item in chars_val:
                    if not isinstance(item, dict):
                        continue
                    tier = str(item.get("tier", "")).upper()
                    aid = str(item.get("asset_id") or item.get("char_id") or "")
                    if tier == "T1" or "_T1_" in aid or "BASE" in aid:
                        t1.append(item)
                    elif tier == "T2" or "_T2_" in aid or "4V" in aid or "EXP_" in aid or "LIGHT_" in aid:
                        t2.append(item)
                    elif tier == "T3" or "_T3_" in aid or "MACRO" in aid or "STATUS" in aid:
                        t3.append(item)
                    else:
                        t1.append(item)
                obj["characters_tier_1"] = t1
                obj["characters_tier_2"] = t2
                obj["characters_tier_3"] = t3

            # 2. 场景层级解析
            envs_val = obj.get("environments") or obj.get("scene_assets")
            if isinstance(envs_val, dict):
                if not obj.get("environments_primary"):
                    obj["environments_primary"] = envs_val.get("tier1_primary") or envs_val.get("primary") or []
                if not obj.get("environments_transitional"):
                    obj["environments_transitional"] = envs_val.get("tier2_transitional") or envs_val.get("transitional") or []
            elif isinstance(envs_val, list) and not obj.get("environments_primary"):
                e1, e2 = [], []
                for item in envs_val:
                    if not isinstance(item, dict):
                        continue
                    tier = str(item.get("tier", "")).upper()
                    aid = str(item.get("asset_id") or item.get("scene_id") or "")
                    if tier == "T2" or "_T2_" in aid or "KEYFRAME" in aid:
                        e2.append(item)
                    else:
                        e1.append(item)
                obj["environments_primary"] = e1
                obj["environments_transitional"] = e2

            # 3. 道具层级解析
            props_val = obj.get("props") or obj.get("prop_assets")
            if isinstance(props_val, dict):
                if not obj.get("props_narrative"):
                    obj["props_narrative"] = props_val.get("tier1_hero") or props_val.get("hero") or []
                if not obj.get("props_anchors"):
                    obj["props_anchors"] = props_val.get("tier2_anchor") or props_val.get("anchor") or []
                if not obj.get("props_ambient"):
                    obj["props_ambient"] = props_val.get("tier3_atmospheric") or props_val.get("atmospheric") or []
            elif isinstance(props_val, list) and not obj.get("props_narrative"):
                p1, p2, p3 = [], [], []
                for item in props_val:
                    if not isinstance(item, dict):
                        continue
                    tier = str(item.get("tier", "")).upper()
                    aid = str(item.get("asset_id") or item.get("prop_id") or "")
                    if tier == "T2" or "_T2_" in aid or "ANCHOR" in aid:
                        p2.append(item)
                    elif tier == "T3" or "_T3_" in aid or "AMBIENT" in aid or "ATMOSPHERIC" in aid:
                        p3.append(item)
                    else:
                        p1.append(item)
                obj["props_narrative"] = p1
                obj["props_anchors"] = p2
                obj["props_ambient"] = p3

            if not obj.get("episode_title") and obj.get("title"):
                obj["episode_title"] = str(obj.get("title"))

        return super().model_validate(obj, *args, **kwargs)

    @property
    def characters(self) -> list[dict[str, Any]]:
        """全量角色资产平铺列表。"""
        return self.characters_tier_1 + self.characters_tier_2 + self.characters_tier_3

    @property
    def character_assets(self) -> list[dict[str, Any]]:
        return self.characters

    @property
    def characters_by_tier(self) -> dict[str, list[dict[str, Any]]]:
        """SKILL1.md Table 6 规范三级角色资产字典。"""
        return {
            "tier1_base": self.characters_tier_1,
            "tier2_performance": self.characters_tier_2,
            "tier3_special": self.characters_tier_3,
        }

    @property
    def environments(self) -> list[dict[str, Any]]:
        """全量场景资产平铺列表。"""
        return self.environments_primary + self.environments_transitional

    @property
    def scene_assets(self) -> list[dict[str, Any]]:
        return self.environments

    @property
    def environments_by_tier(self) -> dict[str, list[dict[str, Any]]]:
        """SKILL1.md Table 6 规范两级场景资产字典。"""
        return {
            "tier1_primary": self.environments_primary,
            "tier2_transitional": self.environments_transitional,
        }

    @property
    def props(self) -> list[dict[str, Any]]:
        """全量道具资产平铺列表。"""
        return self.props_narrative + self.props_anchors + self.props_ambient

    @property
    def prop_assets(self) -> list[dict[str, Any]]:
        return self.props

    @property
    def props_by_tier(self) -> dict[str, list[dict[str, Any]]]:
        """SKILL1.md Table 6 规范三级道具资产字典。"""
        return {
            "tier1_hero": self.props_narrative,
            "tier2_anchor": self.props_anchors,
            "tier3_atmospheric": self.props_ambient,
        }

    @property
    def character_names(self) -> list[str]:
        """本集引单中涉及的所有角色名称去重列表。"""
        names: list[str] = []
        for c in self.characters:
            name = c.get("character_name") or c.get("name")
            if name and str(name) not in names:
                names.append(str(name))
        return names

    @property
    def scene_names(self) -> list[str]:
        """本集引单中涉及的所有场景名称/空间去重列表。"""
        names: list[str] = []
        for e in self.environments:
            name = e.get("scene_name") or e.get("location_name") or e.get("location") or e.get("name")
            if name and str(name) not in names:
                names.append(str(name))
        return names

    @property
    def prop_names(self) -> list[str]:
        """本集引单中涉及的所有道具名称去重列表。"""
        names: list[str] = []
        for p in self.props:
            name = p.get("prop_name") or p.get("name")
            if name and str(name) not in names:
                names.append(str(name))
        return names

    @property
    def all_asset_ids(self) -> list[str]:
        """本集引单中登记的所有四段式资产唯一ID去重列表。"""
        ids: list[str] = []
        for c in self.characters:
            aid = c.get("asset_id") or c.get("char_id")
            if aid and str(aid) not in ids:
                ids.append(str(aid))
        for e in self.environments:
            aid = e.get("asset_id") or e.get("scene_id")
            if aid and str(aid) not in ids:
                ids.append(str(aid))
        for p in self.props:
            aid = p.get("asset_id") or p.get("prop_id")
            if aid and str(aid) not in ids:
                ids.append(str(aid))
        for c in self.characters_tier_1:
            mv = c.get("master_voice")
            if mv and str(mv) not in ids:
                ids.append(str(mv))
        for vc in self.new_character_master_voice_cards:
            if isinstance(vc, dict):
                vid = vc.get("master_voice_id") or vc.get("voice_id") or vc.get("asset_id")
                if vid and str(vid) not in ids:
                    ids.append(str(vid))
        return ids

    @property
    def semantic_hashes(self) -> dict[str, str]:
        """提取引单中所有登记了语义哈希的资产指纹字典 {asset_id: semantic_hash}。"""
        hashes: dict[str, str] = {}
        for item in self.characters + self.environments + self.props + self.new_character_master_voice_cards:
            if isinstance(item, dict):
                aid = (
                    item.get("asset_id")
                    or item.get("char_id")
                    or item.get("scene_id")
                    or item.get("prop_id")
                    or item.get("master_voice_id")
                    or item.get("voice_id")
                )
                h = item.get("semantic_hash")
                if aid and h:
                    hashes[str(aid)] = str(h)
        return hashes

    def to_flat_dict(self) -> dict[str, Any]:
        """输出原生平铺结构字典。"""
        return self.model_dump()

    def to_nested_dict(self) -> dict[str, Any]:
        """输出 SKILL1.md Table 6 树状嵌套契约字典。"""
        return {
            "episode_num": self.episode_num,
            "characters": self.characters_by_tier,
            "environments": self.environments_by_tier,
            "props": self.props_by_tier,
            "approved_character_ids": self.approved_character_ids,
            "approved_scene_ids": self.approved_scene_ids,
            "approved_prop_ids": self.approved_prop_ids,
            "newly_generated_assets": self.newly_generated_assets,
            "new_character_master_voice_cards": self.new_character_master_voice_cards,
            "lineage_dag": self.lineage_dag,
            "reused_existing_assets": self.reused_existing_assets,
        }

    def to_dict(self) -> dict[str, Any]:
        """输出同时兼容 SKILL1.md 树状嵌套契约与平铺字段的双向兼容字典。"""
        res = self.model_dump()
        res["characters"] = self.characters_by_tier
        res["environments"] = self.environments_by_tier
        res["props"] = self.props_by_tier
        res["character_names"] = self.character_names
        res["scene_names"] = self.scene_names
        res["prop_names"] = self.prop_names
        res["all_asset_ids"] = self.all_asset_ids
        return res

    def get(self, key: str, default: Any = None) -> Any:
        if key == "characters":
            return self.characters
        if key == "characters_by_tier" or key == "characters_nested":
            return self.characters_by_tier
        if key == "character_names":
            return self.character_names
        if key == "environments":
            return self.environments
        if key == "environments_by_tier" or key == "environments_nested":
            return self.environments_by_tier
        if key == "scene_names":
            return self.scene_names
        if key == "props":
            return self.props
        if key == "props_by_tier" or key == "props_nested":
            return self.props_by_tier
        if key == "prop_names":
            return self.prop_names
        if key == "all_asset_ids":
            return self.all_asset_ids
        if key == "semantic_hashes":
            return self.semantic_hashes
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        if key == "characters":
            return self.characters
        if key == "characters_by_tier" or key == "characters_nested":
            return self.characters_by_tier
        if key == "character_names":
            return self.character_names
        if key == "environments":
            return self.environments
        if key == "environments_by_tier" or key == "environments_nested":
            return self.environments_by_tier
        if key == "scene_names":
            return self.scene_names
        if key == "props":
            return self.props
        if key == "props_by_tier" or key == "props_nested":
            return self.props_by_tier
        if key == "prop_names":
            return self.prop_names
        if key == "all_asset_ids":
            return self.all_asset_ids
        if key == "semantic_hashes":
            return self.semantic_hashes
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def keys(self) -> list[str]:
        return list(self.to_dict().keys())

    def values(self) -> list[Any]:
        return list(self.to_dict().values())

    def items(self) -> list[tuple[str, Any]]:
        return list(self.to_dict().items())

    def __contains__(self, key: str) -> bool:
        return key in self.to_dict()


class VisualAudioAssetsRegistryModel(BaseModel):
    """【规则编号: RULE-VI-06】阶段 6 产出：05_visual_audio_assets.json 全局视听资产真理源模型。"""
    model_config = ConfigDict(extra="allow")

    episode_id: int = Field(default=1, description="当前集物理序号")
    episode_title: str = Field(default="", description="单集剧名")
    global_assets_summary: dict[str, Any] = Field(default_factory=dict, description="全局资产统计对象")
    characters: dict[str, Any] = Field(default_factory=dict, description="全剧已注册角色资产库")
    environments: dict[str, Any] = Field(default_factory=dict, description="全剧已注册场景资产库")
    props: dict[str, Any] = Field(default_factory=dict, description="全剧已注册道具资产库")
    audio_tts: dict[str, Any] = Field(default_factory=dict, description="全剧已注册母音频库")
    character_master_voices: dict[str, Any] = Field(default_factory=dict, description="全剧已注册母音频卡片库")
    reused_assets_history: dict[int, list[str]] = Field(default_factory=dict, description="各集复用资产历史记录")
    reused_existing_assets: list[ReusedAssetModel] = Field(default_factory=list, description="本集复用资产列表")
    newly_generated_assets: list[NewlyGeneratedAssetModel] = Field(default_factory=list, description="本集新生成增量资产列表")
    new_character_master_voice_cards: list[MasterVoiceCardModel] = Field(default_factory=list, description="新角色母音频卡片列表")
    episode_resource_manifest: EpisodeResourceManifest | None = Field(default=None, description="本集视听资源引单")
    audit_report: dict[str, Any] = Field(default_factory=dict, description="红蓝对抗质检报告")

    def to_dict(self) -> dict[str, Any]:
        res = self.model_dump()
        if self.episode_resource_manifest:
            res["episode_resource_manifest"] = self.episode_resource_manifest.to_dict()
        return res

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)


class CharacterStageViewAsset(BaseModel):
    """角色阶段分视角资产 (character_stage_views 从表模型)。"""
    model_config = ConfigDict(extra="allow")
    asset_key: str = Field(default="", description="切片全局唯一资产编码 (如 CHAR_LUCHEN_T1_4V_FRONT)")
    parent_asset_key: str = Field(default="", description="底图来源父资产Key (如 CHAR_LUCHEN_T1_BASE_COSTUME)")
    view_type: str = Field(default="front", description="视角类型：main_portrait/front/side/back/three_quarter/facial_macro/hands_detail/etc")
    view_label: str = Field(default="", description="切片展示标签")
    generation_mode: str = Field(default="t2i", description="生成模式：t2i/i2i/controlnet/inpaint/crop_macro")
    denoise_strength: float = Field(default=0.0, description="重绘去噪强度 (0.0~1.0)")
    control_type: str = Field(default="", description="控制网类型 (openpose/depth/lineart/inpaint_face)")
    identity_prompt: str = Field(default="", description="面部与生物学基因锚点词 (锁定不变特征)")
    delta_prompt: str = Field(default="", description="当前视图姿态/视角/服饰增量提示词")
    prompt: str = Field(default="", description="正向生图完整提示词 (image_prompt)")
    image_prompt: str = Field(default="", description="精准生图提示词 (对齐 prompt 字段)")
    negative_prompt: str = Field(default="", description="排他性负向提示词")
    image_url: str = Field(default="", description="生成图访问 URL")
    local_path: str = Field(default="", description="本地物理存储路径")
    seedance_asset_id: str = Field(default="", description="Seedance/外部平台资产引用 ID")
    seedance2_asset_id: str = Field(default="", description="外部平台资产引用 ID 2")
    is_benchmark: int = Field(default=0, description="是否为全剧唯一 Face ID 真理源基准 (1=是, 0=否)")
    is_primary: int = Field(default=0, description="是否作为当前造型的主视觉参考图：0-否，1-是")
    status: str = Field(default="completed", description="状态：pending/processing/completed/failed")


class CharacterStageAsset(BaseModel):
    """角色生命周期阶段变体资产 (character_stages 从表模型)。"""
    model_config = ConfigDict(extra="allow")
    stage_code: str = Field(default="T1", description="阶段代号 (如 T1, T2, T3)")
    stage_name: str = Field(default="初始阶段", description="阶段名称（如：落魄期/逆袭崛起/黑化复仇/终局巅峰）")
    stage_order: int = Field(default=1, description="阶段顺序编号")
    parent_stage_id: int = Field(default=0, description="父级阶段 ID")
    benchmark_asset_key: str = Field(default="", description="本阶段代表真理资产Key")
    costume_desc: str = Field(default="", description="本阶段服化道物理做旧描述")
    makeup_desc: str = Field(default="", description="本阶段妆容与骨相微变描述")
    image_url: str = Field(default="", description="代表图 URL")
    local_path: str = Field(default="", description="代表图本地存储路径")
    seedance_asset_id: str = Field(default="", description="Seedance/外部平台资产引用 ID")
    prompt: str = Field(default="", description="正向生图提示词")
    negative_prompt: str = Field(default="", description="负向提示词")
    views: list[CharacterStageViewAsset] = Field(default_factory=list, description="本阶段多视角子资产列表")


class SceneWeatheringViewAsset(BaseModel):
    """场景气候/做旧/光影图层资产 (scene_weathering_views 从表模型)。"""
    model_config = ConfigDict(extra="allow")
    asset_key: str = Field(default="", description="场景切片唯一资产编码 (如 ENV_OFFICE_Z01_OTS_BG)")
    parent_asset_key: str = Field(default="", description="演变/虚化父底图资产Key (如 ENV_OFFICE_Z01_WIDE)")
    layer_type: str = Field(default="natural", description="图层类型：base_material/natural/rain/night/ruin/panoramic_plate/ots_bg")
    generation_mode: str = Field(default="t2i", description="生成模式：t2i/i2i/depth_blur/controlnet_weather")
    denoise_strength: float = Field(default=0.0, description="重绘降噪度 (如 0.30 景深虚化)")
    description: str = Field(default="", description="做旧细节描述")
    lighting_prompt: str = Field(default="", description="光影与氛围专用提示词")
    texture_prompt: str = Field(default="", description="材质与做旧专用提示词")
    prompt: str = Field(default="", description="完整合成生图提示词 (visual_prompt)")
    visual_prompt: str = Field(default="", description="视角渲染提示词 Prompt")
    negative_prompt: str = Field(default="", description="负向提示词")
    image_url: str = Field(default="", description="图层资产 URL")
    local_path: str = Field(default="", description="本地物理路径")
    is_benchmark: int = Field(default=0, description="是否为空间几何基准视图 (1=是, 0=否)")
    is_primary: int = Field(default=0, description="是否为当前区域默认主视觉图")
    is_locked_truth: int = Field(default=0, description="是否已锁定为空间真值")
    status: str = Field(default="completed", description="状态")


class SceneZoneAsset(BaseModel):
    """场景三级子功能区域资产 (scene_zones 从表模型)。"""
    model_config = ConfigDict(extra="allow")
    zone_code: str = Field(default="Z01_MAIN", description="子区域空间代号 (如 Z01_MAIN, Z02_WINDOW)")
    parent_zone_id: int = Field(default=0, description="父级空间区域 ID")
    zone_name: str = Field(default="主活动区", description="子区域名称（如：办公桌区域/落地窗前/秘密暗格/会客沙发）")
    time_lighting: str = Field(default="", description="时间与光影定义")
    camera_orientation: str = Field(default="", description="机位朝向与空间构图说明")
    spatial_layout: str = Field(default="", description="空间长宽高与摆设布局细节")
    image_url: str = Field(default="", description="局部区域效果图 URL")
    local_path: str = Field(default="", description="本地物理存储路径")
    prompt: str = Field(default="", description="生图提示词")
    negative_prompt: str = Field(default="", description="负向提示词")
    weathering_views: list[SceneWeatheringViewAsset] = Field(default_factory=list, description="多气候图层资产")


class PropDetailViewAsset(BaseModel):
    """道具微距局部与多视角资产 (prop_detail_views 从表模型)。"""
    model_config = ConfigDict(extra="allow")
    asset_key: str = Field(default="", description="道具切片唯一资产编码 (如 PROP_JADE_S0_STATIC)")
    parent_asset_key: str = Field(default="", description="战损演进上一级父底图Key")
    view_type: str = Field(default="macro_feature", description="视角类型：macro_feature/overall_shot/engraving/alpha_mask")
    generation_mode: str = Field(default="t2i", description="生成模式：t2i/i2i/inpaint")
    denoise_strength: float = Field(default=0.0, description="重绘降噪度 (如 0.35~0.50)")
    visual_prompt: str = Field(default="", description="特写生图 Prompt")
    prompt: str = Field(default="", description="正向生图提示词")
    negative_prompt: str = Field(default="", description="负向提示词")
    image_url: str = Field(default="", description="生成图访问 URL")
    local_path: str = Field(default="", description="本地物理路径")
    is_benchmark: int = Field(default=0, description="是否为初始物证真值基准")
    is_primary: int = Field(default=0, description="是否为主视图")
    is_locked_truth: int = Field(default=0, description="是否已锁定为物证真值")
    status: str = Field(default="completed", description="状态")


class PropDamageStateAsset(BaseModel):
    """道具损坏/形变状态演进资产 (prop_damage_states 从表模型)。"""
    model_config = ConfigDict(extra="allow")
    state_code: str = Field(default="S0_PRISTINE", description="破坏状态代号 (如 S0_PRISTINE, S1_CRACKED, S2_BROKEN)")
    state_label: str = Field(default="完整初始态", description="状态标签（如：完整初始态/裂痕破损/断裂烧焦）")
    state_order: int = Field(default=1, description="状态顺序编号")
    damage_level: int = Field(default=0, description="破坏等级 (0=完好, 1=轻度, 2=受创, 3=报废)")
    parent_state_id: int = Field(default=0, description="继承来源父状态 ID")
    narrative_point: str = Field(default="", description="触发该状态演进的剧情节点")
    damage_desc: str = Field(default="", description="物理形变与破损原因详细描述")
    image_url: str = Field(default="", description="状态代表图 URL")
    local_path: str = Field(default="", description="本地存储路径")
    prompt: str = Field(default="", description="正向生图提示词")
    negative_prompt: str = Field(default="", description="负向提示词")
    detail_views: list[PropDetailViewAsset] = Field(default_factory=list, description="本状态多视角/微距图层")


class EpisodeLocalAsset(BaseModel):
    """【单集局部资产】单集独有资产（如特约群演、一次性道具、临时特定场景），生命周期局限于本集。"""
    model_config = ConfigDict(extra="allow")
    asset_id: str = Field(default="", description="局部资产唯一标识 (如 EP01_CHAR_WAITER)")
    asset_type: str = Field(default="character", description="资产类型: character / prop / scene")
    name: str = Field(default="", description="资产名称")
    visual_prompt: str = Field(default="", description="视觉生图提示词特征")
    local_path: str = Field(default="", description="本地图片或文件持久化路径")
    image_url: str = Field(default="", description="对象存储或网络图片 URI")
    description: str = Field(default="", description="资产简要说明与戏剧功能")

    @model_validator(mode="before")
    @classmethod
    def _normalize_asset_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            if not data.get("name"):
                data["name"] = (
                    data.get("item_name")
                    or data.get("prop_name")
                    or data.get("character_name")
                    or data.get("location_name")
                    or data.get("title")
                    or data.get("asset_id")
                    or "未命名资产"
                )
            if not data.get("asset_id"):
                data["asset_id"] = (
                    data.get("prop_id")
                    or data.get("char_id")
                    or data.get("scene_id")
                    or data.get("voice_id")
                    or data.get("id")
                    or "ASSET_DEFAULT"
                )
            if not data.get("asset_type"):
                aid = str(data.get("asset_id", ""))
                if "CHAR" in aid:
                    data["asset_type"] = "character"
                elif "ENV" in aid or "SCENE" in aid:
                    data["asset_type"] = "scene"
                elif "PROP" in aid:
                    data["asset_type"] = "prop"
                elif "VOICE" in aid or "AUDIO" in aid:
                    data["asset_type"] = "audio"
        return data

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        if self.model_extra and key in self.model_extra:
            return self.model_extra[key]
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) or (bool(self.model_extra) and key in self.model_extra)

    def get(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        if self.model_extra and key in self.model_extra:
            return self.model_extra[key]
        return default


class ReusedAssetItem(TypedDict, total=False):
    """【规则编号: RULE-VI-06】阶段 6 已核准复用资产项。"""
    asset_id: str
    type: str
    usage_in_current_ep: str
    status: Literal["APPROVED"]


class NewlyGeneratedAssetItem(TypedDict, total=False):
    """【规则编号: RULE-VI-06】阶段 6 新生成增量资产项。"""
    asset_id: str
    asset_category: str
    script_inference_trigger: str
    generation_method: Literal["text_to_image", "image_to_image_outpainting", "image_to_image_pose", "inpainting_local_edit", "relighting"]
    input_source_image: str | None
    identity_reference: str | None
    denoising_strength: float | None
    aspect_ratio: str
    image_prompt: str
    status: Literal["APPROVED"]


class EpisodeResourceManifestDict(TypedDict, total=False):
    """【规则编号: RULE-VI-06】阶段 6 单集视听资源引单字典。"""
    characters: dict[str, list[dict[str, Any]]]
    environments: dict[str, list[dict[str, Any]]]
    props: dict[str, list[dict[str, Any]]]
    audio: dict[str, Any]


VisualAudioAssetsRegistry = VisualAudioAssetsRegistryModel


__all__ = [
    "ReusedAssetModel",
    "NewlyGeneratedAssetModel",
    "EpisodeResourceManifest",
    "VisualAudioAssetsRegistryModel",
    "CharacterStageViewAsset",
    "CharacterStageAsset",
    "SceneWeatheringViewAsset",
    "SceneZoneAsset",
    "PropDetailViewAsset",
    "PropDamageStateAsset",
    "EpisodeLocalAsset",
    "ReusedAssetItem",
    "NewlyGeneratedAssetItem",
    "EpisodeResourceManifestDict",
    "VisualAudioAssetsRegistry",
]
