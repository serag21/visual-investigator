"""Gemini transport only. No credentials, URLs, or raw responses in public errors."""
import base64
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

from dotenv import dotenv_values
from .engine import SYSTEM_PROMPT, Picture
from .models import Finding


class ProviderError(Exception):
    def __init__(self, message: str, status: int = 502, private_response: str | None = None, category: str | None = None):
        super().__init__(message)
        self.status = status
        self.private_response=private_response[:100_000] if private_response else None
        self.category=category or ('infrastructure' if status in (429,502,503,504) else 'request')


def configured_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or dotenv_values(Path(__file__).resolve().parents[1] / ".env").get("GEMINI_API_KEY")


class Gemini:
    name = "Google Gemini"
    model = "gemini-3.5-flash-lite"

    def ready(self):
        return bool(configured_key())

    def investigate(self, context: str, pictures: list[Picture]) -> tuple[Finding, dict]:
        text, usage = self._generate(context, pictures, structured=True)
        try:
            return Finding.model_validate_json(text), usage
        except ValueError:
            raise ProviderError("The model returned an invalid answer format. Your investigation is unchanged; no automatic retry was made.",private_response=text,category='answer_format') from None

    def generate_text(self, context: str, pictures: list[Picture]) -> tuple[str, dict]:
        """Direct baseline comparison: same transport/images/budget, no product schema."""
        return self._generate(context, pictures, structured=False)

    def _generate(self, context: str, pictures: list[Picture], structured: bool) -> tuple[str, dict]:
        key = configured_key()
        if not key:
            raise ProviderError("Gemini is not configured on this server.", 503)
        parts = [{"text": context}]
        for picture in pictures:
            parts.extend([{"text": f"Photo evidence {picture.id}:"},
                          {"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(picture.data).decode()}}])
            if picture.target_data:
                parts.extend([{"text": f"Selected target {picture.id}:target; prioritize this area. Full photo is context."},
                              {"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(picture.target_data).decode()}}])
        prompt = SYSTEM_PROMPT if structured else "Answer the user's visual question accurately and concisely. If evidence is insufficient, explain what is missing and give a useful next step. Do not invent facts. If no question is given, identify the likely subject or ask what the user means."
        config = {"maxOutputTokens": 2400, "temperature": 0.2}
        if structured:
            config.update(responseMimeType="application/json", responseJsonSchema=Finding.model_json_schema())
        payload = {"systemInstruction": {"parts": [{"text": prompt}]}, "contents": [{"role": "user", "parts": parts}], "generationConfig": config}
        request = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
            data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": key}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=50) as response:
                body = json.loads(response.read(200_000))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise ProviderError("Gemini's quota is busy or exhausted. Your investigation is unchanged. Try later; no automatic retry was made.", 429) from None
            if 400 <= exc.code < 500:
                # Region/billing preconditions may be HTTP 400, not only 403.
                # Surface no provider body/URL and let the durable beta pause
                # prevent another request until an operator reviews configuration.
                raise ProviderError(f"Gemini rejected server access or request configuration (HTTP {exc.code}). Your investigation is unchanged; server configuration needs review before another attempt.", 503) from None
            raise ProviderError(f"Gemini could not complete this request (HTTP {exc.code}). Your investigation is unchanged.") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ProviderError("Gemini did not respond in time. Your investigation is unchanged. You can try again.", 504) from None
        except (ValueError, TypeError):
            raise ProviderError("Gemini returned an unreadable response. Your investigation is unchanged.") from None
        try:
            candidate = body["candidates"][0]
            if candidate.get("finishReason") != "STOP":
                raise ValueError("incomplete response")
            text = "".join(p.get("text", "") for p in candidate["content"]["parts"] if not p.get("thought"))
            return text, body.get("usageMetadata", {})
        except (ValueError, KeyError, TypeError, IndexError):
            raise ProviderError("The model returned an incomplete answer. Your investigation is unchanged; no automatic retry was made.",category='answer_format') from None
