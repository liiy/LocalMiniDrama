-- =========================================================================
-- 阶段 6 视听资产编码体系、同类依赖 DAG 与结构化提示词分层存储迁移 DDL (MySQL 8.0+)
-- 严格落实：
-- 1. 角色、场景、道具的全局确定性业务代号 (asset_key / scene_code / prop_code)；
-- 2. 同类资产基准视图标记 (is_benchmark) 与图生图来源底图引用 (parent_asset_key)；
-- 3. 图生图生成模式 (generation_mode)、重绘降噪度 (denoise_strength) 与控制网参数 (control_type)；
-- 4. 提示词四层解耦存储 (identity_prompt / delta_prompt / image_prompt / negative_prompt)；
-- 5. 包含完整表字段中文 COMMENT 说明。
-- =========================================================================

-- -------------------------------------------------------------------------
-- 1. 角色领域主表与多级切片扩展
-- -------------------------------------------------------------------------
-- characters 主表：增加全剧最高真理源正脸肖像资产 Key
ALTER TABLE `characters`
    ADD COLUMN IF NOT EXISTS `benchmark_asset_key` VARCHAR(128) NULL COMMENT '全剧最高真理源正脸肖像资产Key (如 CHAR_LUCHEN_T1_BASE_PORTRAIT)';

-- character_stage_views 切片表：增加切片编码、血统依赖、图生图控制参数与解耦提示词
ALTER TABLE `character_stage_views`
    ADD COLUMN IF NOT EXISTS `asset_key` VARCHAR(128) NULL COMMENT '切片全局唯一资产编码 (如 CHAR_LUCHEN_T1_4V_FRONT)',
    ADD COLUMN IF NOT EXISTS `parent_asset_key` VARCHAR(128) NULL COMMENT '图生图来源底图资产Key (如 CHAR_LUCHEN_T1_BASE_COSTUME)',
    ADD COLUMN IF NOT EXISTS `generation_mode` VARCHAR(32) NOT NULL DEFAULT 't2i' COMMENT '生成模式 (t2i:文生图, i2i:图生图外绘, controlnet:骨骼约束, inpaint:局部重绘)',
    ADD COLUMN IF NOT EXISTS `denoise_strength` FLOAT NOT NULL DEFAULT 0.0 COMMENT '重绘降噪度 (0.00~1.00, 文生图固定为0.0)',
    ADD COLUMN IF NOT EXISTS `control_type` VARCHAR(64) NULL COMMENT '控制网类型 (openpose/depth/lineart/inpaint_only)',
    ADD COLUMN IF NOT EXISTS `identity_prompt` MEDIUMTEXT NULL COMMENT '面部与生物学基因锚点词 (锁定不变特征)',
    ADD COLUMN IF NOT EXISTS `delta_prompt` MEDIUMTEXT NULL COMMENT '当前视图姿态/视角/服饰增量提示词',
    ADD COLUMN IF NOT EXISTS `is_benchmark` TINYINT NOT NULL DEFAULT 0 COMMENT '是否为全剧最高真理源基准 (1=全剧唯一Face ID, 0=常规衍生视图)';

CREATE INDEX IF NOT EXISTS `idx_csv_asset_key` ON `character_stage_views` (`asset_key`);
CREATE INDEX IF NOT EXISTS `idx_csv_parent_asset_key` ON `character_stage_views` (`parent_asset_key`);

-- -------------------------------------------------------------------------
-- 2. 空间场景主表与多级从表扩展
-- -------------------------------------------------------------------------
-- scenes 主表：增加场景业务编码与全景基准键
ALTER TABLE `scenes`
    ADD COLUMN IF NOT EXISTS `scene_code` VARCHAR(64) NULL COMMENT '场景唯一业务代号 (如 ENV_OFFICE, ENV_WAREHOUSE)',
    ADD COLUMN IF NOT EXISTS `benchmark_asset_key` VARCHAR(128) NULL COMMENT '全景超广角空镜基准资产Key (如 ENV_OFFICE_Z01_WIDE)';

-- scene_zones 区域从表：增加区域代号与父区域指针
ALTER TABLE `scene_zones`
    ADD COLUMN IF NOT EXISTS `zone_code` VARCHAR(64) NULL COMMENT '子区域空间代号 (如 Z01_MAIN, Z02_WINDOW)',
    ADD COLUMN IF NOT EXISTS `parent_zone_id` INT NOT NULL DEFAULT 0 COMMENT '父级空间区域 ID (用于嵌套空间表达)';

-- scene_weathering_views 做旧/切片表：增加切片编码、虚化依赖与负向提示词
ALTER TABLE `scene_weathering_views`
    ADD COLUMN IF NOT EXISTS `asset_key` VARCHAR(128) NULL COMMENT '场景切片唯一资产编码 (如 ENV_OFFICE_Z01_OTS_BG)',
    ADD COLUMN IF NOT EXISTS `parent_asset_key` VARCHAR(128) NULL COMMENT '演变/虚化父底图资产Key (如 ENV_OFFICE_Z01_WIDE)',
    ADD COLUMN IF NOT EXISTS `generation_mode` VARCHAR(32) NOT NULL DEFAULT 't2i' COMMENT '生成模式 (t2i:全景空镜, i2i:天气演变, depth_blur:过肩虚化板)',
    ADD COLUMN IF NOT EXISTS `denoise_strength` FLOAT NOT NULL DEFAULT 0.0 COMMENT '重绘降噪度 (如 0.30 景深虚化, 0.48 暴雨天气重绘)',
    ADD COLUMN IF NOT EXISTS `negative_prompt` MEDIUMTEXT NULL COMMENT '场景专用排他性负向提示词',
    ADD COLUMN IF NOT EXISTS `is_benchmark` TINYINT NOT NULL DEFAULT 0 COMMENT '是否为空间几何基准视图 (1=全景几何基准, 0=衍生层)',
    ADD COLUMN IF NOT EXISTS `is_primary` TINYINT NOT NULL DEFAULT 0 COMMENT '是否为当前区域默认主视觉图 (0=否, 1=是)';

