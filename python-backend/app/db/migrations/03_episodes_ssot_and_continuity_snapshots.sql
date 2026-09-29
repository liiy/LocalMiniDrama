-- =========================================================================
-- 阶段 5 视听剧本与跨集时空快照规范化迁移 DDL (MySQL 8.0+)
-- 严格遵守单一事实源 (SSOT) 原则：
-- 1. 大纲创意设计数据 100% 归属于 episode_outlines 表；
-- 2. episodes 表彻底去冗余，仅保留剧本纯文本、AST分块、时空连续性快照与自审结果；
-- 3. 包含完整表字段中文 COMMENT 说明。
-- =========================================================================

-- 1. 为 episodes 补充剧本质量自审字段与时空快照字段（如果尚不存在）
ALTER TABLE `episodes`
    ADD COLUMN IF NOT EXISTS `audit_verdict` VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT '剧本自审结论：passed(通过)/need_revision(待修改)/rejected(否决)' AFTER `status`,
    ADD COLUMN IF NOT EXISTS `audit_report` MEDIUMTEXT NULL COMMENT '剧本结构化自审与合规审查报告 JSON（包含台词精简度、钩子紧凑度、情感张力评分）' AFTER `audit_verdict`,
    ADD COLUMN IF NOT EXISTS `physical_snapshot_start` MEDIUMTEXT NULL COMMENT '承接上一集出场 0 秒物理快照 JSON（角色站位、残余伤情、手持道具、光影残留）' AFTER `audit_report`,
    ADD COLUMN IF NOT EXISTS `physical_snapshot_end` MEDIUMTEXT NULL COMMENT '本集集尾出场终态物理快照 JSON（用于下一集开场直接继承，保障时空咬合连续性）' AFTER `physical_snapshot_start`;

-- 2. 优化组合查询索引，加速单集时空快照链毫秒级加载
CREATE INDEX IF NOT EXISTS `idx_episodes_drama_ep` ON `episodes` (`drama_id`, `episode_number`);
CREATE INDEX IF NOT EXISTS `idx_episodes_outline` ON `episodes` (`outline_id`);

-- 3. 历史数据清理说明：
-- 建议在业务稳定后执行以下清理（移除原大纲冗余列）：
-- ALTER TABLE `episodes` DROP COLUMN `description`;
-- ALTER TABLE `episodes` DROP COLUMN `hook_cliffhanger`;
