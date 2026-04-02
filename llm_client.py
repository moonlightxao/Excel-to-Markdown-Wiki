"""LLM client for communicating with Ollama API."""

from __future__ import annotations

import json
import logging
import time

import requests

from prompt_template import build_llm_payload

logger = logging.getLogger(__name__)


class LLMUnavailableError(Exception):
    """Raised when the Ollama service is not running or the requested model is not available."""


class LLMGenerationError(Exception):
    """Raised when LLM generation failed after all retries."""


class LLMClient:
    """Client for interacting with a locally running Ollama LLM service."""

    def __init__(self, config: dict) -> None:
        llm_config = config["llm"]
        self.base_url: str = llm_config["base_url"]
        self.model: str = llm_config["model"]
        self.timeout: int = llm_config["timeout_seconds"]
        self.max_retries: int = llm_config["max_retries"]
        self.retry_delay: float = llm_config["retry_delay_seconds"]
        self.temperature: float = llm_config["temperature"]
        self.stream: bool = llm_config["stream"]
        self.config_dict: dict = config

    def check_availability(self) -> bool:
        """Check whether the Ollama service is running and the configured model is available.

        Returns:
            True if the model is available.

        Raises:
            LLMUnavailableError: If the service is unreachable or the model is not found.
        """
        # Check service reachability
        try:
            response = requests.get(
                f"{self.base_url}/api/tags",
                timeout=10,
            )
            response.raise_for_status()
        except requests.exceptions.ConnectionError:
            raise LLMUnavailableError(
                "Ollama service is not reachable. "
                "Please make sure Ollama is installed and running.\n"
                "  Install: https://ollama.com/download\n"
                "  Start:   ollama serve"
            )
        except requests.exceptions.Timeout:
            raise LLMUnavailableError(
                "Ollama service did not respond in time. "
                "Please check that the Ollama service is running at "
                f"{self.base_url}"
            )
        except requests.exceptions.HTTPError as exc:
            raise LLMUnavailableError(
                f"Ollama service returned an error: {exc}"
            )

        # Check if requested model is available
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise LLMUnavailableError(
                f"Failed to parse Ollama model list: {exc}"
            )

        available_models = [m.get("name", "") for m in data.get("models", [])]

        # Prefix match: e.g. "qwen2.5:7b" matches "qwen2.5:7b-q4_0"
        model_found = any(
            name.startswith(self.model) for name in available_models
        )

        if not model_found:
            raise LLMUnavailableError(
                f"Model '{self.model}' is not available locally. "
                f"Available models: {available_models or '(none)'}\n"
                f"  Pull the model with: ollama pull {self.model}"
            )

        logger.info("LLM model '%s' is available", self.model)
        return True

    def generate(self, prompt: str) -> str:
        """Generate text from the LLM using the given prompt.

        Args:
            prompt: The full prompt string to send.

        Returns:
            The generated text from the LLM.

        Raises:
            LLMGenerationError: If generation fails after all retries.
        """
        payload = build_llm_payload(prompt, self.config_dict)

        last_exception: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = self._send_request(payload)
                result = response.json()
                generated_text = result.get("response", "")
                if generated_text:
                    logger.debug(
                        "LLM generation succeeded on attempt %d/%d",
                        attempt + 1,
                        self.max_retries,
                    )
                    return generated_text
                logger.warning(
                    "LLM returned empty response on attempt %d/%d",
                    attempt + 1,
                    self.max_retries,
                )
            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.HTTPError,
            ) as exc:
                last_exception = exc
                logger.warning(
                    "LLM request failed on attempt %d/%d: %s",
                    attempt + 1,
                    self.max_retries,
                    exc,
                )

            if attempt < self.max_retries - 1:
                backoff = self.retry_delay * (2 ** attempt)
                logger.info("Retrying in %.1f seconds...", backoff)
                time.sleep(backoff)

        raise LLMGenerationError(
            f"LLM generation failed after {self.max_retries} attempts. "
            f"Last error: {last_exception}"
        )

    def _send_request(self, payload: dict) -> requests.Response:
        """Send a generation request to the Ollama API.

        Args:
            payload: The JSON payload to send.

        Returns:
            The requests.Response object. For streaming requests, the response
            body will contain the concatenated output from all chunks.

        Raises:
            requests.HTTPError: If the API returns a non-200 status code.
        """
        response = requests.post(
            f"{self.base_url}/api/generate",
            json=payload,
            timeout=self.timeout,
        )

        if response.status_code != 200:
            response.raise_for_status()

        if not self.stream:
            return response

        # Stream mode: collect all chunks and concatenate response fields
        collected_parts: list[str] = []
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                chunk = json.loads(line)
                part = chunk.get("response", "")
                if part:
                    collected_parts.append(part)
            except (json.JSONDecodeError, ValueError):
                logger.debug("Skipping non-JSON chunk: %s", line[:100])
                continue

        # Build a synthetic final response with concatenated text
        full_text = "".join(collected_parts)
        final_data = {"response": full_text}
        response._content = json.dumps(final_data).encode("utf-8")
        return response

    def pull_model(self) -> bool:
        """Pull the configured model from the Ollama registry.

        Returns:
            True if the pull succeeded, False otherwise.
        """
        try:
            response = requests.post(
                f"{self.base_url}/api/pull",
                json={"name": self.model, "stream": False},
                timeout=self.timeout,
            )
            response.raise_for_status()
            logger.info("Successfully pulled model '%s'", self.model)
            return True
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.HTTPError,
        ) as exc:
            logger.error("Failed to pull model '%s': %s", self.model, exc)
            return False
