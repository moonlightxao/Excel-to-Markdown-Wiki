"""OpenAI-compatible LLM client for the Excel to Markdown Wiki converter.

Supports any service that follows the OpenAI Chat Completions API format,
including OpenAI, DeepSeek, DashScope (Qwen), and local servers that
expose an /v1/chat/completions endpoint.
"""

from __future__ import annotations

import logging
import time

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

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

        self._client = OpenAI(
            api_key=llm_config.get("api_key", ""),
            base_url=llm_config.get("base_url", "https://api.openai.com/v1"),
            timeout=self.timeout,
            max_retries=0,  # we handle retries ourselves
        )

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
        try:
            self._client.models.list()
        except APIConnectionError as exc:
            raise LLMUnavailableError(
                "OpenAI-compatible service is not reachable at "
                f"{self._client.base_url}. "
                "Please check the base_url and network settings."
            ) from exc
        except APITimeoutError as exc:
            raise LLMUnavailableError(
                "OpenAI-compatible service did not respond in time at "
                f"{self._client.base_url}"
            ) from exc
        except APIStatusError as exc:
            if exc.status_code == 401:
                raise LLMUnavailableError(
                    "Authentication failed. Please check your api_key in config."
                ) from exc
            # For other errors (e.g. 404 on /v1/models), still consider
            # the service reachable — just log a warning.
            logger.warning(
                "Service returned HTTP %d on model list (non-fatal): %s",
                exc.status_code,
                exc.message,
            )

        logger.info("OpenAI-compatible service reachable, model: %s", self.model)
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
        payload = build_openai_payload(prompt, self.config_dict)
        # Extract messages from payload; the rest are keyword args
        messages = payload.pop("messages")

        last_exception: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = self._client.chat.completions.create(
                    messages=messages,
                    **payload,
                )
                generated_text = response.choices[0].message.content or ""

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

            except (APIConnectionError, APITimeoutError, APIStatusError) as exc:
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
