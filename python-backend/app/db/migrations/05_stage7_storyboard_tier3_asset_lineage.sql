-- =========================================================================
-- 阶段 7 分镜与阶段 6 三级视听资产精准级联透传迁移 DDL (MySQL 8.0+)
-- 严格落实：
-- 1. storyboards 表支持精准关联场景二级子空间 (scene_zone_id) 与三级做旧切片 (scene_weathering_view_id)；
-- 2. storyboard_characters 关联表支持角色二级换装造型 (character_stage_id) 与三级视角微距切片 (stage_view_id)；
-- 3. storyboard_props 关联表支持道具二级战损状态 (damage_state_id) 与三级微距/材质切片 (prop_detail_view_id)；
-- 4. storyboard_audios 音轨表支持发音角色阶段造型 (character_stage_id)，以便捕捉阶段性声音突变；
-- 5. 补充完整字段与索引定义，所有字段附带规范中文 COMMENT 说明。
-- =========================================================================

-- -------------------------------------------------------------------------
-- 1. storyboards 分镜镜头主表升级
-- -------------------------------------------------------------------------
ALTER TABLE `storyboards`
    ADD COLUMN IF NOT EXISTS `scene_zone_id` INT NULL COMMENT '关联场景二级子空间区域 ID，关联 scene_zones.id（明确机位所在子区域与光影）',
    ADD COLUMN IF NOT EXISTS `scene_weathering_view_id` INT NULL COMMENT '关联场景三级做旧与视角渲染切片 ID，关联 scene_weathering_views.id（明确做旧与机位层真值图）',
    ADD COLUMN IF NOT EXISTS `scene_asset_key` VARCHAR(128) NULL COMMENT '当前镜头锁定的场景全景资产 Token，如 ENV_WAREHOUSE_Z01_RAIN';

CREATE INDEX IF NOT EXISTS `idx_storyboard_scene_zone` ON `storyboards` (`scene_zone_id`);
CREATE INDEX IF NOT EXISTS `idx_storyboard_scene_weathering` ON `storyboards` (`scene_weathering_view_id`);

-- -------------------------------------------------------------------------
-- 2. storyboard_characters 分镜角色保序关联从表升级
-- -------------------------------------------------------------------------
ALTER TABLE `storyboard_characters`
    ADD COLUMN IF NOT EXISTS `character_stage_id` INT NULL COMMENT '关联角色二级造型阶段 ID，关联 character_stages.id（锁定本镜角色服装、发型与生命周期阶段）',
    ADD COLUMN IF NOT EXISTS `stage_view_id` INT NULL COMMENT '关联角色三级切片视图 ID，关联 character_stage_views.id（锁定多图参考的具体视角切片，如：4V正视、微距）',
    ADD COLUMN IF NOT EXISTS `emotion_override` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '当前镜头角色微表情或局部情绪覆盖设定（如：冷笑、惊恐微张）';

CREATE INDEX IF NOT EXISTS `idx_sbc_char_stage` ON `storyboard_characters` (`character_stage_id`);
CREATE INDEX IF NOT EXISTS `idx_sbc_stage_view` ON `storyboard_characters` (`stage_view_id`);

-- -------------------------------------------------------------------------
-- 3. storyboard_props 分镜道具保序关联从表升级
-- -------------------------------------------------------------------------
ALTER TABLE `storyboard_props`
    ADD COLUMN IF NOT EXISTS `prop_detail_view_id` INT NULL COMMENT '关联道具三级微距与材质特写切片视图 ID，关联 prop_detail_views.id';

CREATE INDEX IF NOT EXISTS `idx_sbp_prop_detail_view` ON `storyboard_props` (`prop_detail_view_id`);

-- -------------------------------------------------------------------------
-- 4. storyboard_audios 分镜音轨从表升级
-- -------------------------------------------------------------------------
ALTER TABLE `storyboard_audios`
    ADD COLUMN IF NOT EXISTS `character_stage_id` INT NULL COMMENT '关联发音角色造型或状态阶段 ID，关联 character_stages.id（用于特定阶段音色变化/虚弱/情绪突变）';

CREATE INDEX IF NOT EXISTS `idx_sba_char_stage` ON `storyboard_audios` (`character_stage_id`);
