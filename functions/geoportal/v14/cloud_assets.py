from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from google.cloud import storage
from google.oauth2 import service_account


DEFAULT_LOCAL_ASSET_ROOT = Path(
    os.environ.get(
        "LOCAL_ASSET_ROOT",
        "/datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server",
    )
)
DEFAULT_GCS_BUCKET_NAME = "ksa_datepalm"
DEFAULT_GCS_ASSET_PREFIX = "app_server"
DEFAULT_APP_ASSET_BASE_URL = "/static/assets"
DEFAULT_GCLOUD_BIN = os.environ.get(
    "GCLOUD_BIN",
    "/rhome/lit0a/google-cloud-sdk/bin/gcloud",
)

CACHE_ROOT = Path(tempfile.gettempdir()) / "geoportal_asset_cache"
CACHE_ROOT.mkdir(parents=True, exist_ok=True)
_FORCE_GCS = os.environ.get("FORCE_GCS", "").strip().lower() in {"1", "true", "yes", "on"}
_LAST_FETCH_INFO = {
    "path": None,
    "source": None,
    "resolved_path": None,
    "object_name": None,
    "mode": None,
    "detail": None,
}


def gcs_enabled() -> bool:
    return bool(os.environ.get("GCS_BUCKET_NAME", DEFAULT_GCS_BUCKET_NAME))


def force_gcs_enabled() -> bool:
    return _FORCE_GCS


def set_force_gcs(enabled: bool) -> None:
    global _FORCE_GCS
    _FORCE_GCS = bool(enabled)


def _record_fetch(path: str | Path, source: str, *, resolved_path: str | None = None, detail: str | None = None) -> None:
    global _LAST_FETCH_INFO
    try:
        object_name = object_name_for_path(path)
    except Exception:
        object_name = None
    _LAST_FETCH_INFO = {
        "path": str(path),
        "source": source,
        "resolved_path": resolved_path,
        "object_name": object_name,
        "mode": "force_gcs" if force_gcs_enabled() else "local_first",
        "detail": detail,
    }


def last_fetch_info() -> dict:
    return dict(_LAST_FETCH_INFO)


def use_service_account_json() -> bool:
    return bool(os.environ.get("GCP_SERVICE_ACCOUNT_JSON"))


@lru_cache(maxsize=1)
def get_gcs_client() -> storage.Client:
    if use_service_account_json():
        raw = os.environ["GCP_SERVICE_ACCOUNT_JSON"]
        info = json.loads(raw)
        credentials = service_account.Credentials.from_service_account_info(info)
        return storage.Client(project=info["project_id"], credentials=credentials)
    return storage.Client()


@lru_cache(maxsize=1)
def get_bucket():
    return get_gcs_client().bucket(os.environ.get("GCS_BUCKET_NAME", DEFAULT_GCS_BUCKET_NAME))


@lru_cache(maxsize=1)
def asset_prefix() -> str:
    return os.environ.get("GCS_ASSET_PREFIX", DEFAULT_GCS_ASSET_PREFIX).strip("/")


@lru_cache(maxsize=1)
def local_asset_root() -> Path:
    return DEFAULT_LOCAL_ASSET_ROOT


@lru_cache(maxsize=1)
def asset_base_url() -> str:
    value = os.environ.get("APP_ASSET_BASE_URL", DEFAULT_APP_ASSET_BASE_URL)
    if not value.startswith("/"):
        value = "/" + value
    return value.rstrip("/")


def _rel_asset_path(path: str | Path) -> Path:
    p = Path(path)
    if p.is_absolute():
        try:
            return p.relative_to(local_asset_root())
        except Exception:
            try:
                return p.relative_to(CACHE_ROOT)
            except Exception as exc:
                raise ValueError(f"Path {p} is outside LOCAL_ASSET_ROOT={local_asset_root()}") from exc
    return p


def local_path_for(path: str | Path) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    return local_asset_root() / p


def object_name_for_path(path: str | Path) -> str:
    rel = _rel_asset_path(path).as_posix().lstrip("/")
    prefix = asset_prefix()
    return f"{prefix}/{rel}" if prefix else rel


def gcs_uri_for_path(path: str | Path) -> str:
    bucket = os.environ.get("GCS_BUCKET_NAME", DEFAULT_GCS_BUCKET_NAME)
    return f"gs://{bucket}/{object_name_for_path(path)}"


def cached_path_for(path: str | Path) -> Path:
    return CACHE_ROOT / _rel_asset_path(path)


def _run_gcloud(args: list[str], capture_output: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        [DEFAULT_GCLOUD_BIN, *args],
        check=True,
        capture_output=capture_output,
    )


def _gcloud_exists(path: str | Path) -> bool:
    uri = gcs_uri_for_path(path)
    try:
        result = _run_gcloud(["storage", "ls", uri], capture_output=True)
        return uri in result.stdout.decode("utf-8", errors="ignore")
    except subprocess.CalledProcessError:
        return False


def _gcloud_download_file(path: str | Path, target: Path) -> bool:
    uri = gcs_uri_for_path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        _run_gcloud(["storage", "cp", uri, str(target)])
        return True
    except subprocess.CalledProcessError:
        return False


def _gcloud_download_bytes(path: str | Path) -> bytes:
    uri = gcs_uri_for_path(path)
    result = _run_gcloud(["storage", "cat", uri], capture_output=True)
    return result.stdout


