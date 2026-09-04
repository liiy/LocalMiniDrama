"""契约测试：剧本打包导出、导入与示例剧库服务。

对齐 backend-node:
- GET  /api/v1/dramas/:id/export    -> application/zip 下载流
- POST /api/v1/dramas/import        -> 上传 zip 并恢复全套剧本、角色、分集、分镜、场景、道具、生成记录
- GET  /api/v1/dramas/examples      -> 示例剧库列表
- POST /api/v1/dramas/import-example-> 导入指定示例剧
"""
from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import load_config
from app.db import session as dbm
from app.services.dramaExportService import get_storage_path


def test_export_nonexistent_drama_returns_500(client: TestClient):
    r = client.get("/api/v1/dramas/999999/export")
    assert r.status_code == 500
    assert "不存在" in r.text


def test_import_validation_errors(client: TestClient):
    # 1. 未传文件
    r = client.post("/api/v1/dramas/import")
    assert r.status_code == 400
    assert "请上传 ZIP 文件" in r.text

    # 2. 传损坏或非 zip 内容
    r = client.post(
        "/api/v1/dramas/import",
        files={"file": ("corrupt.zip", b"not a valid zip content", "application/zip")},
    )
    assert r.status_code == 400

    # 3. zip 不包含 project.json
    empty_buf = io.BytesIO()
    with zipfile.ZipFile(empty_buf, "w") as zf:
        zf.writestr("test.txt", "hello")
    empty_buf.seek(0)
    r = client.post(
        "/api/v1/dramas/import",
        files={"file": ("missing_project.zip", empty_buf.getvalue(), "application/zip")},
    )
    assert r.status_code == 400
    assert "缺少 project.json" in r.text

    # 4. project.json 格式错误
    bad_json_buf = io.BytesIO()
    with zipfile.ZipFile(bad_json_buf, "w") as zf:
        zf.writestr("project.json", "{invalid json")
    bad_json_buf.seek(0)
    r = client.post(
        "/api/v1/dramas/import",
        files={"file": ("bad_json.zip", bad_json_buf.getvalue(), "application/zip")},
    )
    assert r.status_code == 400
    assert "project.json 格式错误" in r.text


def test_examples_endpoints(client: TestClient, monkeypatch):
    import tempfile
    tmp_ex_dir = tempfile.mkdtemp(prefix="lmd-examples-")
    monkeypatch.setenv("EXAMPLE_DRAMA_PATH", tmp_ex_dir)

    # 初始为空
    r = client.get("/api/v1/dramas/examples")
    assert r.status_code == 200
    assert r.json()["data"] == []

    # import-example 参数校验
    r = client.post("/api/v1/dramas/import-example", json={})
    assert r.status_code == 400
    assert "请指定示例文件名" in r.json()["error"]["message"]

    r = client.post("/api/v1/dramas/import-example", json={"filename": "../hack.zip"})
    assert r.status_code == 400
    assert "文件名不合法" in r.json()["error"]["message"]

    r = client.post("/api/v1/dramas/import-example", json={"filename": "not_exist.zip"})
    assert r.status_code == 404
    assert "示例文件不存在" in r.json()["error"]["message"]


