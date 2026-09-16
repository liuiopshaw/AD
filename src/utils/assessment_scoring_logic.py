#!/usr/bin/env python3
# Specify python3 as the interpreter to ensure the correct Python version is used when executed directly on Unix-like systems

"""
Assessment Scoring Logic Module.
Provides unified scoring logic to ensure assessment agent evaluations are based on the model's own rational judgment.

Assessment scoring logic module.
Provides unified scoring logic, ensuring that each assessment Agent evaluates based on the model's own rational judgment.
"""

import logging
# Import Python's built-in logging module to record warnings and errors during score adjustment
from typing import Dict, Any, List, Tuple
# Import type hints from the typing module to improve code readability and IDE support

# Configure logging
logging.basicConfig(level=logging.WARNING)
# Configure the basic logging settings with level WARNING; INFO and DEBUG level logs will not be output
logger = logging.getLogger(__name__)
# Get the logger for the current module; using __name__ allows log output to identify the source module

class AssessmentScoringLogic:
    """Assessment Scoring Logic Class - Provides unified scoring logic.
    Encapsulates all scoring-related methods."""

    # Dimension weights
    # Weight configuration for each assessment dimension: catalytic performance has the highest weight (50%), structural rationality is second (20%),
    # while economic feasibility, environmental friendliness, and technical feasibility each account for 10%, reflecting the core concerns of water treatment material assessment
    DIMENSION_WEIGHTS = {
        "catalytic": 0.50,      # Catalytic performance weight - the most critical assessment dimension
        "economic": 0.10,       # Economic feasibility weight - cost factors are relatively secondary
        "environmental": 0.10,  # Environmental friendliness weight - as important as technical requirements
        "technical": 0.10,      # Technical feasibility weight - assesses implementation difficulty
        "structural": 0.20      # Structural rationality weight - the scientific foundation of the material itself
    }

    # Scoring criteria
    # Scoring criteria mapping table: maps numeric scores from 1-10 to corresponding textual descriptions
    # 10 is the highest (exceptional), 1 is the lowest (completely invalid); designs scoring below 5 are unusable
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
        Calculate the weighted total score: multiply each of the five dimension scores by its weight and sum the results.

        Args:
            scores (List[int]): Five dimension scores [catalytic performance, economic feasibility, environmental friendliness, technical feasibility, structural rationality]

        Returns:
            float: Weighted total score, rounded to two decimal places
        """
        # Validate the length of the input score list to ensure it contains exactly five dimensions
        if len(scores) != 5:
            raise ValueError("Scores must include five dimensions")

        # Weighted summation: multiply each dimension's score by its corresponding weight and accumulate
        weighted_total = (
            scores[0] * AssessmentScoringLogic.DIMENSION_WEIGHTS["catalytic"] +
            scores[1] * AssessmentScoringLogic.DIMENSION_WEIGHTS["economic"] +
            scores[2] * AssessmentScoringLogic.DIMENSION_WEIGHTS["environmental"] +
            scores[3] * AssessmentScoringLogic.DIMENSION_WEIGHTS["technical"] +
            scores[4] * AssessmentScoringLogic.DIMENSION_WEIGHTS["structural"]
        )

        # Return the result rounded to two decimal places to avoid floating-point precision issues
        return round(weighted_total, 2)

    @staticmethod
    def validate_chemically_impossible(formula: str) -> bool:
        """
        Validate if chemical formula is chemically impossible.
        Validate whether the chemical formula is chemically impossible (e.g., over-oxidized valence states).

        Args:
            formula (str): Material chemical formula to be validated

        Returns:
            bool: True if chemically impossible, False otherwise
        """
        # Define a list of known chemically impossible formula patterns
        # For example, Ir in IrO7 has a +14 valence state (unattainable for transition metals), and Ru in Ru(SO4)9 has a +18 valence state (beyond the reasonable range)
        impossible_patterns = [
            "IrO7",      # Ir +14 valence state - chemically impossible
            "Ru(SO4)9",  # Ru +18 valence state - chemically impossible
            "FeO4",      # Fe +8 valence state - chemically impossible
            "Hg(Cl)5"    # Hg +5 valence state - chemically impossible
        ]

        # If the formula contains any of the above impossible patterns, return True (chemically impossible)
        return any(pattern in formula for pattern in impossible_patterns)

    @staticmethod
    def validate_ambiguous_formula(formula: str) -> bool:
        """
        Validate if chemical formula is ambiguous.
        Validate whether the chemical formula is ambiguous (e.g., component ratios not specified).

        Args:
            formula (str): Material chemical formula to be validated

        Returns:
            bool: True if formula is ambiguous, False otherwise
        """
        # Define a list of ambiguous formula patterns
        # For example, "Pd/Au" only indicates a mixture of palladium and gold without specifying the exact ratio, making accurate assessment impossible
        ambiguous_patterns = [
            "Pd/Au",     # Ratio not specified - cannot be accurately modeled and assessed
        ]

        # If the formula contains an ambiguous pattern, return True
        return any(pattern in formula for pattern in ambiguous_patterns)

    @staticmethod
    def adjust_scores_based_on_tool_validation(scores: List[int], tool_validation_result: Dict[str, Any]) -> List[int]:
        """
        Adjust scores based on tool validation results.
        Adjust scores based on tool validation results: if not all tool validations pass, deduct 1 point from all dimension scores.

        Args:
            scores (List[int]): Original dimension score list
            tool_validation_result (Dict[str, Any]): Tool validation result dictionary

        Returns:
            List[int]: Adjusted score list
        """
        # Copy the original score list to avoid modifying the original data
        adjusted_scores = scores.copy()

        # Check whether all tool validations passed (all_valid being False indicates a validation failure)
        if not tool_validation_result.get("all_valid", True):
            # If tool validation fails, decrease all dimension scores by 1 point, but not below 1
            # Rationale: tool validation failure indicates questionable data reliability and warrants a penalty, but a minimum score is preserved
            adjusted_scores = [max(1, score - 1) for score in scores]
            # Log the score adjustment for tracking and debugging
            logger.warning(f"Tool validation failed, scores adjusted: {scores} -> {adjusted_scores}")

        # Return the adjusted score list
        return adjusted_scores

    @staticmethod
    def ensure_consistent_scoring(expert_a_scores: List[int], expert_b_scores: List[int], expert_c_scores: List[int]) -> Tuple[List[int], List[int], List[int]]:
        """
        Ensure consistency among three assessment agent scores.
        Ensure consistency among the scores of the three assessment Agents. A "move toward the average" strategy is adopted:
        if an expert's score deviates from the average by more than 2 points, adjust the score by 1 point toward the average.

        Args:
            expert_a_scores (List[int]): Expert A's scores
            expert_b_scores (List[int]): Expert B's scores
            expert_c_scores (List[int]): Expert C's scores

        Returns:
            Tuple[List[int], List[int], List[int]]: Adjusted scores of the three experts
        """
        # Calculate the average score for each dimension (arithmetic mean of the three experts' scores for that dimension, rounded)
        avg_scores = []
        for i in range(5):
            avg = (expert_a_scores[i] + expert_b_scores[i] + expert_c_scores[i]) / 3
            avg_scores.append(round(avg))

        # Define the score adjustment function: if the deviation exceeds 2 points, move 1 point toward the average
        # This is a gentle adjustment strategy that avoids over-correction while reducing the impact of extreme deviations
        def adjust_score(score, avg):
            if abs(score - avg) > 2:
                # Deviation exceeds the threshold; adjust 1 point toward the average
                if score > avg:
                    return score - 1  # Decrease by 1 point when the score is too high
                else:
                    return score + 1  # Increase by 1 point when the score is too low
            return score  # Deviation is within a reasonable range; keep unchanged

        # Apply the adjustment function to each dimension score of each expert
        adjusted_a_scores = [adjust_score(expert_a_scores[i], avg_scores[i]) for i in range(5)]
        adjusted_b_scores = [adjust_score(expert_b_scores[i], avg_scores[i]) for i in range(5)]
        adjusted_c_scores = [adjust_score(expert_c_scores[i], avg_scores[i]) for i in range(5)]

        # Return the tuple of adjusted scores from all experts
        return adjusted_a_scores, adjusted_b_scores, adjusted_c_scores
