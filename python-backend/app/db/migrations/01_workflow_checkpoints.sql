-- =========================================================================
-- LangGraph 工业级状态机持久化 Checkpointer 建表 DDL (MySQL 8.0+)
-- 包含完整的表注释与每一个字段的中文业务注释，防止中文乱码 (UTF-8)
-- =========================================================================

-- 1. 核心检查点快照表
CREATE TABLE IF NOT EXISTS `workflow_checkpoints` (
    `thread_id` VARCHAR(128) NOT NULL COMMENT '工作流会话线程隔离标识 (如 drama_1001 或 drama_1001_ep_3)',
    `checkpoint_ns` VARCHAR(128) NOT NULL DEFAULT '' COMMENT '状态机命名空间/子图标识 (主图为空字符串，子图为 episode_subgraph 等)',
    `checkpoint_id` VARCHAR(128) NOT NULL COMMENT '检查点唯一版本标识 (采用递增自增编号或 UUID6，保证全局单调全序)',
    `parent_checkpoint_id` VARCHAR(128) NULL COMMENT '父级检查点标识 (用于有向无环图分支回溯、重试重放分叉追踪)',
    `type` VARCHAR(64) NOT NULL DEFAULT 'json' COMMENT '检查点数据序列化类型 (json / msgpack / pickle)',
    `checkpoint` MEDIUMTEXT NOT NULL COMMENT 'LangGraph 检查点完整状态快照数据 (包含 channel_versions 与版本游标)',
    `metadata` MEDIUMTEXT NULL COMMENT '检查点业务元数据 JSON (包含执行步骤 step、当前 stage、写入节点 source、耗时等)',
    `created_at` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '检查点生成时间 (ISO-8601 格式，如 2026-03-31T12:00:00.000Z)',
    `updated_at` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '检查点最后更新时间 (ISO-8601 格式)',
    PRIMARY KEY (`thread_id`, `checkpoint_ns`, `checkpoint_id`),
    INDEX `idx_wf_ckpt_parent` (`thread_id`, `checkpoint_ns`, `parent_checkpoint_id`),
    INDEX `idx_wf_ckpt_created` (`thread_id`, `checkpoint_ns`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='LangGraph 工业级状态机检查点核心持久化表，实现进程崩溃秒级恢复与版本重放';

-- 2. 状态通道版本数据载荷表 (按通道独立版本存储，极致节省存储空间并提升更新性能)
CREATE TABLE IF NOT EXISTS `workflow_checkpoint_blobs` (
    `thread_id` VARCHAR(128) NOT NULL COMMENT '工作流会话线程隔离标识 (关联所属线程)',
    `checkpoint_ns` VARCHAR(128) NOT NULL DEFAULT '' COMMENT '状态机命名空间/子图标识',
    `channel` VARCHAR(128) NOT NULL COMMENT '状态通道名称 (对应 LangGraph State 中的具体字段属性名)',
    `version` VARCHAR(128) NOT NULL COMMENT '通道数据版本号 (单调递增游标)',
    `type` VARCHAR(64) NOT NULL DEFAULT 'json' COMMENT '通道数据序列化类型 (json / msgpack / pickle)',
    `blob` MEDIUMTEXT NOT NULL COMMENT '通道数据序列化有效载荷 (Base64 或 JSON 字符串)',
    `created_at` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '通道数据创建时间 (ISO-8601 格式)',
    PRIMARY KEY (`thread_id`, `checkpoint_ns`, `channel`, `version`),
    INDEX `idx_wf_blobs_lookup` (`thread_id`, `checkpoint_ns`, `channel`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='LangGraph 检查点通道数据版本持久化表，记录各通道历史版本载荷';

-- 3. 检查点中间写入通道追踪表 (记录节点并发调度过程中产生的 Pending Writes)
CREATE TABLE IF NOT EXISTS `workflow_checkpoint_writes` (
    `thread_id` VARCHAR(128) NOT NULL COMMENT '工作流会话线程隔离标识',
    `checkpoint_ns` VARCHAR(128) NOT NULL DEFAULT '' COMMENT '状态机命名空间/子图标识',
    `checkpoint_id` VARCHAR(128) NOT NULL COMMENT '所属检查点唯一版本标识',
    `task_id` VARCHAR(128) NOT NULL COMMENT '产生写入的节点执行任务 ID (由 LangGraph 调度器派发)',
    `idx` INT NOT NULL DEFAULT 0 COMMENT '单个任务内多次写入的单调递增索引编号',
    `channel` VARCHAR(128) NOT NULL COMMENT '目标写入状态通道名称',
    `type` VARCHAR(64) NOT NULL DEFAULT 'json' COMMENT '通道增量数据序列化类型 (json / msgpack / pickle)',
    `blob` MEDIUMTEXT NOT NULL COMMENT '通道写入的增量有效载荷',
    `task_path` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '节点调度执行路径 (用于嵌套状态机层级定位)',
    `created_at` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '写入产生时间 (ISO-8601 格式)',
    PRIMARY KEY (`thread_id`, `checkpoint_ns`, `checkpoint_id`, `task_id`, `idx`),
    INDEX `idx_wf_writes_channel` (`thread_id`, `checkpoint_ns`, `channel`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='LangGraph 检查点并发中间通道写入追踪表，确保并发节点写入时序与幂等性';
