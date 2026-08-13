import csv
import io
import json
import math
from collections.abc import Iterable
from typing import Any

from app.models.annotation import AnnotationRecord


EXPORT_COLUMNS = [
    "task_id", "annotation_id", "output_type", "question_type", "image_id",
    "generated_image_id", "slide_name", "categories", "category", "slide_type",
    "language", "drive_link", "question", "question_text", "option_A", "option_B",
    "option_C", "option_D", "answer", "main_annotator", "blind_annotator", "reviewer",
    "main_label", "blind_label", "reviewer_label", "blind_question", "blind_answer",
    "similarity_score", "reject_reason", "final_status", "main_annotator_decision",
    "main_annotator_reject_reason", "main_annotator_reject_note",
    "blind_annotator_decision", "blind_annotator_reject_reason",
    "blind_annotator_reject_note", "reviewer_decision", "reviewer_reject_reason",
    "reviewer_reject_note", "annotation_status", "created_by", "page_number",
    "created_at", "updated_at", "option_a", "option_b", "option_c", "option_d",
]


def decision(record: AnnotationRecord, role: str) -> int | None:
    explicit = {
        "main_annotator": getattr(record, "main_label", None),
        "blind_annotator": getattr(record, "blind_label", None),
        "reviewer": getattr(record, "reviewer_label", None),
    }.get(role)
    if explicit in (0, 1):
        return explicit
    value = getattr(record, role, None) or {}
    result = value.get("decision") if isinstance(value, dict) else None
    return result if result in (0, 1) else None


def agreement_stats(records: Iterable[AnnotationRecord]) -> dict[str, Any]:
    rows = list(records)
    decisions = [[decision(row, role) for role in ("main_annotator", "blind_annotator", "reviewer")] for row in rows]
    complete = [values for values in decisions if all(value in (0, 1) for value in values)]
    unanimous = sum(len(set(values)) == 1 for values in complete)
    accepted = sum(value == 1 for row in complete for value in row)
    rejected = sum(value == 0 for row in complete for value in row)
    kappa = fleiss_kappa(complete)
    return {
        "total_annotations": len(complete),
        "unanimous_agreement": unanimous,
        "disagreement": len(complete) - unanimous,
        "accept": accepted,
        "reject": rejected,
        "fleiss_kappa": kappa,
    }


def fleiss_agreement_stats(records: Iterable[AnnotationRecord]) -> dict[str, Any]:
    rows = list(records)
    roles = ("main_annotator", "blind_annotator", "reviewer")
    counts = {
        role: {"label_0": 0, "label_1": 0}
        for role in ("main", "blind", "reviewer")
    }
    observations: list[list[int]] = []
    for record in rows:
        labels = [decision(record, role) for role in roles]
        for role_name, label in zip(counts, labels):
            if label in (0, 1):
                counts[role_name][f"label_{label}"] += 1
        if all(label in (0, 1) for label in labels):
            observations.append(labels)
    return {
        "total_records": len(rows),
        "observations": len(observations),
        **fleiss_components(observations),
        "annotators": counts,
    }


def fleiss_kappa(decisions: list[list[int]]) -> float | None:
    return fleiss_components(decisions)["fleiss_kappa"]


def fleiss_components(decisions: list[list[int]]) -> dict[str, Any]:
    """Calculate standard Fleiss' Kappa from an N x 3 binary rating matrix."""
    if not decisions or any(len(row) != 3 or any(value not in (0, 1) for value in row) for row in decisions):
        return {"total_ratings": 0, "p_observed": None, "p_expected": None, "fleiss_kappa": None}
    observation_count = len(decisions)
    category_counts = [sum(value == category for row in decisions for value in row) for category in (0, 1)]
    total_ratings = observation_count * 3
    proportions = [count / total_ratings for count in category_counts]
    p_expected = sum(proportion * proportion for proportion in proportions)
    # P_i = (n_i0^2 + n_i1^2) / (n(n-1)) - 1/(n-1), with n=3.
    p_items = [
        (sum(value == 0 for value in row) ** 2 + sum(value == 1 for value in row) ** 2) / 6 - 0.5
        for row in decisions
    ]
    p_observed = sum(p_items) / observation_count
    if math.isclose(1 - p_expected, 0.0):
        kappa = None
    else:
        kappa = round((p_observed - p_expected) / (1 - p_expected), 10)
    return {
        "total_ratings": total_ratings,
        "p_observed": round(p_observed, 10),
        "p_expected": round(p_expected, 10),
        "fleiss_kappa": kappa,
    }


