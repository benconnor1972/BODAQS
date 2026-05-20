from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Optional


SESSION_ARCHIVE_SUFFIX = ".zip"


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_jsonable(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def is_session_archive_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() == SESSION_ARCHIVE_SUFFIX


def raw_session_identity(*, csv_sha256: str, log_metadata_sha256: str) -> str:
    return sha256_jsonable(
        {
            "csv_sha256": csv_sha256,
            "log_metadata_sha256": log_metadata_sha256,
        }
    )


@dataclass(frozen=True)
class SessionArchiveContract:
    csv_member_name: str
    log_metadata_member_name: str
    session_stem: str
    csv_sha256: str
    log_metadata_sha256: str

    @property
    def raw_session_identity(self) -> str:
        return raw_session_identity(
            csv_sha256=self.csv_sha256,
            log_metadata_sha256=self.log_metadata_sha256,
        )


@dataclass(frozen=True)
class SessionInputIdentity:
    input_path: Path
    input_kind: str
    source_identity: str
    source_identity_kind: str
    csv_sha256: str
    log_metadata_sha256: Optional[str] = None
    archive_sha256: Optional[str] = None
    contract: Optional[SessionArchiveContract] = None


@dataclass(frozen=True)
class PreparedSessionInput:
    input_path: Path
    input_kind: str
    csv_path: Path
    csv_sha256: str
    log_metadata_path: Optional[Path] = None
    log_metadata_sha256: Optional[str] = None
    archive_sha256: Optional[str] = None
    contract: Optional[SessionArchiveContract] = None

    @property
    def source_identity(self) -> str:
        if self.contract is not None:
            return self.contract.raw_session_identity
        return self.csv_sha256

    @property
    def source_identity_kind(self) -> str:
        return "raw_session_identity" if self.contract is not None else "csv_sha256"

    def source_manifest(
        self,
        *,
        source_path: str = "source/input.csv",
        source_sha256: Optional[str] = None,
    ) -> dict[str, Any]:
        csv_sha256 = source_sha256 or self.csv_sha256
        manifest: dict[str, Any] = {
            "path": source_path,
            "sha256": csv_sha256,
            "source_identity": self.source_identity,
            "source_identity_kind": self.source_identity_kind,
            "input_kind": self.input_kind,
        }

        if self.contract is None:
            manifest["original_input_path"] = str(self.input_path)
            manifest["original_input_filename"] = self.input_path.name
            return manifest

        manifest.update(
            {
                "raw_session_identity": self.contract.raw_session_identity,
                "original_archive_filename": self.input_path.name,
                "original_archive_sha256": self.archive_sha256,
                "original_archive_path": str(self.input_path),
                "archive_csv_member": self.contract.csv_member_name,
                "archive_csv_sha256": self.contract.csv_sha256,
                "archive_log_metadata_member": self.contract.log_metadata_member_name,
                "archive_log_metadata_sha256": self.contract.log_metadata_sha256,
            }
        )
        return manifest


def _root_member_path(filename: str, *, archive_name: str) -> PurePosixPath:
    normalized = str(filename).replace("\\", "/")
    member_path = PurePosixPath(normalized)
    if member_path.is_absolute():
        raise ValueError(f"Archive member path must be relative: {filename}")
    if any(part in {"", ".", ".."} for part in member_path.parts):
        raise ValueError(f"Archive member contains an unsafe path segment: {filename}")
    if len(member_path.parts) != 1:
        raise ValueError(
            f"Session archive members must be stored at the archive root: {filename}"
        )
    if not member_path.name:
        raise ValueError(f"Archive member has no filename: {archive_name}")
    return member_path


def read_session_archive_contract(archive_path: str | Path) -> SessionArchiveContract:
    archive = Path(archive_path)
    with zipfile.ZipFile(archive, "r") as zf:
        infos = [info for info in zf.infolist() if not info.is_dir()]
        if len(infos) != 2:
            raise ValueError(
                f"Session archive must contain exactly two root files (.csv + .json): {archive.name}"
            )

        for info in infos:
            _root_member_path(info.filename, archive_name=archive.name)

        csv_infos = [info for info in infos if info.filename.lower().endswith(".csv")]
        json_infos = [info for info in infos if info.filename.lower().endswith(".json")]
        if len(csv_infos) != 1 or len(json_infos) != 1:
            raise ValueError(
                f"Session archive must contain exactly one .csv and one .json: {archive.name}"
            )

        csv_info = csv_infos[0]
        json_info = json_infos[0]
        csv_stem = PurePosixPath(csv_info.filename).stem
        json_stem = PurePosixPath(json_info.filename).stem
        if csv_stem != json_stem:
            raise ValueError(
                "Session archive CSV and JSON filenames must share the same stem: "
                f"{csv_info.filename!r} vs {json_info.filename!r}"
            )

        return SessionArchiveContract(
            csv_member_name=csv_info.filename,
            log_metadata_member_name=json_info.filename,
            session_stem=csv_stem,
            csv_sha256=sha256_bytes(zf.read(csv_info)),
            log_metadata_sha256=sha256_bytes(zf.read(json_info)),
        )


def session_input_identity(path: str | Path) -> SessionInputIdentity:
    input_path = Path(path).expanduser().resolve()
    if is_session_archive_path(input_path):
        contract = read_session_archive_contract(input_path)
        return SessionInputIdentity(
            input_path=input_path,
            input_kind="archive",
            source_identity=contract.raw_session_identity,
            source_identity_kind="raw_session_identity",
            csv_sha256=contract.csv_sha256,
            log_metadata_sha256=contract.log_metadata_sha256,
            archive_sha256=sha256_file(input_path),
            contract=contract,
        )

    csv_sha256 = sha256_file(input_path)
    return SessionInputIdentity(
        input_path=input_path,
        input_kind="csv",
        source_identity=csv_sha256,
        source_identity_kind="csv_sha256",
        csv_sha256=csv_sha256,
    )


def extract_session_archive(
    archive_path: str | Path,
    target_dir: str | Path,
    *,
    contract: Optional[SessionArchiveContract] = None,
) -> PreparedSessionInput:
    archive = Path(archive_path).expanduser().resolve()
    target = Path(target_dir).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    resolved_contract = contract or read_session_archive_contract(archive)

    csv_target = target / PurePosixPath(resolved_contract.csv_member_name).name
    json_target = target / PurePosixPath(resolved_contract.log_metadata_member_name).name

    with zipfile.ZipFile(archive, "r") as zf:
        for member_name, target_path in (
            (resolved_contract.csv_member_name, csv_target),
            (resolved_contract.log_metadata_member_name, json_target),
        ):
            with zf.open(member_name, "r") as src, target_path.open("wb") as dst:
                shutil.copyfileobj(src, dst)

    return PreparedSessionInput(
        input_path=archive,
        input_kind="archive",
        csv_path=csv_target,
        csv_sha256=resolved_contract.csv_sha256,
        log_metadata_path=json_target,
        log_metadata_sha256=resolved_contract.log_metadata_sha256,
        archive_sha256=sha256_file(archive),
        contract=resolved_contract,
    )


@contextmanager
def prepare_session_input(
    path: str | Path,
    *,
    work_dir: Optional[str | Path] = None,
) -> Iterator[PreparedSessionInput]:
    input_path = Path(path).expanduser().resolve()
    if is_session_archive_path(input_path):
        temp_parent = Path(work_dir).expanduser().resolve() if work_dir is not None else None
        if temp_parent is not None:
            temp_parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=f"{input_path.stem}_",
            dir=str(temp_parent) if temp_parent is not None else None,
        ) as tmpdir:
            yield extract_session_archive(input_path, tmpdir)
        return

    yield PreparedSessionInput(
        input_path=input_path,
        input_kind="csv",
        csv_path=input_path,
        csv_sha256=sha256_file(input_path),
    )
