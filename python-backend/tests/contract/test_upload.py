"""契约安全网：/api/v1/upload/image 与 Node 版 backend-node/src/routes/upload.js 行为等价。

Node 行为基线（multer + Express 全局错误处理的组合结果）：
- 未提供 file              → 400 BAD_REQUEST '请选择文件'
- mimetype 非白名单        → 500 INTERNAL_ERROR '只支持图片格式 (jpg, png, gif, webp)'
                             （multer fileFilter 抛错落到通用错误处理 → 500，非 400）
- 超过 16MB               → 413 FILE_TOO_LARGE '图片大小不能超过 16MB，请压缩后重试'
- 成功                     → { url, path, local_path, filename, size }

存储分层（relPrefix）：
- 无 drama_id / drama_id ≤ 0 / 非数字 → 'uploads'
- drama_id > 0 但剧集不存在            → 'library/uploads'
- drama_id > 0 且剧集存在              → 'projects/{id4}_{yyyymmdd}_{剧名}/uploads'

注：base_url 取自配置，故 url 前缀为 http://localhost:5679/static。
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import text

from app.api.v1 import upload as v1_upload
from app.db import session as dbm

BASE = "/api/v1/upload/image"
MAX_IMAGE_SIZE = 16 * 1024 * 1024


@pytest.fixture(autouse=True)
def _tmp_storage(tmp_path, monkeypatch):
    """把落盘目录指向临时目录（响应体不含存储根，故不影响契约断言）。"""
    monkeypatch.setattr(
        v1_upload,
        "_CFG",
        {"storage": {"local_path": str(tmp_path), "base_url": "http://localhost:5679/static"}},
    )
    yield tmp_path


def _image_bytes(mime: str = "image/png") -> bytes:
    fmt = {
        "image/jpeg": "JPEG",
        "image/jpg": "JPEG",
        "image/png": "PNG",
        "image/gif": "GIF",
        "image/webp": "WEBP",
    }.get(mime, "PNG")
    buf = BytesIO()
    Image.new("RGB", (1, 1), (255, 0, 0)).save(buf, format=fmt)
    return buf.getvalue()


def _upload(client: TestClient, *, filename="a.png", content=None, mime="image/png", **form):
    if filename == "a.png" and mime != "image/png":
        filename = {
            "image/jpeg": "a.jpg",
            "image/jpg": "a.jpg",
            "image/gif": "a.gif",
            "image/webp": "a.webp",
        }.get(mime, filename)
    if content is None:
        content = _image_bytes(mime)
    files = {"file": (filename, content, mime)} if content is not None else None
    return client.post(BASE, files=files, data=form or None)


def _seed_drama(title="测试剧", created_at="2026-03-09T00:00:00.000Z") -> int:
    with dbm.engine.begin() as conn:
        conn.execute(
            text("INSERT INTO dramas (title, created_at, updated_at) VALUES (:t, :c, :c)"),
            {"t": title, "c": created_at},
        )
        return conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()


# ---------------- 错误分支 ----------------


def test_no_file_returns_400(client: TestClient):
    r = client.post(BASE)
    assert r.status_code == 400
    assert r.json()["error"] == {"code": "BAD_REQUEST", "message": "请选择文件"}


def test_non_multipart_body_returns_400(client: TestClient):
    """Node 的 multer 对非 multipart 请求也只得到 req.file=undefined → 400。"""
    r = client.post(BASE, json={"x": 1})
    assert r.status_code == 400
    assert r.json()["error"]["message"] == "请选择文件"


@pytest.mark.parametrize(
    "mime",
    ["text/plain", "application/octet-stream", "image/svg+xml", "application/pdf"],
)
def test_disallowed_mime_returns_400(client: TestClient, mime):
    r = _upload(client, mime=mime)
    assert r.status_code == 400
    assert r.json()["error"] == {
        "code": "UNSUPPORTED_FILE_TYPE",
        "message": "Only jpg, png, gif and webp images are supported",
    }


def test_missing_content_type_is_rejected(client: TestClient):
    """Node: file.mimetype || 'application/octet-stream' → 不在白名单。"""
    r = _upload(client, mime="")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


@pytest.mark.parametrize("mime", ["image/jpeg", "image/jpg", "image/png", "image/gif", "image/webp"])
def test_allowed_mimes_accepted(client: TestClient, mime):
    r = _upload(client, mime=mime)
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_file_too_large_returns_413(client: TestClient, monkeypatch):
    """超限时 413；用缩小后的阈值验证分支（真实阈值由 test_max_size_constant 锁定）。"""
    monkeypatch.setattr(v1_upload, "MAX_IMAGE_SIZE", 2048)
    r = _upload(client, content=b"x" * 4096)
    assert r.status_code == 413
    assert r.json()["error"] == {
        "code": "FILE_TOO_LARGE",
        "message": "Image size cannot exceed 16MB. Please compress and retry.",
    }


def test_valid_image_under_limit_is_accepted(client: TestClient, monkeypatch):
    """Node: limits.fileSize 为上限，等于上限的字节数可通过（超出才报 LIMIT_FILE_SIZE）。"""
    monkeypatch.setattr(v1_upload, "MAX_IMAGE_SIZE", 2048)
    content = _image_bytes("image/png")
    r = _upload(client, content=content)
    assert r.status_code == 200
    assert r.json()["data"]["size"] == len(content)


def test_max_size_constant(client: TestClient):
    """锁定真实阈值 16MB（对应 Node maxSize = 16 * 1024 * 1024）。"""
    assert v1_upload.MAX_IMAGE_SIZE == MAX_IMAGE_SIZE
    assert v1_upload.ALLOWED_IMAGE_TYPES == (
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/gif",
        "image/webp",
    )


# ---------------- 成功响应 ----------------


def test_success_response_shape(client: TestClient):
    content = _image_bytes("image/png")
    r = _upload(client, filename="photo.png", content=content)
    assert r.status_code == 200
    data = r.json()["data"]
    assert set(data) == {"url", "path", "local_path", "filename", "size"}
    assert data["filename"] == "photo.png"
    assert data["size"] == len(content)
    assert data["path"] == data["local_path"]
    # url 由 base_url + 相对路径拼成
    assert data["url"] == f"http://localhost:5679/static/{data['local_path']}"


def test_extension_taken_from_original_name(client: TestClient):
    r = _upload(client, filename="clip.webp", content=_image_bytes("image/webp"), mime="image/webp")
    assert r.json()["data"]["local_path"].endswith(".webp")


def test_extension_is_required(client: TestClient):
    """Node: path.extname(originalName) || '.png'"""
    r = _upload(client, filename="noext")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "BAD_REQUEST"


def test_filename_pattern(client: TestClient):
    """文件名形如 20260829T045448_{uuid}{ext}。"""
    import re

    local_path = _upload(client, filename="a.png", content=_image_bytes("image/png")).json()["data"]["local_path"]
    name = local_path.rsplit("/", 1)[-1]
    assert re.match(r"^\d{8}T\d{6}_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.png$", name)


# ---------------- extract-description-from-image ----------------


def test_extract_description_validation_errors(client: TestClient):
    # 缺少 image_url
    r = client.post("/api/v1/extract-description-from-image", json={})
    assert r.status_code == 400
    assert "缺少 image_url" in r.text

    # entity_type 非法
    r = client.post(
        "/api/v1/extract-description-from-image",
        json={"image_url": "http://example.com/img.png", "entity_type": "unknown"},
    )
    assert r.status_code == 400
    assert "entity_type 需为 character/scene/prop" in r.text


def test_extract_description_success(client: TestClient, monkeypatch):
    import app.services.aiClient as ai_client

    def mock_extract(db, log, entity_type, image_url, entity_name=None):
        return {"ok": True, "description": f"成功识别{entity_type}: {entity_name}"}

    monkeypatch.setattr(ai_client, "extract_description_from_image", mock_extract)

    r = client.post(
        "/api/v1/extract-description-from-image",
        json={
            "image_url": "http://example.com/character.png",
            "entity_type": "character",
            "entity_name": "张无忌",
        },
    )
    assert r.status_code == 200
    assert r.json()["data"]["description"] == "成功识别character: 张无忌"


def test_extract_description_refusal_returns_400(client: TestClient, monkeypatch):
    import app.services.aiClient as ai_client

    def mock_extract(db, log, entity_type, image_url, entity_name=None):
        return {"ok": False, "error": "模型因安全策略拒绝描述"}

    monkeypatch.setattr(ai_client, "extract_description_from_image", mock_extract)

    r = client.post(
        "/api/v1/extract-description-from-image",
        json={
            "image_url": "http://example.com/photo.png",
            "entity_type": "character",
        },
    )
    assert r.status_code == 400
    assert "模型因安全策略拒绝描述" in r.text



def test_file_actually_written(client: TestClient, _tmp_storage):
    content = _image_bytes("image/png")
    local_path = _upload(client, filename="a.png", content=content).json()["data"]["local_path"]
    written = Path(_tmp_storage) / local_path
    assert written.is_file()
    assert written.read_bytes() == content


# ---------------- drama_id 分层 ----------------


def test_no_drama_id_goes_to_uploads_root(client: TestClient):
    local_path = _upload(client).json()["data"]["local_path"]
    assert local_path.startswith("uploads/")


@pytest.mark.parametrize("raw", ["0", "-1", "abc", "  ", ""])
def test_non_positive_or_invalid_drama_id_goes_to_uploads_root(client: TestClient, raw):
    """did 非有限值或 ≤ 0 → projectSubdir 保持 None（连 storageLayout 都不会调用）。"""
    local_path = _upload(client, drama_id=raw).json()["data"]["local_path"]
    assert local_path.startswith("uploads/")


def test_unknown_drama_id_goes_to_library(client: TestClient):
    local_path = _upload(client, drama_id="999999").json()["data"]["local_path"]
    assert local_path.startswith("library/uploads/")


def test_known_drama_goes_to_project_dir(client: TestClient):
    did = _seed_drama(title="我的剧集", created_at="2026-03-09T00:00:00.000Z")
    local_path = _upload(client, drama_id=str(did)).json()["data"]["local_path"]
    assert local_path.startswith(f"projects/{did:04d}_20260309_我的剧集/uploads/")


def test_project_dir_uses_existing_storage_folder_label(client: TestClient):
    """metadata 已有 storage_folder_label 时沿用（用户改剧名后目录不分裂）。"""
    did = _seed_drama(title="新剧名", created_at="2026-01-02T00:00:00.000Z")
    with dbm.engine.begin() as conn:
        conn.execute(
            text("UPDATE dramas SET metadata = :m WHERE id = :id"),
            {"m": '{"storage_folder_label":"老目录"}', "id": did},
        )
    local_path = _upload(client, drama_id=str(did)).json()["data"]["local_path"]
    assert local_path.startswith(f"projects/{did:04d}_20260102_老目录/uploads/")


def test_first_upload_writes_storage_folder_label(client: TestClient):
    """首次上传会把 storage_folder_label 固化进 dramas.metadata。"""
    did = _seed_drama(title="固化剧名", created_at="2026-01-02T00:00:00.000Z")
    _upload(client, drama_id=str(did))
    with dbm.engine.begin() as conn:
        meta = conn.execute(text("SELECT metadata FROM dramas WHERE id = :id"), {"id": did}).scalar()
    assert '"storage_folder_label":"固化剧名"' in meta


def test_folder_label_sanitized_and_truncated(client: TestClient):
    """剧名中的非法字符/空格 → 下划线，并截断到 20 字符。"""
    title = "剧 名/含*非法 字符" + "长" * 30
    did = _seed_drama(title=title, created_at="2026-01-02T00:00:00.000Z")
    local_path = _upload(client, drama_id=str(did)).json()["data"]["local_path"]

    prefix = f"{did:04d}_20260102_"
    subdir = local_path.split("/")[1]  # projects/<subdir>/uploads/<name>
    assert subdir.startswith(prefix)
    label = subdir[len(prefix) :]
    assert "/" not in label and "*" not in label and " " not in label
    assert len(label) == 20  # sanitizeFolderLabel 截断上限


# ---------------- 配置无关性 ----------------


def test_url_falls_back_to_relative_static_when_no_base_url(client: TestClient, monkeypatch, _tmp_storage):
    """Node: baseUrl 为空串 → /static/{relativePath}。"""
    monkeypatch.setattr(v1_upload, "_CFG", {"storage": {"local_path": str(_tmp_storage), "base_url": ""}})
    r = _upload(client)
    assert r.json()["data"]["url"].startswith("/static/uploads/")
