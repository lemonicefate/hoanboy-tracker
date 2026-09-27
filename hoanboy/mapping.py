"""Explicit candidate mappings. Nothing is verified by a field's spelling."""

import math
from datetime import datetime
from typing import Any

MAPPING_VERSION = "candidate-1"
# source, label, candidate unit, report section
FIELDS = {
    "weight": ("bhWeightKg", "體重", "kg", 2),
    "bmi": ("bhBMI", "BMI", "kg/m²", 3),
    "fat_rate": ("bhBodyFatRate", "體脂肪率", "%", 3),
    "water": ("bhWaterKg", "身體水分", "kg", 1),
    "protein": ("bhProteinKg", "蛋白質", "kg", 1),
    "mineral": ("bhMineralKg", "無機鹽", "kg", 1),
    "fat": ("bhBodyFatKg", "體脂肪", "kg", 1),
    "fat_free": ("bhBodyFatFreeMassKg", "去脂體重", "kg", 1),
    "skeletal": ("bhSkeletalMuscleKg", "骨骼肌", "kg", 2),
    "whr": ("bhWHR", "腰臀比", "比值", 3),
    "subcutaneous": ("bhbhBodyFatSubCutRate", "皮下脂肪率", "%", 3),
    "visceral": ("bhVFAL", "內臟脂肪", "等級", 4),
    "ideal": ("bhIdealWeightKg", "目標體重", "kg", 9),
    "weight_control": ("bhWeightKgCon", "體重控制", "kg", 9),
    "fat_control": ("bhBodyFatKgCon", "脂肪控制", "kg", 9),
    "muscle_control": ("bhMuscleKgCon", "肌肉控制", "kg", 9),
    "bmr": ("bhBMR", "基礎代謝", "未核對", 9),
    "body_age": ("bhBodyAge", "身體年齡", "歲", 9),
    "score": ("bhBodyScore", "健康評分", "分", 10),
}
for suffix, label in (
    ("Trunk", "軀幹"),
    ("LeftArm", "左臂"),
    ("RightArm", "右臂"),
    ("LeftLeg", "左腿"),
    ("RightLeg", "右腿"),
):
    FIELDS[f"muscle_{suffix}"] = (f"bhMuscleKg{suffix}", f"{label}肌肉", "kg", 5)
    FIELDS[f"fat_{suffix}"] = (f"bhBodyFatKg{suffix}", f"{label}脂肪", "kg", 5)

# Explicitly override the source's inconsistent subcutaneous spelling.
LEVEL_FIELDS = {key: source + "Level" for key, (source, _, _, _) in FIELDS.items()}
LEVEL_FIELDS["subcutaneous"] = "bhBodyFatSubCutRateLevel"


def normalize(raw: dict[str, Any], verified: dict[str, str]) -> dict[str, Any]:
    result = {}
    for key, (source, label, unit, section) in FIELDS.items():
        value, state = numeric(raw.get(source))
        result[key] = dict(
            value=value,
            source=source,
            label=label,
            unit=unit,
            section=section,
            status=state or ("verified" if verified.get(source) else "unverified"),
            evidence=verified.get(source),
            minimum=raw.get(source + "ListMin"),
            maximum=raw.get(source + "ListMax"),
            level=raw.get(LEVEL_FIELDS[key]),
            level_source=LEVEL_FIELDS[key],
        )
    return result


def numeric(value: Any) -> tuple[float | None, str | None]:
    if value is None or value == "":
        return None, "missing"
    try:
        number = float(value)
        if isinstance(value, bool) or not math.isfinite(number):
            return None, "invalid"
        return number, None
    except (ValueError, TypeError):
        return None, "invalid"


def parse_time(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("/", "-").replace("Z", "+00:00"))
        # Device times are a local wall-clock series; preserve original offset in raw.
        return parsed.replace(tzinfo=None).isoformat()
    except ValueError:
        return None
