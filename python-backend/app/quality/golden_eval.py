"""Golden Dataset 回归评估套件与质量基准测试流水线。

【系统定位与架构职责】
- 本模块建立基准测试用例集（Golden Dataset），涵盖短剧核心环节：
  1. 小说章节语义切片与关键事实召回 (Novel Chunking & RAG Recall)
  2. 角色设定与外观提示词一致性 (Character Consistency & Prompt Fidelity)
  3. 分镜视听语言与镜头构图提示词生成 (Storyboard Visual/Audio Design)
- 提供自动化打分流水线 (Evaluation Pipeline)：
  - 角色设定保留率 (Entity Retention Score)
  - 分镜提示词丰富度与格式合规性 (Prompt Compliance Score)
  - 事实忠实度评分 (Faithfulness Score)
- 支持 CI/CD 与上线前一键自动化回归质量评估。
"""
from __future__ import annotations

import re
import json
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class GoldenTestCase(BaseModel):
    """Golden Dataset 单条基准测试用例模型。"""
    id: str
    category: str = Field(description="测试类型：novel_rag | character_design | storyboard_prompt | audio_design")
    input_text: str = Field(description="测试输入源文本或剧情梗概")
    expected_entities: List[str] = Field(default_factory=list, description="期望保留的核心实体/角色名")
    required_keywords: List[str] = Field(default_factory=list, description="输出必须包含的关键视听或语义词汇")
    forbidden_keywords: List[List[str]] = Field(default_factory=list, description="禁止出现的错觉/幻觉词汇")
    reference_output: Optional[str] = Field(default=None, description="标准参考答案或黄金输出")


class EvaluationScore(BaseModel):
    """单项测试评估打分结果。"""
    test_id: str
    category: str
    entity_retention_score: float = Field(ge=0.0, le=1.0, description="实体保留率 (0-1)")
    keyword_coverage_score: float = Field(ge=0.0, le=1.0, description="关键词覆盖度 (0-1)")
    faithfulness_score: float = Field(ge=0.0, le=1.0, description="剧情忠实度 (0-1)")
    overall_score: float = Field(ge=0.0, le=1.0, description="综合加权得分 (0-1)")
    passed: bool
    details: Dict[str, Any] = Field(default_factory=dict)


# ── 内置 Golden Dataset 基准数据集 ──────────────────────────────────────────────────

DEFAULT_GOLDEN_DATASET: List[GoldenTestCase] = [
    GoldenTestCase(
        id="TC-NOVEL-001",
        category="novel_rag",
        input_text="林轩站在天穹之巅，手握九霄诛仙剑。远处的魔尊厉绝天冷笑道：'三千年了，你依然无法参透天道无情！' 林轩目光如炬，剑身泛起青色龙纹雷光，一步踏出虚空震颤。",
        expected_entities=["林轩", "厉绝天", "九霄诛仙剑"],
        required_keywords=["天穹", "魔尊", "剑身", "雷光", "虚空"],
    ),
    GoldenTestCase(
        id="TC-CHAR-002",
        category="character_design",
        input_text="女主苏清雪，22岁，海归天才建筑设计师。容貌清冷出尘，一头墨黑微卷长发，身着剪裁利落的米白色双排扣风衣，眼神冷静敏锐但隐藏着深情。",
        expected_entities=["苏清雪"],
        required_keywords=["建筑设计师", "清冷", "墨黑", "风衣", "冷静"],
    ),
    GoldenTestCase(
        id="TC-STORYBOARD-003",
        category="storyboard_prompt",
        input_text="第3集第1镜：雨夜狭巷，男主被黑衣人围堵。特写镜头打在男主沾满雨水的侧脸上，眼神决绝，背景是昏暗的霓虹灯倒影与积水反光。",
        expected_entities=["男主", "黑衣人"],
        required_keywords=["雨夜", "特写", "侧脸", "霓虹", "反光"],
    ),
    GoldenTestCase(
        id="TC-AUDIO-004",
        category="audio_design",
        input_text="高潮对决场景：配乐从低沉压抑的弦乐铺垫，在双方刀剑相交瞬间爆发激昂的交响乐与重低音鼓点，环境音伴随暴风雨与雷鸣呼啸。",
        expected_entities=[],
        required_keywords=["弦乐", "交响", "鼓点", "暴风雨", "雷鸣"],
    ),
]


