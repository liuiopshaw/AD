#!/usr/bin/env python3
# 指定解释器为 python3，确保在 Unix-like 系统上直接执行时使用正确的 Python 版本

"""
Assessment Scoring Logic Module.
Provides unified scoring logic to ensure assessment agent evaluations are based on the model's own rational judgment.

评估评分逻辑模块。
提供统一的评分逻辑，确保各评估 Agent 基于模型自身的理性判断进行评估。
"""

import logging
# 导入 Python 内置日志模块，用于记录评分调整过程中的警告和错误信息
from typing import Dict, Any, List, Tuple
# 从 typing 模块导入类型提示，提高代码可读性和 IDE 支持

# Configure logging
logging.basicConfig(level=logging.WARNING)
# 配置日志的基本格式，设置日志级别为 WARNING，INFO 和 DEBUG 级别的日志将不会输出
logger = logging.getLogger(__name__)
# 获取当前模块的日志记录器，使用 __name__ 使日志输出时能识别来源模块

class AssessmentScoringLogic:
    """Assessment Scoring Logic Class - Provides unified scoring logic.
    评估评分逻辑类 - 提供统一的评分逻辑，封装所有与评分相关的方法。"""

    # Dimension weights
    # 各评估维度的权重配置：催化性能权重最高（50%），结构合理性次之（20%），
    # 经济性、环保性和技术可行性各占 10%，反映了水处理材料评估的核心关注点
    DIMENSION_WEIGHTS = {
        "catalytic": 0.50,      # 催化性能权重 - 最核心的评估维度
        "economic": 0.10,       # 经济可行性权重 - 成本因素相对次要
        "environmental": 0.10,  # 环境友好性权重 - 与技术要求同等重要
        "technical": 0.10,      # 技术可行性权重 - 评估实现难度
        "structural": 0.20      # 结构合理性权重 - 材料本身的科学基础
    }

    # Scoring criteria
    # 评分标准映射表：将 1-10 的数值分数映射为对应的文字描述
    # 10 分为最高（杰出），1 分为最低（完全无效），低于 5 分的设计方案不可用
    SCORE_CRITERIA = {
        10: "Exceptional - Outstanding performance, fully validated",
        9: "Excellent - Strong scientific value, well-designed structure",
        8: "Very Good - Stable performance, minor improvements needed",
        7: "Good - Above average, some limitations",
        6: "Average - Acceptable performance, noticeable limitations",
        5: "Below Average - Moderate performance, major issues",
        4: "Poor - Low performance, major defects",
        3: "Very Poor - Minimal performance, critical defects",
        2: "Invalid - Serious issues, fundamental errors",
        1: "Completely Invalid - Chemically impossible or non-existent"
    }

    @staticmethod
    def calculate_weighted_score(scores: List[int]) -> float:
        """
        Calculate weighted total score.
        计算加权总分：将五个维度的分数乘以各自权重后求和。

        Args:
            scores (List[int]): Five dimension scores [catalytic performance, economic feasibility, environmental friendliness, technical feasibility, structural rationality]
            scores (List[int]): 五个维度分数 [催化性能, 经济可行性, 环境友好性, 技术可行性, 结构合理性]

        Returns:
            float: Weighted total score
            float: 加权总分，保留两位小数
        """
        # 校验输入的分数列表长度，确保恰好包含五个维度
        if len(scores) != 5:
            raise ValueError("Scores must include five dimensions")

        # 加权求和：每个维度的分数乘以对应的权重后累加
        weighted_total = (
            scores[0] * AssessmentScoringLogic.DIMENSION_WEIGHTS["catalytic"] +
            scores[1] * AssessmentScoringLogic.DIMENSION_WEIGHTS["economic"] +
            scores[2] * AssessmentScoringLogic.DIMENSION_WEIGHTS["environmental"] +
            scores[3] * AssessmentScoringLogic.DIMENSION_WEIGHTS["technical"] +
            scores[4] * AssessmentScoringLogic.DIMENSION_WEIGHTS["structural"]
        )

        # 返回四舍五入保留两位小数的结果，避免浮点数精度问题
        return round(weighted_total, 2)

    @staticmethod
    def validate_chemically_impossible(formula: str) -> bool:
        """
        Validate if chemical formula is chemically impossible.
        验证化学式是否在化学上不可能存在（例如过度氧化的化合价状态）。

        Args:
            formula (str): Material chemical formula
            formula (str): 待验证的材料化学式

        Returns:
            bool: True if chemically impossible, False otherwise
            bool: 如果是化学上不可能的结构则返回 True，否则返回 False
        """
        # 定义已知的化学上不可能存在的化学式模式列表
        # 例如 IrO7 中 Ir 为 +14 价（过渡金属不可达到），Ru(SO4)9 中 Ru 为 +18 价（超出合理范围）
        impossible_patterns = [
            "IrO7",      # Ir +14 价 - 化学上不可能
            "Ru(SO4)9",  # Ru +18 价 - 化学上不可能
            "FeO4",      # Fe +8 价 - 化学上不可能
            "Hg(Cl)5"    # Hg +5 价 - 化学上不可能
        ]

        # 如果化学式中包含上述任一不可能模式，则返回 True（化学上不可能）
        return any(pattern in formula for pattern in impossible_patterns)

    @staticmethod
    def validate_ambiguous_formula(formula: str) -> bool:
        """
        Validate if chemical formula is ambiguous.
        验证化学式是否模糊不清（例如未标明组分配比）。

        Args:
            formula (str): Material chemical formula
            formula (str): 待验证的材料化学式

        Returns:
            bool: True if formula is ambiguous, False otherwise
            bool: 如果化学式模糊不清则返回 True，否则返回 False
        """
        # 定义模糊化学式模式列表
        # 例如 "Pd/Au" 仅表明是钯和金的混合，但未说明具体比例，无法准确评估
        ambiguous_patterns = [
            "Pd/Au",     # 未指定比例 - 无法准确建模和评估
        ]

        # 如果化学式中包含模糊模式，则返回 True
        return any(pattern in formula for pattern in ambiguous_patterns)

    @staticmethod
    def adjust_scores_based_on_tool_validation(scores: List[int], tool_validation_result: Dict[str, Any]) -> List[int]:
        """
        Adjust scores based on tool validation results.
        根据工具验证结果调整评分：如果工具验证未全部通过，则所有维度分数扣减 1 分。

        Args:
            scores (List[int]): Original scores
            scores (List[int]): 原始的各维度评分列表
            tool_validation_result (Dict[str, Any]): Tool validation results
            tool_validation_result (Dict[str, Any]): 工具验证结果字典

        Returns:
            List[int]: Adjusted scores
            List[int]: 调整后的评分列表
        """
        # 复制原始分数列表，避免修改原始数据
        adjusted_scores = scores.copy()

        # 检查工具验证是否全部通过（all_valid 为 False 表示存在验证失败）
        if not tool_validation_result.get("all_valid", True):
            # 如果工具验证失败，所有维度分数降低 1 分，但最低不低于 1 分
            # 这样做的原因：工具验证失败说明数据可靠性存疑，需要惩罚，但保留最低分
            adjusted_scores = [max(1, score - 1) for score in scores]
            # 记录评分调整的日志，便于追踪和调试
            logger.warning(f"Tool validation failed, scores adjusted: {scores} -> {adjusted_scores}")

        # 返回调整后的分数列表
        return adjusted_scores

    @staticmethod
    def ensure_consistent_scoring(expert_a_scores: List[int], expert_b_scores: List[int], expert_c_scores: List[int]) -> Tuple[List[int], List[int], List[int]]:
        """
        Ensure consistency among three assessment agent scores.
        确保三位评估 Agent 评分的一致性。采用"向平均值靠拢"的策略：
        如果某专家的评分与平均值偏差超过 2 分，则将其分数向平均值方向调整 1 分。

        Args:
            expert_a_scores (List[int]): Expert A's scores
            expert_a_scores (List[int]): 专家 A 的评分
            expert_b_scores (List[int]): Expert B's scores
            expert_b_scores (List[int]): 专家 B 的评分
            expert_c_scores (List[int]): Expert C's scores
            expert_c_scores (List[int]): 专家 C 的评分

        Returns:
            Tuple[List[int], List[int], List[int]]: Adjusted scores
            Tuple[List[int], List[int], List[int]]: 调整后的三位专家的评分
        """
        # 计算每个维度的平均分（三位专家的该维度分数取算术平均后四舍五入）
        avg_scores = []
        for i in range(5):
            avg = (expert_a_scores[i] + expert_b_scores[i] + expert_c_scores[i]) / 3
            avg_scores.append(round(avg))

        # 定义评分调整函数：如果偏差超过 2 分则向平均值方向移动 1 分
        # 这是一种温和的调整策略，避免过度修正但能减少极端偏差的影响
        def adjust_score(score, avg):
            if abs(score - avg) > 2:
                # 偏差超过阈值，向平均值方向调整 1 分
                if score > avg:
                    return score - 1  # 分数偏高时降低 1 分
                else:
                    return score + 1  # 分数偏低时提高 1 分
            return score  # 偏差在合理范围内，保持不变

        # 对每位专家的每个维度分数应用调整函数
        adjusted_a_scores = [adjust_score(expert_a_scores[i], avg_scores[i]) for i in range(5)]
        adjusted_b_scores = [adjust_score(expert_b_scores[i], avg_scores[i]) for i in range(5)]
        adjusted_c_scores = [adjust_score(expert_c_scores[i], avg_scores[i]) for i in range(5)]

        # 返回多位专家调整后的评分元组
        return adjusted_a_scores, adjusted_b_scores, adjusted_c_scores
