# -*- coding: utf-8 -*-
"""MySQLCheckpointSaver 单元测试与崩溃恢复验证 (Phase 2)

测试覆盖点：
1. setup() 自动创建持久化表结构验证
2. put 与 get_tuple 状态保存与精准回读
3. put_writes 中间通道写入与 pending writes 检索
4. list() 检查点历史序列遍历与 metadata 过滤
5. 进程崩溃恢复仿真：丢弃内存对象后，凭 thread_id 秒级复原状态快照
6. aput / aget_tuple 异步接口协议兼容性验证
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.workflows.checkpointers.mysql_saver import MySQLCheckpointSaver


@pytest.fixture
def sqlite_engine():
    """使用内存 SQLite 模拟持久化数据库 (采用 StaticPool 保证多线程与异步环境共享数据)。"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    return engine


@pytest.fixture
def saver(sqlite_engine):
    """创建并初始化 CheckpointSaver。"""
    session_factory = sessionmaker(bind=sqlite_engine)
    saver_instance = MySQLCheckpointSaver(engine=sqlite_engine, session_factory=session_factory)
    saver_instance.setup()
    return saver_instance


def test_put_and_get_tuple_round_trip(saver):
    """验证基本的 put 保存与 get_tuple 读取。"""
    config = {
        "configurable": {
            "thread_id": "drama_1001",
            "checkpoint_ns": "",
        }
    }
    checkpoint = {
        "v": 1,
        "id": "1-00000000-0000-0000-0000-000000000001",
        "ts": "2026-03-31T12:00:00.000Z",
        "channel_values": {
            "drama_id": 1001,
            "selected_title": "龙王出狱：无敌战神",
            "current_stage": 1,
            "ideation_working_memory": "核心反差：战神隐忍与豪门傲慢",
        },
        "channel_versions": {
            "drama_id": "1",
            "selected_title": "1",
            "current_stage": "1",
            "ideation_working_memory": "1",
        },
        "versions_seen": {},
    }
    metadata = {
        "source": "input",
        "step": 1,
        "writes": {},
        "stage": 1,
    }
    new_versions = {
        "drama_id": "1",
        "selected_title": "1",
        "current_stage": "1",
        "ideation_working_memory": "1",
    }

    # 1. 保存检查点
    saved_config = saver.put(config, checkpoint, metadata, new_versions)
    assert saved_config["configurable"]["checkpoint_id"] == checkpoint["id"]

    # 2. 读取最新检查点
    ckpt_tuple = saver.get_tuple(config)
    assert ckpt_tuple is not None
    assert ckpt_tuple.checkpoint["id"] == checkpoint["id"]
    assert ckpt_tuple.checkpoint["channel_values"]["drama_id"] == 1001
    assert ckpt_tuple.checkpoint["channel_values"]["selected_title"] == "龙王出狱：无敌战神"
    assert ckpt_tuple.checkpoint["channel_values"]["ideation_working_memory"] == "核心反差：战神隐忍与豪门傲慢"
    assert ckpt_tuple.metadata.get("stage") == 1


