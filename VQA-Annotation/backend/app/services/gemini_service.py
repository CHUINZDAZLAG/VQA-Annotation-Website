import base64
import json

import requests

from app.config.settings import settings


def generate_annotation(image_bytes: bytes, output_type: str, language: int, prompt: str | None) -> dict:
    if not settings.gemini_api_key:
        raise RuntimeError("Gemini is not configured on the backend.")
    language_name = "English" if language == 1 else "Vietnamese"
    structure = (
        '{"question":{"question_text":"...","option_a":"...","option_b":"...","option_c":"...","option_d":"..."},"answer":"..."}'
        if output_type == "MULTIPLE_CHOICE" else '{"question":{"question_text":"..."},"answer":"..."}'
    )
    instruction = prompt or "Create a concise, factual question and answer based only on the slide."
    body = {
        "contents": [{"parts": [
            {"text": f"{instruction}\nLanguage: {language_name}. Output type: {output_type}. Return JSON only in this structure: {structure}"},
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
    result = json.loads(text)
    if not isinstance(result, dict) or not isinstance(result.get("question"), dict) or not result.get("answer"):
        raise ValueError("Gemini returned an invalid annotation structure.")
    return result