def flatten_record(record: AnnotationRecord) -> dict[str, Any]:
    question = record.question or {}
    main = record.main_annotator or {}
    blind = record.blind_annotator or {}
    reviewer = record.reviewer or {}
    main_decision = decision(record, "main_annotator")
    blind_decision = decision(record, "blind_annotator")
    reviewer_decision = decision(record, "reviewer")
    options = {
        letter: question.get(f"option_{letter.lower()}", question.get(f"option_{letter}"))
        for letter in "ABCD"
    }
    result = {
        "task_id": record.task_id,
        "annotation_id": record.id,
        "output_type": record.output_type,
        "question_type": record.output_type,
        "image_id": record.image_id,
        "generated_image_id": record.generated_image_id,
        "slide_name": record.slide_name,
        "categories": record.categories,
        "category": record.categories,
        "slide_type": record.slide_type,
        "language": record.language,
        "drive_link": getattr(record, "drive_link", None),
        "question": question,
        "question_text": question.get("question_text"),
        "option_A": options["A"],
        "option_B": options["B"],
        "option_C": options["C"],
        "option_D": options["D"],
        "answer": record.answer,
        "main_annotator": main_decision,
        "blind_annotator": blind_decision,
        "reviewer": reviewer_decision,
        "main_label": main_decision,
        "blind_label": blind_decision,
        "reviewer_label": reviewer_decision,
        "blind_question": getattr(record, "blind_question", None),
        "blind_answer": getattr(record, "blind_answer", None),
        "similarity_score": getattr(record, "similarity_score", None),
        "reject_reason": getattr(record, "reject_reason", None),
        "final_status": getattr(record, "final_status", "PENDING"),
        "main_annotator_decision": main.get("decision"),
        "main_annotator_reject_reason": main.get("reject_reason"),
        "main_annotator_reject_note": main.get("reject_note"),
        "blind_annotator_decision": blind.get("decision"),
        "blind_annotator_reject_reason": blind.get("reject_reason"),
        "blind_annotator_reject_note": blind.get("reject_note"),
        "reviewer_decision": reviewer.get("decision"),
        "reviewer_reject_reason": reviewer.get("reject_reason"),
        "reviewer_reject_note": reviewer.get("reject_note"),
        "annotation_status": record.annotation_status,
        "created_by": record.created_by,
        "page_number": record.page_number,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }
    result.update({f"option_{letter.lower()}": options[letter] for letter in "ABCD"})
    return result


def final_dataset_records(records: Iterable[AnnotationRecord]) -> list[AnnotationRecord]:
    """Return only pages unanimously accepted by Main, Blind, and Reviewer."""
    return [
        record for record in records
        if decision(record, "main_annotator") == 1
        and decision(record, "blind_annotator") == 1
        and decision(record, "reviewer") == 1
    ]


def serialize_records(records: Iterable[AnnotationRecord], output_format: str) -> tuple[bytes, str]:
    rows = [flatten_record(record) for record in records]
    normalized = output_format.upper()
    if normalized == "CSV":
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=EXPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
        return stream.getvalue().encode("utf-8-sig"), "text/csv"
    return json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8"), "application/json"


def filename(task_name: str, output_format: str) -> str:
    safe_name = "_".join(part for part in task_name.strip().split() if part) or "task"
    return f"{safe_name}_final.{output_format.lower()}"