def test_export_and_import_roundtrip(client: TestClient):
    # 1. 先通过 API 创建剧本
    cr = client.post("/api/v1/dramas", json={"title": "武侠传奇", "genre": "武侠", "description": "一段江湖恩怨"})
    assert cr.status_code == 201
    drama_id = cr.json()["data"]["id"]

    # 2. 数据库中构造角色、场景、分集、分镜、道具等完整数据
    with dbm.engine.begin() as conn:
        # 添加角色
        c_res = conn.execute(
            text(
                "INSERT INTO characters (drama_id, name, role, image_url, local_path, description, created_at, updated_at) "
                "VALUES (:did, '令狐冲', '主角', '/avatar.png', 'characters/linghu.png', '华山派大弟子', NOW(), NOW())"
            ),
            {"did": drama_id},
        )
        char_id = c_res.lastrowid

        # 添加分集
        ep_res = conn.execute(
            text(
                "INSERT INTO episodes (drama_id, episode_number, title, duration, status, created_at, updated_at) "
                "VALUES (:did, 1, '第一集：决战黑木崖', 60, 'completed', NOW(), NOW())"
            ),
            {"did": drama_id},
        )
        ep_id = ep_res.lastrowid

        # 添加场景
        s_res = conn.execute(
            text(
                "INSERT INTO scenes (drama_id, episode_id, location, prompt, image_url, local_path, created_at, updated_at) "
                "VALUES (:did, :eid, '思过崖', 'snowy cliff', '/scenes/cliff.png', 'scenes/cliff.png', NOW(), NOW())"
            ),
            {"did": drama_id, "eid": ep_id},
        )
        scene_id = s_res.lastrowid

        # 添加道具
        p_res = conn.execute(
            text(
                "INSERT INTO props (drama_id, name, type, description, prompt, image_url, local_path, created_at, updated_at) "
                "VALUES (:did, '玄铁重剑', '武器', '绝世神兵', 'black iron sword', '/props/sword.png', 'props/sword.png', NOW(), NOW())"
            ),
            {"did": drama_id},
        )
        prop_id = p_res.lastrowid

        # 添加分镜
        sb_res = conn.execute(
            text(
                "INSERT INTO storyboards (episode_id, scene_id, storyboard_number, image_prompt, characters, image_url, video_url, "
                "local_path, status, duration, created_at, updated_at) "
                "VALUES (:eid, :sid, 1, '令狐冲拔剑出鞘', :chars, '/sb/1.png', '/sb/1.mp4', 'images/sb_1.png', "
                "'completed', 5, NOW(), NOW())"
            ),
            {"eid": ep_id, "sid": scene_id, "chars": json.dumps([char_id])},
        )
        sb_id = sb_res.lastrowid

        # 关联分镜角色
        conn.execute(
            text("INSERT INTO storyboard_characters (storyboard_id, character_id, created_at) VALUES (:sbid, :cid, NOW())"),
            {"sbid": sb_id, "cid": char_id},
        )
        # 关联分镜道具
        conn.execute(
            text("INSERT INTO storyboard_props (storyboard_id, prop_id) VALUES (:sbid, :pid)"),
            {"sbid": sb_id, "pid": prop_id},
        )

        # 添加 frame_prompts 记录
        conn.execute(
            text(
                "INSERT INTO frame_prompts (storyboard_id, frame_type, prompt, description, created_at, updated_at) "
                "VALUES (:sbid, 'first_frame', '出剑瞬间', '初始帧', NOW(), NOW())"
            ),
            {"sbid": sb_id},
        )

        # 添加 image_generations 记录
        conn.execute(
            text(
                "INSERT INTO image_generations (storyboard_id, prompt, image_url, local_path, status, created_at, updated_at) "
                "VALUES (:sbid, '令狐冲拔剑出鞘', '/sb/1.png', 'images/sb_1.png', 'completed', NOW(), NOW())"
            ),
            {"sbid": sb_id},
        )

    # 写入测试所需的 dummy 图片文件到 storage
    cfg = load_config()
    storage_path = get_storage_path(cfg)
    sb_img_file = os.path.join(storage_path, "images", "sb_1.png")
    os.makedirs(os.path.dirname(sb_img_file), exist_ok=True)
    with open(sb_img_file, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\nfake_image_bytes")

    # 3. 导出剧本
    exp_r = client.get(f"/api/v1/dramas/{drama_id}/export")
    assert exp_r.status_code == 200
    assert exp_r.headers["content-type"] == "application/zip"
    assert "filename*=UTF-8''" in exp_r.headers["content-disposition"]

    zip_bytes = exp_r.content
    assert len(zip_bytes) > 0

    # 检查导出的 zip 内容
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        namelist = zf.namelist()
        assert "project.json" in namelist
        project_data = json.loads(zf.read("project.json").decode("utf-8"))
        assert project_data["version"] == "1.4"
        assert project_data["drama"]["title"] == "武侠传奇"
        assert len(project_data["characters"]) == 1
        assert project_data["characters"][0]["name"] == "令狐冲"
        assert len(project_data["scenes"]) == 1
        assert project_data["scenes"][0]["location"] == "思过崖"
        assert len(project_data["props"]) == 1
        assert project_data["props"][0]["name"] == "玄铁重剑"
        assert len(project_data["episodes"]) >= 1
        assert len(project_data["episodes"][0]["storyboards"]) == 1
        exported_sb = project_data["episodes"][0]["storyboards"][0]
        assert exported_sb["image_prompt"] == "令狐冲拔剑出鞘"
        # 角色/道具索引映射
        assert exported_sb["character_indices"] == [0]
        assert exported_sb["prop_indices"] == [0]
        assert exported_sb["scene_index"] == 0
        assert len(exported_sb["image_generations"]) == 1

    # 4. 导入同一个 zip 包（测试重名自动追加 "导入1"）
    imp_r = client.post(
        "/api/v1/dramas/import",
        files={"file": ("wuxia.zip", zip_bytes, "application/zip")},
    )
    assert imp_r.status_code == 201
    imported_drama = imp_r.json()["data"]
    assert imported_drama["title"] == "武侠传奇 导入1"
    new_drama_id = imported_drama["drama_id"]

    # 5. 校验导入后的数据结构与关联
    with dbm.engine.begin() as conn:
        new_chars = conn.execute(
            text("SELECT * FROM characters WHERE drama_id = :did"),
            {"did": new_drama_id},
        ).mappings().all()
        assert len(new_chars) == 1
        assert new_chars[0]["name"] == "令狐冲"
        new_char_id = new_chars[0]["id"]

        new_scenes = conn.execute(
            text("SELECT * FROM scenes WHERE drama_id = :did"),
            {"did": new_drama_id},
        ).mappings().all()
        assert len(new_scenes) == 1
        assert new_scenes[0]["location"] == "思过崖"
        new_scene_id = new_scenes[0]["id"]

        new_props = conn.execute(
            text("SELECT * FROM props WHERE drama_id = :did"),
            {"did": new_drama_id},
        ).mappings().all()
        assert len(new_props) == 1
        assert new_props[0]["name"] == "玄铁重剑"
        new_prop_id = new_props[0]["id"]

        new_eps = conn.execute(
            text("SELECT * FROM episodes WHERE drama_id = :did"),
            {"did": new_drama_id},
        ).mappings().all()
        assert len(new_eps) >= 1
        new_ep_id = new_eps[0]["id"]

        new_sbs = conn.execute(
            text("SELECT * FROM storyboards WHERE episode_id = :eid"),
            {"eid": new_ep_id},
        ).mappings().all()
        assert len(new_sbs) == 1
        new_sb = new_sbs[0]
        assert new_sb["image_prompt"] == "令狐冲拔剑出鞘"
        assert new_sb["scene_id"] == new_scene_id

        # 校验分镜角色关联（优先校验 storyboards.characters JSON 数组）
        assert json.loads(new_sb["characters"]) == [new_char_id]

        # 校验分镜道具关联
        sb_props = conn.execute(
            text("SELECT prop_id FROM storyboard_props WHERE storyboard_id = :sbid"),
            {"sbid": new_sb["id"]},
        ).scalars().all()
        assert sb_props == [new_prop_id]

        # 校验分镜生成历史 image_generations
        new_gens = conn.execute(
            text("SELECT * FROM image_generations WHERE storyboard_id = :sbid"),
            {"sbid": new_sb["id"]},
        ).mappings().all()
        assert len(new_gens) == 1
        assert new_gens[0]["prompt"] == "令狐冲拔剑出鞘"

    # 6. 再次导入 -> 标题应为 "武侠传奇 导入2"
    imp_r2 = client.post(
        "/api/v1/dramas/import",
        files={"file": ("wuxia.zip", zip_bytes, "application/zip")},
    )
    assert imp_r2.status_code == 201
    assert imp_r2.json()["data"]["title"] == "武侠传奇 导入2"
