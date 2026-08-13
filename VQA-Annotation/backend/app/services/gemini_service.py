import base64
import json

import requests

from app.config.settings import settings


def generate_annotations(
    image_bytes: bytes,
    output_type: str,
    language: int,
    prompt: str | None = None,
    category: int = 0,
    count: int = 10,
) -> list[dict]:
    if not settings.gemini_api_key:
        raise RuntimeError("Gemini is not configured on the backend.")
    if output_type not in {"MULTIPLE_CHOICE", "SHORT_ANSWER"}:
        raise ValueError("Unsupported task output type.")
    if language not in {1, 2} or category not in {0, 1, 2, 3, 4} or count < 1 or count > 10:
        raise ValueError("Invalid Gemini generation configuration.")
    language_name = "English" if language == 1 else "Vietnamese"
    category_name = {
        0: "CHART_ONLY", 1: "TEXT_ONLY", 2: "TABLE_ONLY", 3: "MIXED", 4: "INSIGHT",
    }[category]
    category_guide = (
        "0=CHART_ONLY, 1=TEXT_ONLY, 2=TABLE_ONLY, 3=MIXED, 4=INSIGHT"
    )
    item_structure = (
        '{"category":0,"question":{"question_text":"...","option_A":"...","option_B":"...","option_C":"...","option_D":"..."},"answer":"A"}'
        if output_type == "MULTIPLE_CHOICE" else '{"category":0,"question":{"question_text":"..."},"answer":"..."}'
    )
    structure = f'{{"annotations":[{item_structure}]}}'
    instruction = prompt or "Create diverse, concise, factual questions and answers based only on the slide."
    body = {
        "contents": [{"parts": [
            {"text": (
                f"Analyze only the provided slide image. {instruction} Generate exactly {count} distinct annotations.\n"
                f"Language: {language_name}. Output type: {output_type}. Available categories: {category_guide}. "
                f"Choose the most relevant category independently for each annotation and use a varied mix when "
                f"the slide content supports it. Category {category} ({category_name}) is only a preference, not a requirement. "
                f"Do not use Markdown or explanations. Return JSON only in this exact structure, with exactly {count} items: {structure}"
            )},
            {"inline_data": {"mime_type": "image/png", "data": base64.b64encode(image_bytes).decode("ascii")}},
        ]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent"
    response = requests.post(
        url,
        headers={"x-goog-api-key": settings.gemini_api_key},
        json=body,
        timeout=120,
    )
    response.raise_for_status()
    candidates = response.json().get("candidates", [])
    text = candidates[0]["content"]["parts"][0]["text"] if candidates else ""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError("Gemini returned invalid JSON.") from error
    results = payload.get("annotations") if isinstance(payload, dict) else None
    if count == 1 and results is None and isinstance(payload, dict):
        results = [payload]
    if not isinstance(results, list) or len(results) != count:
        raise ValueError(f"Gemini must return exactly {count} annotations.")
    for result in results:
        _validate_annotation(result, output_type, category)
    return results


def generate_annotation(
    image_bytes: bytes,
    output_type: str,
    language: int,
    prompt: str | None = None,
    category: int = 0,
) -> dict:
    return generate_annotations(image_bytes, output_type, language, prompt, category, count=1)[0]


def _validate_annotation(result: object, output_type: str, category: int) -> None:
    if not isinstance(result, dict) or not isinstance(result.get("question"), dict) or not result.get("answer"):
        raise ValueError("Gemini returned an invalid annotation structure.")
    if not isinstance(result.get("category", category), int) or not 0 <= result.get("category", category) <= 4:
        raise ValueError("Gemini returned an invalid category.")
    question = result["question"]
    question_text = str(question.get("question_text", "")).strip()
    if not question_text:
        raise ValueError("Gemini returned an empty question.")
    if "answer" in question:
        raise ValueError("Gemini nested answer inside question.")
    result["category"] = result.get("category", category)
    if output_type == "MULTIPLE_CHOICE":
        keys = ("option_A", "option_B", "option_C", "option_D")
        if any(not str(question.get(key, question.get(key.lower(), ""))).strip() for key in keys):
            raise ValueError("Gemini returned incomplete multiple-choice options.")
        if result["answer"] not in {"A", "B", "C", "D"}:
            raise ValueError("Gemini returned an invalid multiple-choice answer.")
    else:
        if any(key.lower().startswith("option_") for key in question):
            raise ValueError("Gemini returned options for a short-answer question.")
        if not question_text.endswith((".", "?")):
            raise ValueError("Gemini returned a short-answer question without punctuation.")