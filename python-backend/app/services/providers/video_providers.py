"""视频生成 Provider 具体协议实现。
对接火山引擎（Volcengine/Doubao/Seedance）、快手可灵（Kling）、通义万相（DashScope）、Minimax（H3）、Agnes、生数科技（Vidu）、即梦（Jimeng）、Google Veo/Gemini、OpenAI Sora 与 xAI。
"""
from __future__ import annotations

from typing import Any
from app.services.providers.base import (
    BaseVideoProvider,
    VideoGenerationOptions,
    VideoTaskResult,
    VideoPollResult,
)


class VolcengineVideoProvider(BaseVideoProvider):
    """火山引擎 / 豆包视频生成 Provider。"""
    protocol_name = "volcengine"

    def create_video_task(
        self,
        config: dict[str, Any],
        log,
        opts: VideoGenerationOptions,
        post_json=None,
        db=None,
    ) -> VideoTaskResult:
        from app.services import videoClient
        opts_dict = opts.model_dump()
        is_omni = opts_dict.get("model") and "omni" in str(opts_dict.get("model")).lower()
        if is_omni:
            res = videoClient.call_volcengine_omni_video_api(config, log, opts_dict, post_json)
        else:
            res = videoClient.call_video_api(db, log, {**opts_dict, "config": config}, post_json)
        return VideoTaskResult(
            task_id=res.get("task_id"),
            provider_task_id=res.get("provider_task_id"),
            status="processing" if res.get("task_id") else ("failed" if res.get("error") else "succeeded"),
            video_url=res.get("video_url"),
            error=res.get("error"),
            raw_data=res.get("raw_data") or res,
        )

    def poll_video_task(
        self,
        config: dict[str, Any],
        log,
        task_id: str,
        fetch_bytes=None,
    ) -> VideoPollResult:
        from app.services import videoClient
        res = videoClient.poll_video_task(config, log, task_id, fetch_bytes)
        return VideoPollResult(
            task_id=task_id,
            status=res.get("status") or ("succeeded" if res.get("video_url") else "processing"),
            video_url=res.get("video_url"),
            local_path=res.get("local_path"),
            error_msg=res.get("error") or res.get("error_msg"),
            raw_data=res.get("raw_data") or res,
        )


class KlingVideoProvider(BaseVideoProvider):
    """可灵 AI 视频生成 Provider。"""
    protocol_name = "kling"

    def create_video_task(
        self,
        config: dict[str, Any],
        log,
        opts: VideoGenerationOptions,
        post_json=None,
        db=None,
    ) -> VideoTaskResult:
        from app.services import videoClient
        opts_dict = opts.model_dump()
        if "omni" in str(opts_dict.get("model") or "").lower():
            res = videoClient.call_kling_omni_video_api(config, log, opts_dict, post_json)
        else:
            res = videoClient.call_kling_video_api(config, log, opts_dict, post_json)
        return VideoTaskResult(
            task_id=res.get("task_id"),
            provider_task_id=res.get("provider_task_id"),
            status="processing" if res.get("task_id") else ("failed" if res.get("error") else "succeeded"),
            video_url=res.get("video_url"),
            error=res.get("error"),
            raw_data=res.get("raw_data") or res,
        )

    def poll_video_task(
        self,
        config: dict[str, Any],
        log,
        task_id: str,
        fetch_bytes=None,
    ) -> VideoPollResult:
        from app.services import videoClient
        res = videoClient.poll_video_task(config, log, task_id, fetch_bytes)
        return VideoPollResult(
            task_id=task_id,
            status=res.get("status") or ("succeeded" if res.get("video_url") else "processing"),
            video_url=res.get("video_url"),
            local_path=res.get("local_path"),
            error_msg=res.get("error") or res.get("error_msg"),
            raw_data=res.get("raw_data") or res,
        )


class DashScopeVideoProvider(BaseVideoProvider):
    """通义万相视频 Provider。"""
    protocol_name = "dashscope"

    def create_video_task(
        self,
        config: dict[str, Any],
        log,
        opts: VideoGenerationOptions,
        post_json=None,
        db=None,
    ) -> VideoTaskResult:
        from app.services import videoClient
        opts_dict = opts.model_dump()
        res = videoClient.call_dash_scope_video_api(config, log, opts_dict, post_json)
        return VideoTaskResult(
            task_id=res.get("task_id"),
            provider_task_id=res.get("provider_task_id"),
            status="processing" if res.get("task_id") else ("failed" if res.get("error") else "succeeded"),
            video_url=res.get("video_url"),
            error=res.get("error"),
            raw_data=res.get("raw_data") or res,
        )

    def poll_video_task(
        self,
        config: dict[str, Any],
        log,
        task_id: str,
        fetch_bytes=None,
    ) -> VideoPollResult:
        from app.services import videoClient
        res = videoClient.poll_video_task(config, log, task_id, fetch_bytes)
        return VideoPollResult(
            task_id=task_id,
            status=res.get("status") or ("succeeded" if res.get("video_url") else "processing"),
            video_url=res.get("video_url"),
            local_path=res.get("local_path"),
            error_msg=res.get("error") or res.get("error_msg"),
            raw_data=res.get("raw_data") or res,
        )


