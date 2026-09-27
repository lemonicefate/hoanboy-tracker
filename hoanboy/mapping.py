"""Explicit candidate mappings. Nothing is verified by a field's spelling."""

import math
import hashlib
import json
from datetime import datetime
from typing import Any, NamedTuple

MAPPING_VERSION = "candidate-1"


class FieldDefinition(NamedTuple):
    source: str
    label: str
    unit: str
    section: int


def mapping_version(verified: dict[str, str]) -> str:
    if not isinstance(verified, dict) or any(
        not isinstance(key, str) or not isinstance(value, str) or not value.strip()
        for key, value in verified.items()
    ):
        raise ValueError("已驗證欄位必須附有非空的證據索引")
    if not verified:
        return MAPPING_VERSION
    if not set(verified).issubset({field.source for field in FIELDS.values()}):
        raise ValueError("核對設定含有未知來源欄名")
    digest = hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()[
        :16
    ]
    return MAPPING_VERSION + "+" + digest


# source, label, candidate unit, report section
FIELDS: dict[str, FieldDefinition] = {
    "weight": FieldDefinition("bhWeightKg", "體重", "kg", 2),
    "bmi": FieldDefinition("bhBMI", "BMI", "kg/m²", 3),
    "fat_rate": FieldDefinition("bhBodyFatRate", "體脂肪率", "%", 3),
    "water": FieldDefinition("bhWaterKg", "身體水分", "kg", 1),
    "protein": FieldDefinition("bhProteinKg", "蛋白質", "kg", 1),
    "mineral": FieldDefinition("bhMineralKg", "無機鹽", "kg", 1),
    "fat": FieldDefinition("bhBodyFatKg", "體脂肪", "kg", 1),
    "fat_free": FieldDefinition("bhBodyFatFreeMassKg", "去脂體重", "kg", 1),
    "skeletal": FieldDefinition("bhSkeletalMuscleKg", "骨骼肌", "kg", 2),
    "whr": FieldDefinition("bhWHR", "腰臀比", "比值", 3),
    "subcutaneous": FieldDefinition("bhbhBodyFatSubCutRate", "皮下脂肪率", "%", 3),
    "visceral": FieldDefinition("bhVFAL", "內臟脂肪", "等級", 4),
    "ideal": FieldDefinition("bhIdealWeightKg", "目標體重", "kg", 9),
    "weight_control": FieldDefinition("bhWeightKgCon", "體重控制", "kg", 9),
    "fat_control": FieldDefinition("bhBodyFatKgCon", "脂肪控制", "kg", 9),
    "muscle_control": FieldDefinition("bhMuscleKgCon", "肌肉控制", "kg", 9),
    "bmr": FieldDefinition("bhBMR", "基礎代謝", "未核對", 9),
    "body_age": FieldDefinition("bhBodyAge", "身體年齡", "歲", 9),
    "score": FieldDefinition("bhBodyScore", "健康評分", "分", 10),
}
for suffix, label in (
    ("Trunk", "軀幹"),
    ("LeftArm", "左臂"),
    ("RightArm", "右臂"),
    ("LeftLeg", "左腿"),
    ("RightLeg", "右腿"),
):
    FIELDS[f"muscle_{suffix}"] = FieldDefinition(
        f"bhMuscleKg{suffix}", f"{label}肌肉", "kg", 5
    )
    FIELDS[f"fat_{suffix}"] = FieldDefinition(
        f"bhBodyFatKg{suffix}", f"{label}脂肪", "kg", 5
    )

# Explicitly override the source's inconsistent subcutaneous spelling.
LEVEL_FIELDS = {key: field.source + "Level" for key, field in FIELDS.items()}
LEVEL_FIELDS["subcutaneous"] = "bhBodyFatSubCutRateLevel"


def normalize(raw: dict[str, Any], verified: dict[str, str]) -> dict[str, Any]:
    result = {}
    for key, field in FIELDS.items():
        source = field.source
        value, state = numeric(raw.get(source))
        result[key] = dict(
            value=value,
            source=source,
            label=field.label,
            unit=field.unit,
            section=field.section,
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
