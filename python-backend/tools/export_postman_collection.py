"""Export registered FastAPI routes as a categorized Postman collection.

Run from the repository root with the Python backend environment active.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.main import create_app  # noqa: E402


TAG_NAMES = {
    "auth": "身份与鉴权", "settings": "应用设置", "promptOverrides": "提示词覆盖",
    "sceneModelMap": "场景模型映射", "characterLibrary": "角色素材库",
    "sceneLibrary": "场景素材库", "propLibrary": "道具素材库", "dramas": "剧本与项目",
    "characters": "角色管理", "scenes": "场景管理", "props": "道具管理",
    "storyboards": "分镜管理", "episodes": "分集管理", "generation": "内容生成",
    "ai-configs": "AI 服务与模型配置", "tasks": "异步任务", "assets": "生成资产",
    "upload": "文件上传", "audio": "音频生成", "images": "图片生成与管理",
    "videos": "视频生成与管理", "video-merges": "视频合并",
    "platform": "平台能力（Prompt、Skill、Context、Workflow、Memory）",
    "Script Studio V2.0": "剧本创作工坊",
    "Workflow Control & Time Travel": "工作流控制与历史重跑",
    "other": "服务状态与监控",
}
METHOD_ORDER = {name: i for i, name in enumerate(("get", "post", "put", "patch", "delete", "options", "head"))}


def resolve_schema(schema: Any, components: dict[str, Any], seen: frozenset[str] = frozenset(), depth: int = 0) -> Any:
    if not isinstance(schema, dict) or depth > 7:
        return schema
    result = {k: v for k, v in schema.items() if k not in {"$ref", "properties", "items", "allOf", "oneOf", "anyOf"}}
    ref = schema.get("$ref")
    if ref:
        name = ref.rsplit("/", 1)[-1]
        target = components.get(name)
        if name in seen:
            return {"$ref": ref}
        if target:
            result = {**resolve_schema(target, components, seen | {name}, depth + 1), **result}
    for key in ("properties", "items", "allOf", "oneOf", "anyOf"):
        if key not in schema:
            continue
        value = schema[key]
        if key == "properties" and isinstance(value, dict):
            result[key] = {k: resolve_schema(v, components, seen, depth + 1) for k, v in value.items()}
        elif isinstance(value, list):
            result[key] = [resolve_schema(v, components, seen, depth + 1) for v in value]
        else:
            result[key] = resolve_schema(value, components, seen, depth + 1)
    return result


def sample_value(schema: Any, components: dict[str, Any], seen: frozenset[str] = frozenset()) -> Any:
    if not isinstance(schema, dict):
        return ""
    ref = schema.get("$ref")
    if ref:
        name = ref.rsplit("/", 1)[-1]
        if name in seen:
            return None
        schema = {**components.get(name, {}), **schema}
        seen = seen | {name}
    for key in ("example", "default"):
        if key in schema and schema[key] is not None:
            return schema[key]
    if schema.get("enum"):
        return schema["enum"][0]

    # 处理 OpenAPI 3.1 anyOf / oneOf 联合类型 (例如 int | None)
    for union_key in ("anyOf", "oneOf"):
        if schema.get(union_key):
            variants = schema[union_key]
            non_null_variants = [v for v in variants if isinstance(v, dict) and v.get("type") != "null"]
            chosen = non_null_variants[0] if non_null_variants else (variants[0] if variants else {})
            merged = {**chosen}
            for k in ("example", "default"):
                if k in schema and k not in merged:
                    merged[k] = schema[k]
            return sample_value(merged, components, seen)

    # 处理 allOf 继承组合
    if schema.get("allOf"):
        merged = {}
        for part in schema["allOf"]:
            if isinstance(part, dict):
                merged.update(part)
        merged.update({k: v for k, v in schema.items() if k != "allOf"})
        return sample_value(merged, components, seen)

    kind = schema.get("type")
    if kind == "object" or "properties" in schema:
        return {k: sample_value(v, components, seen) for k, v in schema.get("properties", {}).items()}
    if kind == "array":
        return [sample_value(schema.get("items", {}), components, seen)]
    if kind in {"integer", "number"}:
        return 0
    if kind == "boolean":
        return False
    if kind == "null":
        return None
    if kind == "string" or schema.get("format"):
        return ""
    if "default" in schema:
        return schema["default"]
    return {}


def render_schema(schema: dict[str, Any], components: dict[str, Any]) -> str:
    return json.dumps(resolve_schema(schema, components), ensure_ascii=False, indent=2)


def describe_operation(operation: dict[str, Any], components: dict[str, Any]) -> str:
    lines = []
    if operation.get("summary"):
        lines.append(f"**接口摘要：** {operation['summary']}")
    if operation.get("description"):
        lines.extend(["", operation["description"].strip()])
    parameters = operation.get("parameters", [])
    if parameters:
        lines.extend(["", "### 参数"])
        for parameter in parameters:
            schema = resolve_schema(parameter.get("schema", {}), components)
            detail = "必填" if parameter.get("required") else "可选"
            if parameter.get("description"):
                detail += "；" + parameter["description"].strip()
            if "default" in schema:
                detail += f"；默认值：`{schema['default']}`"
            if schema.get("enum"):
                detail += f"；可选值：`{'`, `'.join(map(str, schema['enum']))}`"
            detail += f"；类型：`{schema.get('type', 'string')}{'/' + schema['format'] if schema.get('format') else ''}`"
            lines.append(f"- `{parameter.get('name')}` ({parameter.get('in', 'query')})：{detail}")
    body = operation.get("requestBody")
    if body:
        lines.extend(["", "### 请求体"])
        if body.get("description"):
            lines.append(body["description"].strip())
        if body.get("required"):
            lines.append("请求体必填。")
        for media_type, media in body.get("content", {}).items():
            lines.extend([f"Content-Type：`{media_type}`", "```json", render_schema(media.get("schema", {}), components), "```"])
    if operation.get("responses"):
        lines.extend(["", "### 响应"])
        for status, response in operation["responses"].items():
            lines.append(f"- `{status}`：{response.get('description', '')}".rstrip())
            for media_type, media in response.get("content", {}).items():
                if media.get("schema"):
                    lines.extend([f"  - `{media_type}` schema：", "```json", render_schema(media["schema"], components), "```"])
    lines.extend(["", "### 鉴权", "服务启用 API Token 校验时，可使用 Collection Bearer Token 或 `x-lmd-token` 请求头。"])
    return "\n".join(lines)


def path_parts(path: str) -> tuple[list[str], list[dict[str, str]]]:
    parts, variables = [], []
    for part in path.strip("/").split("/"):
        if part.startswith("{") and part.endswith("}"):
            name = part[1:-1]
            parts.append(f":{name}")
            variables.append({"key": name, "value": "", "description": f"Path parameter: {name}"})
        else:
            parts.append(part)
    return parts, variables


def make_request(path: str, method: str, operation: dict[str, Any], components: dict[str, Any]) -> dict[str, Any]:
    parts, path_variables = path_parts(path)
    path_parameter_names = {p["name"] for p in operation.get("parameters", []) if p.get("in") == "path"}
    path_variables = [v for v in path_variables if v["key"] in path_parameter_names]
    query, headers = [], []
    for parameter in operation.get("parameters", []):
        schema = resolve_schema(parameter.get("schema", {}), components)
        entry = {"key": parameter["name"], "value": str(schema.get("example", schema.get("default", ""))),
                 "description": parameter.get("description", "")}
        if not parameter.get("required"):
            entry["disabled"] = True
        if parameter.get("in") == "query":
            query.append(entry)
        elif parameter.get("in") == "header":
            headers.append(entry)
    url: dict[str, Any] = {"raw": "{{baseUrl}}/" + "/".join(parts), "host": ["{{baseUrl}}"], "path": parts}
    if path_variables:
        url["variable"] = path_variables
    if query:
        url["query"] = query
    request: dict[str, Any] = {
        "method": method.upper(), "header": headers, "description": describe_operation(operation, components), "url": url,
    }
    content = operation.get("requestBody", {}).get("content", {})
    if "application/json" in content:
        request["header"].append({"key": "Content-Type", "value": "application/json"})
        request["body"] = {"mode": "raw", "raw": json.dumps(
            sample_value(content["application/json"].get("schema", {}), components), ensure_ascii=False, indent=2
        ), "options": {"raw": {"language": "json"}}}
    elif "multipart/form-data" in content:
        schema = content["multipart/form-data"].get("schema", {})
        fields = []
        for key, field_schema in schema.get("properties", {}).items():
            resolved = resolve_schema(field_schema, components)
            binary = resolved.get("format") == "binary" or bool(resolved.get("contentMediaType"))
            field = {"key": key, "type": "file" if binary else "text", "description": resolved.get("description", "")}
            field["src" if binary else "value"] = "" if binary else str(sample_value(field_schema, components))
            fields.append(field)
        request["body"] = {"mode": "formdata", "formdata": fields}
    elif content:
        media_type, media = next(iter(content.items()))
        request["header"].append({"key": "Content-Type", "value": media_type})
        request["body"] = {"mode": "raw", "raw": json.dumps(sample_value(media.get("schema", {}), components), ensure_ascii=False, indent=2)}
    return request


def create_collection(openapi: dict[str, Any]) -> dict[str, Any]:
    components = openapi.get("components", {}).get("schemas", {})
    folders: dict[str, list[dict[str, Any]]] = {}
    for path, path_item in openapi.get("paths", {}).items():
        for method, operation in sorted(path_item.items(), key=lambda item: METHOD_ORDER.get(item[0], 99)):
            if method not in METHOD_ORDER or not isinstance(operation, dict) or "responses" not in operation:
                continue
            tag = (operation.get("tags") or ["other"])[0]
            folder = TAG_NAMES.get(tag, tag)
            summary = operation.get("summary") or operation.get("operationId") or f"{method.upper()} {path}"
            folders.setdefault(folder, []).append({
                "name": f"{method.upper()} {path} | {summary}",
                "request": make_request(path, method, operation, components), "response": [],
            })
    description = (
        "从 FastAPI 实际注册路由及 OpenAPI schema 生成，包含 `/api/v1` API、工作流兼容前缀 `/api`、"
        "以及 `/health`、`/metrics`。每个接口说明列出参数、请求体 schema、响应状态和响应 schema。\n\n"
        "导入后设置 `baseUrl`（默认 `http://localhost:5679`）；安全校验启用时设置 `apiToken`。"
        "重新生成：`python python-backend/tools/export_postman_collection.py`。"
    )
    return {
        "info": {"_postman_id": "4b018aa0-a81c-42cb-8e7b-a88ebf18f78a",
                 "name": "LocalMiniDrama Python Backend API", "description": description,
                 "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
        "auth": {"type": "bearer", "bearer": [{"key": "token", "value": "{{apiToken}}", "type": "string"}]},
        "variable": [{"key": "baseUrl", "value": "http://localhost:5679", "type": "string"},
                     {"key": "apiToken", "value": "", "type": "string"}],
        "item": [{"name": name, "item": items} for name, items in sorted(folders.items())],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "postman" / "collections" / "python-backend.postman_collection.json")
    parser.add_argument(
        "--environment-output",
        type=Path,
        default=REPO_ROOT / "postman" / "environments" / "python-backend-local.postman_environment.json",
    )
    args = parser.parse_args()
    collection = create_collection(create_app().openapi())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(collection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    environment = {
        "id": "3fe711b4-f75f-4c04-8f60-316b459f3f55",
        "name": "LocalMiniDrama Python Backend - Local",
        "values": [
            {"key": "baseUrl", "value": "http://localhost:5679", "enabled": True},
            {"key": "apiToken", "value": "", "enabled": True},
        ],
        "_postman_variable_scope": "environment",
        "_postman_exported_using": "Postman",
        "_postman_exported_at": "",
    }
    args.environment_output.parent.mkdir(parents=True, exist_ok=True)
    args.environment_output.write_text(json.dumps(environment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    count = sum(len(folder["item"]) for folder in collection["item"])
    print(f"Wrote {count} API operations in {len(collection['item'])} functional folders: {args.output}")
    print(f"Wrote local Postman environment: {args.environment_output}")


if __name__ == "__main__":
    main()