class MinimaxH3VideoProvider(BaseVideoProvider):
    """Minimax H3 视频 Provider。"""
    protocol_name = "minimax_h3"

    def create_video_task(
        self,
        config: dict[str, Any],
        log,
        opts: VideoGenerationOptions,
        post_json=None,
        db=None,
    ) -> VideoTaskResult:
        from app.services import videoClient
        opts_dict = opts.model_dump()
        res = videoClient.call_minimax_h3_video_api(config, log, opts_dict, post_json)
        return VideoTaskResult(
            task_id=res.get("task_id"),
            provider_task_id=res.get("provider_task_id"),
            status="processing" if res.get("task_id") else ("failed" if res.get("error") else "succeeded"),
            video_url=res.get("video_url"),
            error=res.get("error"),
            raw_data=res.get("raw_data") or res,
        )

    def poll_video_task(
        self,
        config: dict[str, Any],
        log,
        task_id: str,
        fetch_bytes=None,
    ) -> VideoPollResult:
        from app.services import videoClient
        res = videoClient.poll_video_task(config, log, task_id, fetch_bytes)
        return VideoPollResult(
            task_id=task_id,
            status=res.get("status") or ("succeeded" if res.get("video_url") else "processing"),
            video_url=res.get("video_url"),
            local_path=res.get("local_path"),
            error_msg=res.get("error") or res.get("error_msg"),
            raw_data=res.get("raw_data") or res,
        )


class AgnesVideoProvider(BaseVideoProvider):
    """Agnes 视频 Provider。"""
    protocol_name = "agnes"

    def create_video_task(
        self,
        config: dict[str, Any],
        log,
        opts: VideoGenerationOptions,
        post_json=None,
        db=None,
    ) -> VideoTaskResult:
        from app.services import videoClient
        opts_dict = opts.model_dump()
        res = videoClient.call_agnes_video_api(config, log, opts_dict, post_json, db=db)
        return VideoTaskResult(
            task_id=res.get("task_id"),
            provider_task_id=res.get("provider_task_id"),
            status="processing" if res.get("task_id") else ("failed" if res.get("error") else "succeeded"),
            video_url=res.get("video_url"),
            error=res.get("error"),
            raw_data=res.get("raw_data") or res,
        )

    def poll_video_task(
        self,
        config: dict[str, Any],
        log,
        task_id: str,
        fetch_bytes=None,
    ) -> VideoPollResult:
        from app.services import videoClient
        res = videoClient.poll_video_task(config, log, task_id, fetch_bytes)
        return VideoPollResult(
            task_id=task_id,
            status=res.get("status") or ("succeeded" if res.get("video_url") else "processing"),
            video_url=res.get("video_url"),
            local_path=res.get("local_path"),
            error_msg=res.get("error") or res.get("error_msg"),
            raw_data=res.get("raw_data") or res,
        )


class ViduVideoProvider(BaseVideoProvider):
    """生数科技 Vidu 视频 Provider。"""
    protocol_name = "vidu"

    def create_video_task(
        self,
        config: dict[str, Any],
        log,
        opts: VideoGenerationOptions,
        post_json=None,
        db=None,
    ) -> VideoTaskResult:
        from app.services import videoClient
        opts_dict = opts.model_dump()
        res = videoClient.call_vidu_video_api(config, log, opts_dict, post_json)
        return VideoTaskResult(
            task_id=res.get("task_id"),
            provider_task_id=res.get("provider_task_id"),
            status="processing" if res.get("task_id") else ("failed" if res.get("error") else "succeeded"),
            video_url=res.get("video_url"),
            error=res.get("error"),
            raw_data=res.get("raw_data") or res,
        )

    def poll_video_task(
        self,
        config: dict[str, Any],
        log,
        task_id: str,
        fetch_bytes=None,
    ) -> VideoPollResult:
        from app.services import videoClient
        res = videoClient.poll_video_task(config, log, task_id, fetch_bytes)
        return VideoPollResult(
            task_id=task_id,
            status=res.get("status") or ("succeeded" if res.get("video_url") else "processing"),
            video_url=res.get("video_url"),
            local_path=res.get("local_path"),
            error_msg=res.get("error") or res.get("error_msg"),
            raw_data=res.get("raw_data") or res,
        )


