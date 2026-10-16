"""API 请求数据传输对象 (DTO) 公共基类与通用配置。

为所有 HTTP API 请求体提供统一的 Pydantic 配置：
1. 自动去除字符串前后无意义的空白字符 (str_strip_whitespace=True)
2. 允许字段别名与属性名同时访问 (populate_by_name=True)
3. 允许任意类型校验配置，保证向前兼容性
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class BaseApiRequest(BaseModel):
    """所有 API 请求体模型的统一抽象基类。"""

    model_config = ConfigDict(
        # 自动剥离入参字符串首尾的空格，防止脏数据注入
        str_strip_whitespace=True,
        # 允许通过字段名称或字段别名 (alias) 初始化模型
        populate_by_name=True,
        # 遇到未明确声明的多余字段时默认宽容忽略，避免客户端传递未来扩展字段时报错
        extra="ignore",
    )
