"""`python -m friday` → launch the app."""
import sys

# Re-exec into the project venv if started with an interpreter missing the deps
# (e.g. system python). Must run before importing the app / provider stack.
from friday._bootstrap import ensure_venv

ensure_venv()

from friday.app import main  # noqa: E402

main(server_only="--server" in sys.argv)
