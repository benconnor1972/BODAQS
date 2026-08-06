from __future__ import annotations

from bodaqs_history.cli import main


def test_cli_reports_openai_errors_without_traceback(monkeypatch, tmp_path, capsys) -> None:
    config_path = tmp_path / "project.yaml"
    config_path.write_text(
        "sources:\n  - id: source\n    path: missing\noutput:\n  private_work: work\n  corpus: corpus\n",
        encoding="utf-8",
    )

    class SyntheticOpenAIError(Exception):
        __module__ = "openai.errors"

    def raise_openai_error(*_args, **_kwargs):
        raise SyntheticOpenAIError("quota unavailable")

    monkeypatch.setattr("bodaqs_history.cli._run", raise_openai_error)
    assert main(["inventory", "--config", str(config_path)]) == 2
    assert "OpenAI API request failed: quota unavailable" in capsys.readouterr().out
