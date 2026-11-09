"""Settings for the application, read from environment variables."""

from pathlib import Path
from pydantic import SecretStr
from pydantic_settings import BaseSettings


class AppSettings(BaseSettings):
    """All settings. Created once at start-up, so missing configuration stops the app early.

    Attributes:
        reports_dir: Directory for the stored reports, one folder each (`REPORTS_DIR`),
            relative to the working directory.
        conversations_dir: Directory for the chat Conversations, one JSON file each
            (`CONVERSATIONS_DIR`), relative to the working directory.
        anthropic_api_key: The Anthropic API key (`ANTHROPIC_API_KEY`). Required.
        mistral_api_key: The Mistral API key (`MISTRAL_API_KEY`), which reads the PDFs.
            Required.
        anthropic_model: The Claude model ID (`ANTHROPIC_MODEL`).
        max_upload_mb: The largest PDF accepted at upload, in MB (`MAX_UPLOAD_MB`).
        embedding_model: The fastembed model for search (`EMBEDDING_MODEL`). Changing it
            means uploading every report again.
        models_dir: The model files (`MODELS_DIR`): `fastembed/` for the embedding
            model. They live in the repo's `models/` folder and
            are copied into the image, so nothing is downloaded at runtime. Relative to the
            working directory (`backend/`).
    """

    reports_dir: Path = Path("data/reports")
    conversations_dir: Path = Path("data/conversations")
    anthropic_api_key: SecretStr
    mistral_api_key: SecretStr
    anthropic_model: str = "claude-opus-5-5"
    max_upload_mb: int = 100
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    models_dir: Path = Path("models")
