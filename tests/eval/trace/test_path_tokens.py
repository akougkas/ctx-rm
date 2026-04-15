from __future__ import annotations

from ctx_rm.eval.trace._path_tokens import (
    is_path_like,
    strip_path_segments,
)


class TestIsPathLike:
    def test_absolute_path(self) -> None:
        assert is_path_like("/home/akougkas/projects/awoc/src/cli.ts")

    def test_relative_path(self) -> None:
        assert is_path_like("./src/cli.ts")
        assert is_path_like("src/extensions/awoc-core.ts")

    def test_home_path(self) -> None:
        assert is_path_like("~/.claude/projects/foo")

    def test_plain_identifier_is_not_path(self) -> None:
        assert not is_path_like("authenticate_user_with_token")

    def test_single_slash_is_not_path(self) -> None:
        assert not is_path_like("a/b")  # too short, no extension


class TestStripPathSegments:
    def test_strips_absolute_path(self) -> None:
        text = "error in /home/akougkas/projects/ctx-rm/src/ctx_rm/core/bus.py at line 42"
        stripped = strip_path_segments(text)
        assert "/home/akougkas" not in stripped
        assert "bus.py" not in stripped  # whole path token is replaced
        assert "error in" in stripped
        assert "at line 42" in stripped

    def test_preserves_code_identifiers(self) -> None:
        text = "authenticate_user_with_token returns a JWT bearer"
        stripped = strip_path_segments(text)
        assert stripped == text

    def test_strips_multiple_paths(self) -> None:
        text = "read /a/b/file.py wrote /c/d/other.ts"
        stripped = strip_path_segments(text)
        assert "file.py" not in stripped
        assert "other.ts" not in stripped

    def test_strips_path_after_equals_sign(self) -> None:
        text = "tool_use:Read file_path=/home/x/src/cli.ts limit=50"
        stripped = strip_path_segments(text)
        assert "/home/x/src/cli.ts" not in stripped
        assert "cli.ts" not in stripped
        assert "file_path=" in stripped  # boundary char preserved
        assert "limit=50" in stripped    # unrelated key-value preserved

    def test_strips_path_after_colon(self) -> None:
        text = "error in src/foo.ts:42 during load"
        stripped = strip_path_segments(text)
        assert "src/foo.ts" not in stripped
        assert "error in" in stripped
        assert "during load" in stripped

    def test_strips_path_after_comma(self) -> None:
        text = "files: foo.py,/home/x/bar.py,baz.py"
        stripped = strip_path_segments(text)
        assert "/home/x/bar.py" not in stripped

    def test_strips_path_in_curly_brace(self) -> None:
        text = "template {/a/b/c.py} interpolated"
        stripped = strip_path_segments(text)
        assert "/a/b/c.py" not in stripped