class GoldenDatasetEvaluator:
    """自动化评估引擎。"""
    def __init__(self, dataset: Optional[List[GoldenTestCase]] = None):
        self.dataset = dataset or DEFAULT_GOLDEN_DATASET

    def evaluate_output(self, test_case: GoldenTestCase, generated_output: str) -> EvaluationScore:
        """针对单个用例评估生成的文本或提示词质量。"""
        if not generated_output or not generated_output.strip():
            return EvaluationScore(
                test_id=test_case.id,
                category=test_case.category,
                entity_retention_score=0.0,
                keyword_coverage_score=0.0,
                faithfulness_score=0.0,
                overall_score=0.0,
                passed=False,
                details={"error": "Empty generated output"},
            )

        # 1. 实体保留度评分
        found_entities = [e for e in test_case.expected_entities if e in generated_output]
        entity_score = (len(found_entities) / len(test_case.expected_entities)) if test_case.expected_entities else 1.0

        # 2. 关键词覆盖度评分
        found_keywords = [kw for kw in test_case.required_keywords if kw in generated_output]
        kw_score = (len(found_keywords) / len(test_case.required_keywords)) if test_case.required_keywords else 1.0

        # 3. 忠实度与长度合理性打分
        length_penalty = 1.0 if len(generated_output) >= 20 else (len(generated_output) / 20.0)
        faithfulness = (entity_score * 0.5 + kw_score * 0.5) * length_penalty

        # 综合加权得分
        overall = entity_score * 0.35 + kw_score * 0.35 + faithfulness * 0.30
        passed = overall >= 0.70

        return EvaluationScore(
            test_id=test_case.id,
            category=test_case.category,
            entity_retention_score=round(entity_score, 3),
            keyword_coverage_score=round(kw_score, 3),
            faithfulness_score=round(faithfulness, 3),
            overall_score=round(overall, 3),
            passed=passed,
            details={
                "missing_entities": [e for e in test_case.expected_entities if e not in found_entities],
                "missing_keywords": [k for k in test_case.required_keywords if k not in found_keywords],
                "output_length": len(generated_output),
            },
        )

    def run_benchmark_suite(self, generation_funcs: Dict[str, Any]) -> Dict[str, Any]:
        """运行完整 Golden Dataset 回归评估流水线。"""
        results: List[EvaluationScore] = []
        t0 = time.time()

        for tc in self.dataset:
            # 获取对应的生成逻辑或 mock 生成
            gen_func = generation_funcs.get(tc.category) or generation_funcs.get("default")
            if gen_func:
                output = gen_func(tc.input_text)
            else:
                # 默认模拟回显以验证流水线打分逻辑
                output = tc.input_text

            score = self.evaluate_output(tc, output)
            results.append(score)

        duration = time.time() - t0
        passed_count = sum(1 for r in results if r.passed)
        avg_score = sum(r.overall_score for r in results) / len(results) if results else 0.0

        return {
            "summary": {
                "total_cases": len(results),
                "passed_cases": passed_count,
                "failed_cases": len(results) - passed_count,
                "pass_rate": round(passed_count / len(results) * 100.0, 2) if results else 0.0,
                "average_score": round(avg_score, 3),
                "duration_seconds": round(duration, 3),
            },
            "results": [r.model_dump() for r in results],
        }


def run_golden_eval_pipeline() -> Dict[str, Any]:
    """快捷调用入口：执行基准质量评估打分。"""
    evaluator = GoldenDatasetEvaluator()
    return evaluator.run_benchmark_suite({
        "default": lambda text: f"基于大纲生成的视听剧本提示词: {text}",
    })
