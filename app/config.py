from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOTENV_PATH = PROJECT_ROOT / ".env"


def load_environment() -> bool:
    """Load the project-root .env without overriding process variables."""
    return load_dotenv(dotenv_path=DOTENV_PATH, override=False)