class JimengVideoProvider(BaseVideoProvider):
    """即梦 AI 视频 Provider。"""
    protocol_name = "jimeng"

    def create_video_task(
        self,
        config: dict[str, Any],
        log,
        opts: VideoGenerationOptions,
        post_json=None,
        db=None,
    ) -> VideoTaskResult:
        from app.services import videoClient
        opts_dict = opts.model_dump()
        res = videoClient.call_jimeng_ai_api_video(config, log, opts_dict, post_json)
        return VideoTaskResult(
            task_id=res.get("task_id"),
            provider_task_id=res.get("provider_task_id"),
            status="processing" if res.get("task_id") else ("failed" if res.get("error") else "succeeded"),
            video_url=res.get("video_url"),
            error=res.get("error"),
            raw_data=res.get("raw_data") or res,
        )

    def poll_video_task(
        self,
        config: dict[str, Any],
        log,
        task_id: str,
        fetch_bytes=None,
    ) -> VideoPollResult:
        from app.services import videoClient
        res = videoClient.poll_video_task(config, log, task_id, fetch_bytes)
        return VideoPollResult(
            task_id=task_id,
            status=res.get("status") or ("succeeded" if res.get("video_url") else "processing"),
            video_url=res.get("video_url"),
            local_path=res.get("local_path"),
            error_msg=res.get("error") or res.get("error_msg"),
            raw_data=res.get("raw_data") or res,
        )


class Veo3VideoProvider(BaseVideoProvider):
    """Google Veo3 视频 Provider。"""
    protocol_name = "veo3"

    def create_video_task(
        self,
        config: dict[str, Any],
        log,
        opts: VideoGenerationOptions,
        post_json=None,
        db=None,
    ) -> VideoTaskResult:
        from app.services import videoClient
        opts_dict = opts.model_dump()
        res = videoClient.call_veo3_video_api(config, log, opts_dict, post_json, cfg=config)
        return VideoTaskResult(
            task_id=res.get("task_id"),
            provider_task_id=res.get("provider_task_id"),
            status="processing" if res.get("task_id") else ("failed" if res.get("error") else "succeeded"),
            video_url=res.get("video_url"),
            error=res.get("error"),
            raw_data=res.get("raw_data") or res,
        )

    def poll_video_task(
        self,
        config: dict[str, Any],
        log,
        task_id: str,
        fetch_bytes=None,
    ) -> VideoPollResult:
        from app.services import videoClient
        res = videoClient.poll_video_task(config, log, task_id, fetch_bytes)
        return VideoPollResult(
            task_id=task_id,
            status=res.get("status") or ("succeeded" if res.get("video_url") else "processing"),
            video_url=res.get("video_url"),
            local_path=res.get("local_path"),
            error_msg=res.get("error") or res.get("error_msg"),
            raw_data=res.get("raw_data") or res,
        )


class SoraVideoProvider(BaseVideoProvider):
    """OpenAI Sora 视频 Provider。"""
    protocol_name = "sora"

    def create_video_task(
        self,
        config: dict[str, Any],
        log,
        opts: VideoGenerationOptions,
        post_json=None,
        db=None,
    ) -> VideoTaskResult:
        from app.services import videoClient
        opts_dict = opts.model_dump()
        res = videoClient.call_sora_video_api(config, log, opts_dict, post_json)
        return VideoTaskResult(
            task_id=res.get("task_id"),
            provider_task_id=res.get("provider_task_id"),
            status="processing" if res.get("task_id") else ("failed" if res.get("error") else "succeeded"),
            video_url=res.get("video_url"),
            error=res.get("error"),
            raw_data=res.get("raw_data") or res,
        )

    def poll_video_task(
        self,
        config: dict[str, Any],
        log,
        task_id: str,
        fetch_bytes=None,
    ) -> VideoPollResult:
        from app.services import videoClient
        res = videoClient.poll_video_task(config, log, task_id, fetch_bytes)
        return VideoPollResult(
            task_id=task_id,
            status=res.get("status") or ("succeeded" if res.get("video_url") else "processing"),
            video_url=res.get("video_url"),
            local_path=res.get("local_path"),
            error_msg=res.get("error") or res.get("error_msg"),
            raw_data=res.get("raw_data") or res,
        )
