-- =========================================================================
-- 短剧业务阶段检查点索引表 (drama_checkpoint_index) 建表 DDL (MySQL 8.0+)
-- 包含完整的表注释与每一个字段的中文业务注释，防止中文乱码 (UTF-8)
-- 支撑工作流两程九阶时光倒流快速定位、状态机断点恢复与人工审核状态跟踪
-- =========================================================================

CREATE TABLE IF NOT EXISTS `drama_checkpoint_index` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键唯一标识',
    `drama_id` VARCHAR(64) NOT NULL COMMENT '业务剧目ID',
    `journey` VARCHAR(32) NOT NULL DEFAULT 'journey_1_literary' COMMENT '所属程 (journey_1_literary / journey_2_visual)',
    `stage` VARCHAR(64) NOT NULL COMMENT '阶段编号或标识 (1~8 或 stage1~stage8)',
    `episode_number` INT NOT NULL DEFAULT 0 COMMENT '集数 (第一程为0，第二程对应实际集数)',
    `wave_number` INT NOT NULL DEFAULT 0 COMMENT '第5阶批次序号 (0 表示非第5阶或整阶段，>=1 表示具体波次 Mini-Arc)',
    `node_name` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '产出此状态的节点名称 (如 audit_stage2, gatekeeper 等)',
    `step_name` VARCHAR(128) NOT NULL DEFAULT '' COMMENT '当前节点名称 (兼容历史别名)',
    `checkpoint_id` VARCHAR(128) NOT NULL COMMENT '对应的 LangGraph 底层 checkpoint_id',
    `thread_id` VARCHAR(128) NOT NULL COMMENT '对应的 thread_id',
    `checkpoint_ns` VARCHAR(128) NOT NULL DEFAULT '' COMMENT '状态机命名空间/子图标识',
    `is_ready_for_next` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否为本阶段合格就绪点 (自审通过或人工批准)',
    `audit_verdict` VARCHAR(32) NULL COMMENT '自审结论 (BLUE_PASS / RED_BLOCKING / HUMAN_APPROVED)',
    `version_tag` VARCHAR(32) NOT NULL DEFAULT 'v1' COMMENT '重跑版本标识 (v1, v2, v3...)',
    `is_current_active` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否为当前最新激活分支',
    `created_at` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '创建时间 (ISO-8601 格式)',
    `updated_at` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '更新时间 (ISO-8601 格式)',
    INDEX `idx_lookup` (`drama_id`, `stage`, `episode_number`, `is_current_active`),
    INDEX `idx_cp` (`thread_id`, `checkpoint_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='短剧工业编排业务与检查点双向映射索引表';