CREATE INDEX IF NOT EXISTS `idx_swv_asset_key` ON `scene_weathering_views` (`asset_key`);
CREATE INDEX IF NOT EXISTS `idx_swv_parent_asset_key` ON `scene_weathering_views` (`parent_asset_key`);

-- -------------------------------------------------------------------------
-- 3. 核心道具主表与多级从表扩展
-- -------------------------------------------------------------------------
-- props 主表：增加道具业务编码与完好态基准键
ALTER TABLE `props`
    ADD COLUMN IF NOT EXISTS `prop_code` VARCHAR(64) NULL COMMENT '道具唯一业务代号 (如 PROP_JADE_PENDANT)',
    ADD COLUMN IF NOT EXISTS `benchmark_asset_key` VARCHAR(128) NULL COMMENT '道具初始完好态静态真值资产Key (如 PROP_JADE_S0_STATIC)';

-- prop_damage_states 状态表：增加状态业务代号
ALTER TABLE `prop_damage_states`
    ADD COLUMN IF NOT EXISTS `state_code` VARCHAR(64) NULL COMMENT '破坏状态代号 (如 S0_PRISTINE, S1_CRACKED, S2_BROKEN)';

-- prop_detail_views 切片表：增加切片编码、战损依赖与负向提示词
ALTER TABLE `prop_detail_views`
    ADD COLUMN IF NOT EXISTS `asset_key` VARCHAR(128) NULL COMMENT '道具切片唯一资产编码 (如 PROP_JADE_S1_ACTION)',
    ADD COLUMN IF NOT EXISTS `parent_asset_key` VARCHAR(128) NULL COMMENT '战损演进上一级父底图Key (如 PROP_JADE_S0_STATIC)',
    ADD COLUMN IF NOT EXISTS `generation_mode` VARCHAR(32) NOT NULL DEFAULT 't2i' COMMENT '生成模式 (t2i:初始静态特写, i2i:微距衍生, inpaint:局部破坏重绘)',
    ADD COLUMN IF NOT EXISTS `denoise_strength` FLOAT NOT NULL DEFAULT 0.0 COMMENT '战损局部重绘降噪度 (如 0.45~0.50)',
    ADD COLUMN IF NOT EXISTS `negative_prompt` MEDIUMTEXT NULL COMMENT '道具专用排他性负向提示词',
    ADD COLUMN IF NOT EXISTS `is_benchmark` TINYINT NOT NULL DEFAULT 0 COMMENT '是否为初始物证真值基准 (1=初始完好基准, 0=破坏衍生态)',
    ADD COLUMN IF NOT EXISTS `is_primary` TINYINT NOT NULL DEFAULT 0 COMMENT '是否为当前损坏形态主视图 (0=否, 1=是)';

CREATE INDEX IF NOT EXISTS `idx_pdv_asset_key` ON `prop_detail_views` (`asset_key`);
CREATE INDEX IF NOT EXISTS `idx_pdv_parent_asset_key` ON `prop_detail_views` (`parent_asset_key`);

-- -------------------------------------------------------------------------
-- 4. 统管 assets 表结构化依赖扩展
-- -------------------------------------------------------------------------
ALTER TABLE `assets`
    ADD COLUMN IF NOT EXISTS `parent_asset_id` VARCHAR(128) NULL COMMENT '血统父级资产Key (用于直接构建 DAG 拓扑)',
    ADD COLUMN IF NOT EXISTS `generation_mode` VARCHAR(32) NOT NULL DEFAULT 't2i' COMMENT '生成管线模式 (t2i/i2i/controlnet/inpaint/depth_blur/tts_master)',
    ADD COLUMN IF NOT EXISTS `denoise_strength` FLOAT NOT NULL DEFAULT 0.0 COMMENT '重绘去噪强度参数',
    ADD COLUMN IF NOT EXISTS `is_benchmark` TINYINT NOT NULL DEFAULT 0 COMMENT '是否为资产类别下的真理源基准 (1=是, 0=否)',
    ADD COLUMN IF NOT EXISTS `ref_table` VARCHAR(64) NULL COMMENT '实体引用的业务从表名 (character_stage_views/scene_weathering_views/prop_detail_views)',
    ADD COLUMN IF NOT EXISTS `ref_id` INT NULL COMMENT '实体引用的业务从表主键 ID';

CREATE INDEX IF NOT EXISTS `idx_assets_parent_asset_id` ON `assets` (`parent_asset_id`);
CREATE INDEX IF NOT EXISTS `idx_assets_ref_table_id` ON `assets` (`ref_table`, `ref_id`);
