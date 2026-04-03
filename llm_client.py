"""LLM client for communicating with Ollama API (uses stdlib urllib only)."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
import urllib.parse

from prompt_template import build_llm_payload

logger = logging.getLogger(__name__)


class LLMUnavailableError(Exception):
    """Raised when the Ollama service is not running or the requested model is not available."""


class LLMGenerationError(Exception):
    """Raised when LLM generation failed after all retries."""


class _HTTPError(Exception):
    """Wrapper for HTTP-level errors (non-200 status)."""
    def __init__(self, status_code: int, reason: str, body: str) -> None:
        self.status_code = status_code
        self.reason = reason
        self.body = body
        super().__init__(f"HTTP {status_code}: {reason}")


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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _request(self, method: str, path: str, body: dict | None = None, timeout: int | None = None) -> dict:
        """Send an HTTP request and return the parsed JSON response.

        Raises:
            ConnectionError: If the server is unreachable.
            TimeoutError: If the request times out.
            _HTTPError: If the server returns a non-200 status.
        """
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")

        effective_timeout = timeout if timeout is not None else self.timeout
        try:
            with urllib.request.urlopen(req, timeout=effective_timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            body_text = ""
            try:
                body_text = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise _HTTPError(exc.code, exc.reason, body_text)
        except urllib.error.URLError as exc:
            # Wrap as ConnectionError for consistent handling
            raise ConnectionError(f"Cannot connect to {self.base_url}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise TimeoutError(f"Request to {url} timed out after {effective_timeout}s") from exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_availability(self) -> bool:
        """Check whether the Ollama service is running and the configured model is available.

        Returns:
            True if the model is available.

        Raises:
            LLMUnavailableError: If the service is unreachable or the model is not found.
        """
        try:
            data = self._request("GET", "/api/tags", timeout=10)
        except ConnectionError as exc:
            raise LLMUnavailableError(
                "Ollama service is not reachable. "
                "Please make sure Ollama is installed and running.\n"
                "  Install: https://ollama.com/download\n"
                "  Start:   ollama serve"
            ) from exc
        except TimeoutError as exc:
            raise LLMUnavailableError(
                "Ollama service did not respond in time. "
                "Please check that the Ollama service is running at "
                f"{self.base_url}"
            ) from exc
        except _HTTPError as exc:
            raise LLMUnavailableError(
                f"Ollama service returned an error: {exc}"
            ) from exc

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
                result = self._request("POST", "/api/generate", body=payload)

                if self.stream:
                    # Non-streaming request already returns the full response
                    generated_text = result.get("response", "")
                else:
                    generated_text = result.get("response", "")

                if generated_text:
                    logger.debug(
                        "LLM generation succeeded on attempt %d/%d",
                        attempt + 1,
                        self.max_retries,
                    )
                    return generated_text

                # Empty response — check if model used thinking mode
                thinking = result.get("thinking", "")
                if thinking:
                    logger.warning(
                        "LLM returned empty response but has thinking content "
                        "(%d chars) on attempt %d/%d. "
                        "Consider setting enable_thinking: false in config.",
                        len(thinking),
                        attempt + 1,
                        self.max_retries,
                    )
                    logger.debug("Thinking content: %s", thinking[:500])
                else:
                    logger.warning(
                        "LLM returned empty response on attempt %d/%d",
                        attempt + 1,
                        self.max_retries,
                    )
            except (ConnectionError, TimeoutError, _HTTPError) as exc:
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

    def pull_model(self) -> bool:
        """Pull the configured model from the Ollama registry.

        Returns:
            True if the pull succeeded, False otherwise.
        """
        try:
            self._request(
                "POST", "/api/pull",
                body={"name": self.model, "stream": False},
            )
            logger.info("Successfully pulled model '%s'", self.model)
            return True
        except (ConnectionError, TimeoutError, _HTTPError) as exc:
            logger.error("Failed to pull model '%s': %s", self.model, exc)
            return False


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------


def create_llm_client(config: dict):
    """Create an LLM client based on the ``provider`` in config.

    Args:
        config: Application config dict.  ``config["llm"]["provider"]``
            determines which backend to use.  Supported values are
            ``"ollama"`` (default) and ``"openai"``.

    Returns:
        An instance of :class:`LLMClient` (Ollama) or
        :class:`OpenAILLMClient` (OpenAI-compatible).
    """
    provider = config.get("llm", {}).get("provider", "ollama")
    if provider == "openai":
        from openai_client import OpenAILLMClient
        return OpenAILLMClient(config)
    return LLMClient(config)
