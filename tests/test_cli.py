from click.testing import CliRunner

from audiobookshelf_sync.__main__ import main


def test_configure_list_target_libraries_help() -> None:
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "Audiobookshelf" in result.output
