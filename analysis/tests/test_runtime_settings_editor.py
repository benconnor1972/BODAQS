from __future__ import annotations

from pathlib import Path

from bodaqs_analysis.ui.runtime_settings_editor import PreprocessRuntimeSettingsEditor


class _FakeSelector:
    def __init__(self) -> None:
        self.artifacts_dir = None
        self.refresh_count = 0

    def refresh(self) -> None:
        self.refresh_count += 1


def test_runtime_settings_editor_returns_notebook_values(tmp_path):
    log_dir = tmp_path / "logs"
    profile_path = tmp_path / "profile.json"
    artifacts_dir = tmp_path / "artifacts"
    bike_profile_path = tmp_path / "bike.json"
    log_metadata_path = tmp_path / "metadata.json"

    editor = PreprocessRuntimeSettingsEditor(
        log_dir=log_dir,
        preprocess_profile_path=profile_path,
        artifacts_dir=artifacts_dir,
        generic_log_metadata_paths=[log_metadata_path],
        bike_profile_path=bike_profile_path,
        fit_dir=None,
        fit_bindings_path=None,
        prompt_for_descriptions=False,
        run_tz_label="UTC",
        state_file=tmp_path / ".runtime_settings.json",
    )

    settings = editor.get_settings()

    assert settings["log_dir"] == log_dir
    assert settings["preprocess_profile_path"] == profile_path
    assert settings["artifacts_dir"] == artifacts_dir
    assert settings["generic_log_metadata_paths"] == [log_metadata_path]
    assert settings["bike_profile_path"] == bike_profile_path
    assert settings["fit_dir"] is None
    assert settings["fit_bindings_path"] is None
    assert settings["prompt_for_descriptions"] is False
    assert settings["run_tz_label"] == "UTC"


def test_runtime_settings_editor_blank_generic_metadata_means_none(tmp_path):
    editor = PreprocessRuntimeSettingsEditor(
        preprocess_profile_path=tmp_path / "profile.json",
        artifacts_dir=tmp_path / "artifacts",
        generic_log_metadata_paths=[tmp_path / "metadata.json"],
        state_file=tmp_path / ".runtime_settings.json",
    )

    editor.w_generic_log_metadata_paths.value = ""

    assert editor.get_settings()["generic_log_metadata_paths"] is None


def test_runtime_settings_editor_can_bind_log_selector(tmp_path):
    editor = PreprocessRuntimeSettingsEditor(
        preprocess_profile_path=tmp_path / "profile.json",
        artifacts_dir=tmp_path / "artifacts_a",
        state_file=tmp_path / ".runtime_settings.json",
    )
    selector = _FakeSelector()

    editor.bind_log_selector(selector)
    assert selector.artifacts_dir == tmp_path / "artifacts_a"
    assert selector.refresh_count == 1

    editor.w_artifacts_dir.value = str(tmp_path / "artifacts_b")
    assert selector.artifacts_dir == tmp_path / "artifacts_b"
    assert selector.refresh_count == 2


def test_runtime_settings_editor_persists_local_state(tmp_path):
    state_file = tmp_path / ".runtime_settings.json"
    log_dir = tmp_path / "logs_saved"
    profile_path = tmp_path / "profile_saved.json"
    artifacts_dir = tmp_path / "artifacts_saved"
    bike_profile_path = tmp_path / "bike_saved.json"
    fit_dir = tmp_path / "Garmin" / "FIT"
    fit_bindings_path = tmp_path / "fit_bindings_saved.json"
    generic_log_metadata_path = tmp_path / "metadata_saved.json"

    editor = PreprocessRuntimeSettingsEditor(
        log_dir=tmp_path / "logs_default",
        preprocess_profile_path=tmp_path / "profile_default.json",
        artifacts_dir=tmp_path / "artifacts_default",
        state_file=state_file,
        show_log_dir=True,
    )
    editor.w_log_dir.value = str(log_dir)
    editor.w_preprocess_profile_path.value = str(profile_path)
    editor.w_artifacts_dir.value = str(artifacts_dir)
    editor.w_generic_log_metadata_paths.value = str(generic_log_metadata_path)
    editor.w_bike_profile_path.value = str(bike_profile_path)
    editor.w_fit_dir.value = str(fit_dir)
    editor.w_fit_bindings_path.value = str(fit_bindings_path)
    editor.w_prompt_for_descriptions.value = False
    editor.w_run_tz_label.value = "UTC"

    restored = PreprocessRuntimeSettingsEditor(
        log_dir=tmp_path / "logs_other_default",
        preprocess_profile_path=tmp_path / "profile_other_default.json",
        artifacts_dir=tmp_path / "artifacts_other_default",
        state_file=state_file,
        show_log_dir=True,
    )
    settings = restored.get_settings()

    assert settings["log_dir"] == log_dir
    assert settings["preprocess_profile_path"] == profile_path
    assert settings["artifacts_dir"] == artifacts_dir
    assert settings["generic_log_metadata_paths"] == [generic_log_metadata_path]
    assert settings["bike_profile_path"] == bike_profile_path
    assert settings["fit_dir"] == fit_dir
    assert settings["fit_bindings_path"] == fit_bindings_path
    assert settings["prompt_for_descriptions"] is False
    assert settings["run_tz_label"] == "UTC"


def test_runtime_settings_editor_can_render_subset_ui(tmp_path):
    editor = PreprocessRuntimeSettingsEditor(
        log_dir=tmp_path / "logs",
        preprocess_profile_path=tmp_path / "profile.json",
        artifacts_dir=tmp_path / "artifacts",
        state_file=tmp_path / ".runtime_settings.json",
        show_log_dir=True,
        show_preprocess_profile_path=False,
        show_generic_log_metadata=False,
        show_bike_profile_path=False,
        show_fit_inputs=False,
        show_prompt_for_descriptions=False,
        show_run_tz_label=False,
    )

    assert editor.ui.children
    assert "Runtime settings" not in str(editor.ui.children[0])
    settings = editor.get_settings()
    assert settings["log_dir"] == tmp_path / "logs"
    assert settings["artifacts_dir"] == tmp_path / "artifacts"
