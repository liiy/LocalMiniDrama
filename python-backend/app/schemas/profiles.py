"""角色、场景、道具资产设定 Schema (CharacterProfile, SceneProfile, PropProfile)。

支持多阶段变装（stages）、一致性特征锚点（identity_anchors）、美术提示词以及道具戏剧功能定义。
"""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class CharacterStage(BaseModel):
    """角色在不同剧情阶段的服装与状态设定（如：前期落魄隐忍、后期换装霸气归来）。"""
    stage_id: str = Field(default="default", description="阶段标识符（如: stage_1, stage_2）")
    stage_name: str = Field(default="初始状态", description="阶段描述（如: 隐姓埋名落魄期 / 首富继承人亮相期）")
    clothing_description: str = Field(..., description="服装服饰详细描述（材质、颜色、款式、配饰）")
    appearance_variation: str = Field(default="", description="发型妆容或气场变化说明")
    image_prompt_addon: str = Field(default="", description="附加到生图提示词中的阶段限定描述")


class CharacterProfile(BaseModel):
    """角色完整人设档案 (Character Profile)。"""
    id: int | None = Field(default=None, description="数据库角色记录 ID")
    name: str = Field(..., description="角色姓名")
    role_type: Literal["protagonist", "antagonist", "supporting", "extra"] = Field(
        default="supporting", description="角色定位：主角、反派、重要配角、龙套"
    )
    gender: str = Field(default="男", description="性别")
    age_range: str = Field(default="25-30岁", description="视觉年龄区间")
    occupation: str = Field(default="", description="公开身份与隐藏身份")
    personality_traits: list[str] = Field(default_factory=list, description="性格标签（如：果决冷酷、护短、隐忍、睚眦必报）")
    core_motivation: str = Field(default="", description="核心人物行动动机（如：复仇、保护爱人、夺回家族荣耀）")
    appearance_description: str = Field(..., description="基础面貌特征（五官、脸型、发型、体态）")
    identity_anchors: list[str] = Field(
        default_factory=list,
        description="用于保持跨集一致性的核心视觉锚点（如：右眼下泪痣、银色短碎发、冷峻刀削脸）"
    )
    catchphrases: list[str] = Field(default_factory=list, description="标志性口癖与经典台词")
    stages: list[CharacterStage] = Field(default_factory=list, description="多阶段服装与造型列表")
    voice_description: str = Field(default="", description="音色特征与语气语调概括")
    image_prompt_positive: str = Field(default="", description="文生图正向提示词（包含一致性外貌描摹）")
    image_prompt_negative: str = Field(default="ugly, deformed, mutated, blurry, bad anatomy", description="文生图负向提示词")
    reference_image_urls: list[str] = Field(default_factory=list, description="参考立绘/图片 URL 列表")
    metadata: dict[str, Any] = Field(default_factory=dict, description="其他扩展数据")


class SceneProfile(BaseModel):
    """场景资产档案 (Scene Profile)。"""
    id: int | None = Field(default=None, description="数据库场景记录 ID")
    name: str = Field(..., description="场景名称（如：云顶天宫大堂、雨夜废弃工厂）")
    space_type: Literal["interior", "exterior", "semi_outdoor"] = Field(
        default="interior", description="空间类型：室内 / 室外 / 半室外"
    )
    architectural_style: str = Field(default="现代奢华", description="建筑与室内装潢风格")
    atmosphere_lighting: str = Field(default="冷暖对冲光影，富有戏剧张力", description="光影、天气与氛围基调")
    color_palette: str = Field(default="深蓝/暗金/银灰", description="主色调与色彩倾向")
    key_elements: list[str] = Field(default_factory=list, description="场景标志性陈设与构图要素")
    image_prompt_positive: str = Field(default="", description="文生图正向场景提示词")
    image_prompt_negative: str = Field(default="people, human, distorted, low quality", description="文生图负向场景提示词")
    reference_image_urls: list[str] = Field(default_factory=list, description="参考场景图 URL 列表")
    metadata: dict[str, Any] = Field(default_factory=dict, description="其他扩展数据")


class PropProfile(BaseModel):
    """道具资产档案 (Prop Profile)。"""
    id: int | None = Field(default=None, description="数据库道具记录 ID")
    name: str = Field(..., description="道具名称（如：至尊黑金龙卡、染血的传家玉佩）")
    category: Literal["token", "weapon", "document", "vehicle", "daily", "special"] = Field(
        default="token", description="道具类型：信物、武器、机密文件/契约、载具、日用品、特殊法器"
    )
    visual_appearance: str = Field(..., description="道具外观细节与材质描述（如：磨砂哑光黑金、烫金龙纹印花）")
    dramatic_function: str = Field(default="", description="在剧情中的戏剧功能（打脸凭证、身份反转、关键线索）")
    owner_character: str = Field(default="", description="专属持有角色")
    image_prompt_positive: str = Field(default="", description="道具特写文生图正向提示词")
    image_prompt_negative: str = Field(default="blurry, bad details, text watermark", description="道具负向提示词")
    reference_image_urls: list[str] = Field(default_factory=list, description="参考道具图 URL 列表")
    metadata: dict[str, Any] = Field(default_factory=dict, description="其他扩展数据")
