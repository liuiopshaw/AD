#!/usr/bin/env python3
"""
Rule-based enzyme activity classifier for nanomaterials.
Focuses on CAT-like, SOD-like, and NADH oxidase-like activities.
Uses literature-extracted structure-activity relationships — fully interpretable.
"""

import json
import os
import logging

logger = logging.getLogger(__name__)


class EnzymeClassifier:
    """Classify enzyme-like activity based on nanomaterial structural properties.

    Focus: CAT-like (catalase), SOD-like (superoxide dismutase), NADH oxidase-like.
    NADH oxidase-like activity receives bonus scoring due to its therapeutic
    relevance in Alzheimer's disease (NAD+ replenishment).
    """

    RULES_PATH = os.path.join(
        os.path.dirname(__file__), "..", "..", "data", "enzyme_classification_rules.json"
    )

    def __init__(self):
        self.rules = self._load_rules()

    def _load_rules(self) -> dict:
        try:
            with open(self.RULES_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning(f"Rules file not found at {self.RULES_PATH}, using empty rules")
            return {"rules": [], "element_toxicity_flags": {}}

    def run(self, material_properties: dict) -> dict:
        """Classify enzyme-like activity for a given nanomaterial.

        Args:
            material_properties: dict with keys:
                core_elements (list[str]), band_gap_ev (float | None),
                size_nm (float | None), shape (str | None),
                has_mixed_valence (bool), has_oxygen_vacancy (bool),
                material_class (str | None), crystal_structure (str | None)

        Returns:
            dict with predicted enzyme activities, confidence levels,
            toxicity flags, and AD therapeutic relevance.
        """
        predictions = []
        core_elements = material_properties.get("core_elements", [])
        band_gap = material_properties.get("band_gap_ev")
        size_nm = material_properties.get("size_nm")
        shape = material_properties.get("shape")

        for rule in self.rules.get("rules", []):
            score = 0
            max_score = 0
            matched_boosters = []
            conditions = rule.get("conditions", {})

            # Check core elements
            max_score += 1
            if any(el in conditions.get("core_elements", []) for el in core_elements):
                score += 1

            # Check band gap
            if band_gap is not None:
                max_score += 1
                bg_range = conditions.get("band_gap_ev", {})
                if bg_range.get("min", 0) <= band_gap <= bg_range.get("max", 100):
                    score += 1

            # Check size
            if size_nm is not None:
                max_score += 1
                if size_nm <= conditions.get("size_nm", {}).get("max", 999):
                    size_bonus = 0.5 if size_nm <= 10 else 0
                    if size_bonus:
                        score += size_bonus

            # Check confidence boosters
            for booster in conditions.get("confidence_boosters", []):
                if self._match_booster(booster, material_properties):
                    matched_boosters.append(booster)
                    score += 0.5

            # NADH-like bonus for Cu nanoclusters with cyclodextrin coating
            if rule.get("enzyme_type") == "NADH_oxidase_like":
                coating = material_properties.get("coating", "").lower()
                shape_val = material_properties.get("shape", "").lower()
                if "cyclodextrin" in coating or "cd" in coating:
                    score += 1.0
                if "nanocluster" in shape_val or "cluster" in shape_val:
                    score += 0.5

            # Shape bonus
            if shape:
                shape_rules = self.rules.get("shape_activity_relationships", {})
                if shape in shape_rules:
                    matched_boosters.append(shape_rules[shape])

            confidence = score / max(max_score, 1)
            confidence = min(confidence, 1.0)

            if confidence >= 0.3:
                # Add AD therapeutic relevance
                ad_relevance = self.rules.get("ad_therapeutic_relevance", {}).get(
                    rule["enzyme_type"], None
                )
                predictions.append({
                    "enzyme_type": rule["enzyme_type"],
                    "confidence": round(confidence, 2),
                    "activity_level": self._confidence_to_level(confidence),
                    "matched_rules": matched_boosters[:3],
                    "reference_pmids": rule.get("reference_pmids", []),
                    "ad_therapeutic_relevance": ad_relevance
                })

        predictions.sort(key=lambda x: x["confidence"], reverse=True)

        # Element toxicity flags
        toxicity_flags = []
        for el in core_elements:
            flag = self.rules.get("element_toxicity_flags", {}).get(el)
            if flag:
                toxicity_flags.append({"element": el, "flag": flag})

        return {
            "predicted_activities": predictions,
            "toxicity_flags": toxicity_flags,
            "primary_activity": predictions[0] if predictions else None,
            "source": "EnzymeClassifier (rule-based)"
        }

    def _match_booster(self, booster: str, props: dict) -> bool:
        booster_lower = booster.lower()
        if "mixed valence" in booster_lower:
            return props.get("has_mixed_valence", False)
        if "oxygen vacancy" in booster_lower:
            return props.get("has_oxygen_vacancy", False)
        if "fenton" in booster_lower:
            return any(el in ["Fe", "Cu", "Co", "Mn"] for el in props.get("core_elements", []))
        if "small particle" in booster_lower:
            return (props.get("size_nm") or 999) < 10
        if "metal-organic" in booster_lower:
            return props.get("material_class") in ["mof", "coordination_polymer"]
        if "ce3+/ce4+" in booster_lower:
            return "Ce" in props.get("core_elements", [])
        if "fluorite" in booster_lower or "perovskite" in booster_lower:
            return props.get("crystal_structure") in ["fluorite", "perovskite"]
        if "cu nanocluster" in booster_lower:
            return "Cu" in props.get("core_elements", []) and props.get("shape") == "nanocluster"
        if "cyclodextrin" in booster_lower:
            return "cyclodextrin" in str(props.get("coating", "")).lower()
        return any(word in booster_lower for word in str(props).lower().split())

    def _confidence_to_level(self, confidence: float) -> str:
        if confidence >= 0.7:
            return "Strong"
        elif confidence >= 0.5:
            return "Moderate"
        elif confidence >= 0.3:
            return "Weak"
        return "Unlikely"