def ensure_local_asset(path: str | Path) -> Path:
    p = local_path_for(path)
    if not force_gcs_enabled() and p.exists():
        _record_fetch(path, "local", resolved_path=str(p))
        return p
    if not gcs_enabled():
        _record_fetch(path, "local-missing-gcs-disabled", resolved_path=str(p))
        return p

    target = cached_path_for(path)
    if target.exists():
        _record_fetch(path, "cache", resolved_path=str(target))
        return target

    try:
        blob = get_bucket().blob(object_name_for_path(path))
        if not blob.exists():
            _record_fetch(path, "gcs-missing", resolved_path=str(p))
            return p
        target.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(target))
        _record_fetch(path, "gcs-download", resolved_path=str(target), detail="google-cloud-storage")
        return target
    except Exception:
        ok = _gcloud_download_file(path, target)
        if ok:
            _record_fetch(path, "gcs-download", resolved_path=str(target), detail="gcloud")
        else:
            _record_fetch(path, "gcs-download-failed", resolved_path=str(target), detail="gcloud")
        return target if ok else p


def ensure_local_directory(path: str | Path, suffixes: Iterable[str] | None = None) -> Path:
    p = local_path_for(path)
    if p.is_dir():
        return p
    if not gcs_enabled():
        return p

    target_dir = cached_path_for(path)
    target_dir.mkdir(parents=True, exist_ok=True)
    prefix = gcs_uri_for_path(path).rstrip("/") + "/"
    suffixes = tuple(suffixes or ())
    found = False

    try:
        blob_prefix = object_name_for_path(path).rstrip("/") + "/"
        for blob in get_bucket().list_blobs(prefix=blob_prefix):
            rel_name = blob.name[len(blob_prefix):]
            if not rel_name or rel_name.endswith("/"):
                continue
            if suffixes and not rel_name.lower().endswith(tuple(s.lower() for s in suffixes)):
                continue
            found = True
            dst = target_dir / rel_name
            if dst.exists():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            blob.download_to_filename(str(dst))
        return target_dir if found else p
    except Exception:
        result = _run_gcloud(["storage", "ls", "--recursive", prefix], capture_output=True)
        lines = result.stdout.decode("utf-8", errors="ignore").splitlines()
        for line in lines:
            uri = line.strip()
            if not uri or uri.endswith("/"):
                continue
            rel_name = uri[len(prefix):]
            if suffixes and not rel_name.lower().endswith(tuple(s.lower() for s in suffixes)):
                continue
            found = True
            dst = target_dir / rel_name
            if dst.exists():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                _run_gcloud(["storage", "cp", uri, str(dst)])
            except subprocess.CalledProcessError:
                pass
        return target_dir if found else p

    return target_dir if found else p


def list_directory_names(path: str | Path, suffix: str) -> list[str]:
    p = local_path_for(path)
    if p.is_dir():
        return sorted(x.stem for x in p.glob(f"*{suffix}"))
    if not gcs_enabled():
        return []

    names: list[str] = []

    try:
        prefix = object_name_for_path(path).rstrip("/") + "/"
        for blob in get_bucket().list_blobs(prefix=prefix):
            name = Path(blob.name).name
            if name.lower().endswith(suffix.lower()):
                names.append(Path(name).stem)
        return sorted(set(names))
    except Exception:
        prefix = gcs_uri_for_path(path).rstrip("/") + "/"
        result = _run_gcloud(["storage", "ls", "--recursive", prefix], capture_output=True)
        lines = result.stdout.decode("utf-8", errors="ignore").splitlines()
        for line in lines:
            name = Path(line.strip()).name
            if name.lower().endswith(suffix.lower()):
                names.append(Path(name).stem)

    return sorted(set(names))


def read_asset_bytes(path: str | Path) -> bytes:
    if force_gcs_enabled() and gcs_enabled():
        try:
            blob = get_bucket().blob(object_name_for_path(path))
            data = blob.download_as_bytes()
            _record_fetch(path, "gcs-bytes", resolved_path=gcs_uri_for_path(path), detail="google-cloud-storage")
            return data
        except Exception:
            data = _gcloud_download_bytes(path)
            _record_fetch(path, "gcs-bytes", resolved_path=gcs_uri_for_path(path), detail="gcloud")
            return data

    local = ensure_local_asset(path)
    if local.exists():
        _record_fetch(path, "local-bytes", resolved_path=str(local))
        return local.read_bytes()

    try:
        blob = get_bucket().blob(object_name_for_path(path))
        data = blob.download_as_bytes()
        _record_fetch(path, "gcs-bytes", resolved_path=gcs_uri_for_path(path), detail="google-cloud-storage")
        return data
    except Exception:
        data = _gcloud_download_bytes(path)
        _record_fetch(path, "gcs-bytes", resolved_path=gcs_uri_for_path(path), detail="gcloud")
        return data


def asset_url_for(path: str | Path) -> str:
    rel = _rel_asset_path(path).as_posix().lstrip("/")
    return f"{asset_base_url()}/{rel}"


def guess_content_type(path: str | Path, fallback: str | None = None) -> str:
    p = str(path)
    if p.endswith(".pbf"):
        return "application/vnd.mapbox-vector-tile"
    if p.endswith(".mvt"):
        return "application/vnd.mapbox-vector-tile"
    guessed, _ = mimetypes.guess_type(p)
    return fallback or guessed or "application/octet-stream"
