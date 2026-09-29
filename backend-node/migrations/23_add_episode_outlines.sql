-- 23_add_episode_outlines.sql: 分集大纲表独立分立与 episodes 表关联字段
-- 遵循 DDD 聚合根解耦理念，将创作设计蓝图 (episode_outlines) 与生产资产容器 (episodes) 物理分立

CREATE TABLE IF NOT EXISTS episode_outlines (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  drama_id          INTEGER NOT NULL DEFAULT 0,
  episode_number    INTEGER NOT NULL DEFAULT 0,
  title             TEXT DEFAULT '',
  dual_helix_task   TEXT,
  subtext_matrix    TEXT,
  hook_3s           TEXT,
  micro_twist_45s   TEXT,
  cliffhanger_end   TEXT,
  target_duration_s INTEGER DEFAULT 90,
  raw_outline_card  TEXT,
  created_at        TEXT NOT NULL DEFAULT '',
  updated_at        TEXT NOT NULL DEFAULT '',
  deleted_at        TEXT
);

CREATE INDEX IF NOT EXISTS ix_episode_outlines_drama_id ON episode_outlines(drama_id);
CREATE INDEX IF NOT EXISTS ix_episode_outlines_drama_ep ON episode_outlines(drama_id, episode_number);

ALTER TABLE episodes ADD COLUMN outline_id INTEGER;
CREATE INDEX IF NOT EXISTS ix_episodes_outline_id ON episodes(outline_id);
