"""OpenAI-compatible LLM client for the Excel to Markdown Wiki converter.

Supports any service that follows the OpenAI Chat Completions API format,
including OpenAI, DeepSeek, DashScope (Qwen), and local servers that
expose an /v1/chat/completions endpoint.
"""

from __future__ import annotations

import logging
import time

import requests

from llm_client import LLMGenerationError, LLMUnavailableError
from prompt_template import build_openai_payload

logger = logging.getLogger(__name__)


class OpenAILLMClient:
    """Client for interacting with an OpenAI-compatible LLM service."""

    def __init__(self, config: dict) -> None:
        llm_config = config["llm"]
        self.model: str = llm_config["model"]
        self.timeout: int = llm_config["timeout_seconds"]
        self.max_retries: int = llm_config["max_retries"]
        self.retry_delay: float = llm_config["retry_delay_seconds"]
        self.config_dict: dict = config

        self.base_url: str = llm_config.get("base_url", "https://api.openai.com/v1")
        self.api_key: str = llm_config.get("api_key", "")
        self._url: str = f"{self.base_url.rstrip('/')}/chat/completions"
        self._headers: dict = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_availability(self) -> bool:
        """Check whether the OpenAI-compatible service is reachable and the
        configured model is available.

        Returns:
            True if the model is available.

        Raises:
            LLMUnavailableError: If the service is unreachable or the model
                is not found.
        """
        models_url = f"{self.base_url.rstrip('/')}/models"
        try:
            resp = requests.get(
                models_url, headers=self._headers, timeout=self.timeout
            )
            resp.raise_for_status()
        except requests.exceptions.ConnectionError as exc:
            raise LLMUnavailableError(
                "OpenAI-compatible service is not reachable at "
                f"{self.base_url}. "
                "Please check the base_url and network settings."
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise LLMUnavailableError(
                "OpenAI-compatible service did not respond in time at "
                f"{self.base_url}"
            ) from exc
        except requests.exceptions.HTTPError as exc:
            if resp.status_code == 401:
                raise LLMUnavailableError(
                    "Authentication failed. Please check your api_key in config."
                ) from exc
            # For other errors (e.g. 404 on /v1/models), still consider
            # the service reachable — just log a warning.
            logger.warning(
                "Service returned HTTP %d on model list (non-fatal): %s",
                resp.status_code,
                str(exc),
            )

        logger.info("OpenAI-compatible service reachable, model: %s", self.model)
        return True

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        """Generate text from the LLM using the given prompt.

        Args:
            prompt: The full prompt string to send.
            system_prompt: Optional system prompt override. When None, uses
                the default SYSTEM_PROMPT from prompt_template.

        Returns:
            The generated text from the LLM.

        Raises:
            LLMGenerationError: If generation fails after all retries.
        """
        payload = build_openai_payload(prompt, self.config_dict, system_prompt=system_prompt)

        last_exception: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = requests.post(
                    self._url,
                    json=payload,
                    headers=self._headers,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                generated_text = (
                    response.json()["choices"][0]["message"]["content"] or ""
                )

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
