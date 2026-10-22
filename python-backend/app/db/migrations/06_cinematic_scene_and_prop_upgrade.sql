-- =========================================================================
-- 阶段 6 场景视听细化四大支柱、配饰物理晋升与极简按需派生架构升级 DDL (MySQL 8.0+)
-- 严格落实：
-- 1. scenes 主表扩充电影工业级四大视听支柱（空间拓扑、光学系统、年代包浆、微气候介质）与装配提示词；
-- 2. scene_zones 二级机位表扩充极简按需触发依据与视线轴线朝向；
-- 3. props 道具表扩充纯净物性生图提示词、配饰物理晋升标记与全息物理规格；
-- 4. prop_damage_states 战损演进表扩充形态剧变触发动词与演变生图提示词；
-- 5. 补充完整字段与索引定义，所有字段附带规范中文 COMMENT 说明。
-- =========================================================================

-- -------------------------------------------------------------------------
-- 1. scenes 空间场景主表升级（电影工业级四大视听支柱）
-- -------------------------------------------------------------------------
ALTER TABLE `scenes`
    ADD COLUMN IF NOT EXISTS `visual_prompt` MEDIUMTEXT NULL 
        COMMENT '全景标准生图完整提示词(按四大视听支柱组装之最终生图Prompt)',
    ADD COLUMN IF NOT EXISTS `spatial_topology` TEXT NULL 
        COMMENT '视听支柱1: 空间几何拓扑与前/中/后三层景深遮挡构图描述',
    ADD COLUMN IF NOT EXISTS `lighting_rig` TEXT NULL 
        COMMENT '视听支柱2: 电影光学光位系统(主光Key/辅光Fill/实用光源Practical/色温K值与冷暖对冲)',
    ADD COLUMN IF NOT EXISTS `period_patina` TEXT NULL 
        COMMENT '视听支柱3: 时代工业制式与生活做旧包浆(建筑年代/材质规格/墙地面污渍与受潮风化痕迹)',
    ADD COLUMN IF NOT EXISTS `atmospheric_medium` TEXT NULL 
        COMMENT '视听支柱4: 微气候与空气悬浮介质(丁达尔灰尘颗粒/线香轻烟/冷雨挂壁凝结水珠)';

-- -------------------------------------------------------------------------
-- 2. scene_zones 场景空间机位表升级（极简按需派生审计依据）
-- -------------------------------------------------------------------------
ALTER TABLE `scene_zones`
    ADD COLUMN IF NOT EXISTS `trigger_reason` VARCHAR(255) NULL DEFAULT 'DEFAULT_ZONE' 
        COMMENT '极简派生审计依据: 记录派生子机位的具体剧情驱动(如: 审讯室铁椅视线反打/两拨势力空间对峙/法庭旁听席)',
    ADD COLUMN IF NOT EXISTS `spatial_framing` TEXT NULL 
        COMMENT '该子机位特定的镜头焦段、取景范围与视线轴线朝向描述';

-- -------------------------------------------------------------------------
-- 3. props 核心道具主表升级（纯净物性隔离与配饰物理晋升）
-- -------------------------------------------------------------------------
ALTER TABLE `props`
    ADD COLUMN IF NOT EXISTS `visual_prompt` MEDIUMTEXT NULL 
        COMMENT '核心物证初始形态标准生图提示词(物理材质+承载介质+微观破损，严格隔离人脸生物特征)',
    ADD COLUMN IF NOT EXISTS `narrative_category` VARCHAR(64) NOT NULL DEFAULT 'hero' 
        COMMENT '道具叙事层级: hero(承载重大剧情反转的核心物证)/interactive(人物手持功能器具)/ambient(生活环境杂物)',
    ADD COLUMN IF NOT EXISTS `is_accessory_promoted` TINYINT(1) NOT NULL DEFAULT 0 
        COMMENT '配饰晋升标记: 0=常规独立道具, 1=从角色随身首饰经剧情物理剥离/破坏动作晋升为真正道具',
    ADD COLUMN IF NOT EXISTS `physical_specs` JSON NULL 
        COMMENT '物理规格全息定义: 包含材质细节、毫米级破坏尺度描述、质量手感及专属拟音提升指令(+3dB)';

-- -------------------------------------------------------------------------
-- 4. prop_damage_states 道具战损形态演进表升级
-- -------------------------------------------------------------------------
ALTER TABLE `prop_damage_states`
    ADD COLUMN IF NOT EXISTS `trigger_action` VARCHAR(128) NULL 
        COMMENT '形态剧变触发动词: 记录造成此战损态的剧本文学动作(如: 撕开封口/子弹贯穿/烈火灼烧半截)',
    ADD COLUMN IF NOT EXISTS `visual_prompt` MEDIUMTEXT NULL 
        COMMENT '该损伤演进阶段专属的生图提示词(基于母道具基础形态之增量破坏描述)';
