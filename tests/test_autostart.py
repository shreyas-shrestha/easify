import sys
from unittest.mock import patch

from app.cli.autostart import resolve_program_argv


def test_resolve_program_argv_prefers_which() -> None:
    with patch("app.cli.autostart.shutil.which", return_value="/opt/bin/easify"):
        assert resolve_program_argv() == ["/opt/bin/easify"]


def test_resolve_program_argv_fallback_module() -> None:
    with patch("app.cli.autostart.shutil.which", return_value=None):
        out = resolve_program_argv()
        assert out == [sys.executable, "-m", "app"]
