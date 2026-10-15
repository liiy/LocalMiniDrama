-- 24_stage6_asset_truth_enhancements.sql: 阶段6视听资产真理源全量落库支持
-- 1. 扩展 assets 表：增加业务语义键、提示词、生图参数和元数据
ALTER TABLE assets ADD COLUMN asset_key TEXT;
ALTER TABLE assets ADD COLUMN prompt TEXT;
ALTER TABLE assets ADD COLUMN negative_prompt TEXT;
ALTER TABLE assets ADD COLUMN params TEXT;
ALTER TABLE assets ADD COLUMN metadata TEXT;

-- 2. 角色声音档案表：增加母卡 SSOT 标记 (1=全剧母卡, 0=分集临时变声)
ALTER TABLE character_voice_profiles ADD COLUMN is_master_card INTEGER DEFAULT 0;

-- 3. 角色多阶段造型表：增加阶段代号与父阶段指针 (支撑 lineage DAG)
ALTER TABLE character_stages ADD COLUMN stage_code TEXT;
ALTER TABLE character_stages ADD COLUMN parent_stage_id INTEGER DEFAULT 0;

-- 4. 道具损伤形态表：增加父形态指针 (支撑道具破损 lineage DAG)
ALTER TABLE prop_damage_states ADD COLUMN parent_state_id INTEGER DEFAULT 0;