def test_crash_recovery_simulation(sqlite_engine):
    """仿真进程崩溃：丢弃内存中的 Saver，重新创建 Saver 实例读取数据库。"""
    session_factory = sessionmaker(bind=sqlite_engine)
    saver1 = MySQLCheckpointSaver(engine=sqlite_engine, session_factory=session_factory)
    saver1.setup()

    thread_id = "drama_crash_999"
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}

    # 阶段 1 完成时落库
    ckpt_1 = {
        "v": 1,
        "id": "1-00000000-0000-0000-0000-000000000001",
        "ts": "2026-03-31T12:00:00.000Z",
        "channel_values": {"current_stage": 1, "title": "阶段1产物"},
        "channel_versions": {"current_stage": "1", "title": "1"},
        "versions_seen": {},
    }
    saver1.put(config, ckpt_1, {"step": 1}, {"current_stage": "1", "title": "1"})

    # 阶段 2 完成时落库
    config_step2 = {"configurable": {"thread_id": thread_id, "checkpoint_ns": "", "checkpoint_id": ckpt_1["id"]}}
    ckpt_2 = {
        "v": 1,
        "id": "1-00000000-0000-0000-0000-000000000002",
        "ts": "2026-03-31T12:01:00.000Z",
        "channel_values": {"current_stage": 2, "title": "阶段1产物", "characters": ["林动", "苏清月"]},
        "channel_versions": {"current_stage": "2", "title": "1", "characters": "2"},
        "versions_seen": {},
    }
    saver1.put(config_step2, ckpt_2, {"step": 2}, {"current_stage": "2", "characters": "2"})

    # 模拟崩溃：销毁 saver1 实例
    del saver1

    # 模拟重启服务：新起的 Saver 实例连接同一个数据库
    saver2 = MySQLCheckpointSaver(engine=sqlite_engine, session_factory=session_factory)
    
    # 凭 thread_id 恢复执行
    recovered_tuple = saver2.get_tuple({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
    assert recovered_tuple is not None
    assert recovered_tuple.checkpoint["id"] == ckpt_2["id"]
    assert recovered_tuple.checkpoint["channel_values"]["current_stage"] == 2
    assert recovered_tuple.checkpoint["channel_values"]["characters"] == ["林动", "苏清月"]
    assert recovered_tuple.parent_config["configurable"]["checkpoint_id"] == ckpt_1["id"]


def test_put_writes_and_pending_writes(saver):
    """验证中间写通道记录与 pending_writes 获取。"""
    config = {
        "configurable": {
            "thread_id": "drama_2002",
            "checkpoint_ns": "",
            "checkpoint_id": "1-ckpt-001",
        }
    }
    checkpoint = {
        "v": 1,
        "id": "1-ckpt-001",
        "ts": "2026-03-31T12:00:00.000Z",
        "channel_values": {"stage": 1},
        "channel_versions": {"stage": "1"},
        "versions_seen": {},
    }
    saver.put(config, checkpoint, {"step": 1}, {"stage": "1"})

    # 模拟节点在执行过程中产生写记录
    writes = [
        ("stage", 2),
        ("ideation_working_memory", "最新灵感写入"),
    ]
    saver.put_writes(config, writes, task_id="task_concept_node")

    # 读取检查点元组，验证 pending_writes 包含刚才的写入
    ckpt_tuple = saver.get_tuple(config)
    assert ckpt_tuple is not None
    assert len(ckpt_tuple.pending_writes) == 2
    assert ckpt_tuple.pending_writes[0][0] == "task_concept_node"
    assert ckpt_tuple.pending_writes[0][1] == "stage"
    assert ckpt_tuple.pending_writes[0][2] == 2


def test_list_and_metadata_filter(saver):
    """验证 list 检查点与元数据过滤。"""
    thread_id = "drama_list_test"
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}

    for i in range(1, 4):
        c_id = f"ckpt_{i:03d}"
        ckpt = {
            "v": 1,
            "id": c_id,
            "ts": f"2026-03-31T12:0{i}:00.000Z",
            "channel_values": {"count": i},
            "channel_versions": {"count": str(i)},
            "versions_seen": {},
        }
        saver.put(config, ckpt, {"step": i, "tag": "even" if i % 2 == 0 else "odd"}, {"count": str(i)})

    # 列举所有检查点
    all_ckpts = list(saver.list(config))
    assert len(all_ckpts) == 3
    # 默认倒序排列
    assert all_ckpts[0].checkpoint["id"] == "ckpt_003"
    assert all_ckpts[2].checkpoint["id"] == "ckpt_001"

    # 按 metadata 过滤
    even_ckpts = list(saver.list(config, filter={"tag": "even"}))
    assert len(even_ckpts) == 1
    assert even_ckpts[0].checkpoint["id"] == "ckpt_002"


@pytest.mark.anyio
async def test_async_methods(saver):
    """验证 aput 与 aget_tuple 异步接口。"""
    config = {
        "configurable": {
            "thread_id": "drama_async_test",
            "checkpoint_ns": "",
        }
    }
    checkpoint = {
        "v": 1,
        "id": "async_ckpt_001",
        "ts": "2026-03-31T12:00:00.000Z",
        "channel_values": {"async_val": "ok"},
        "channel_versions": {"async_val": "1"},
        "versions_seen": {},
    }
    await saver.aput(config, checkpoint, {"step": 1}, {"async_val": "1"})

    res = await saver.aget_tuple(config)
    assert res is not None
    assert res.checkpoint["channel_values"]["async_val"] == "ok"
