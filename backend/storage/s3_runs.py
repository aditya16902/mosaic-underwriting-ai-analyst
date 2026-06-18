"""
S3-backed storage for run artifacts.

Only used when S3_RUNS_BUCKET is set (AWS). Local dev / Docker Compose
leave it unset and every function here becomes a no-op — the rest of the
app keeps reading/writing RUNS_DIR on local disk exactly as before.

Why upload-after-write rather than write-directly-to-S3: every existing
function in backend/report/snapshot.py (openpyxl writing an xlsx, sqlite3
writing merged_metrics.db, json.dumps to a local path) already works
correctly against a local filesystem path. Rewriting each of them to
target S3 directly would mean touching working code in several places
for no functional benefit — boto3's upload_file just needs a local path
to read from, so the simplest correct change is: keep every write
function as-is, then upload the finished directory as one extra step.
"""

import boto3
from pathlib import Path
from botocore.exceptions import ClientError

from backend.config import S3_RUNS_BUCKET, AWS_REGION

_s3_client = None


def _client():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3", region_name=AWS_REGION)
    return _s3_client


def s3_enabled() -> bool:
    return bool(S3_RUNS_BUCKET)


def upload_run_directory(run_dir: Path, run_id: str) -> None:
    """
    Uploads every file in a completed run directory to
    s3://{S3_RUNS_BUCKET}/runs/{run_id}/{filename}.
    Called once, at the end of create_snapshot(), after every local write
    function has already finished. No-op if S3 isn't configured.
    """
    if not s3_enabled():
        return

    client = _client()
    for fpath in run_dir.iterdir():
        if fpath.is_file():
            key = f"runs/{run_id}/{fpath.name}"
            client.upload_file(str(fpath), S3_RUNS_BUCKET, key)
    print(f"[S3] Uploaded run {run_id} → s3://{S3_RUNS_BUCKET}/runs/{run_id}/")


def download_file(run_id: str, filename: str, local_path: Path) -> None:
    """
    Downloads a single object from s3://{S3_RUNS_BUCKET}/runs/{run_id}/{filename}
    to local_path. Used by the chat agent to pull merged_metrics.db back onto
    local disk before querying it — SQLite needs a real local file, it can't
    open a database directly out of S3.
    """
    if not s3_enabled():
        raise RuntimeError("download_file called but S3_RUNS_BUCKET is not set")

    client = _client()
    key = f"runs/{run_id}/{filename}"
    try:
        client.download_file(S3_RUNS_BUCKET, key, str(local_path))
    except ClientError as e:
        raise FileNotFoundError(f"{key} not found in S3: {e}")


def delete_run_directory(run_id: str) -> None:
    """
    Mirrors the irreversible local shutil.rmtree() in routes.py's
    DELETE /reports/{run_id} — without this, deleting a report would
    remove the DB row and local files but leave an orphaned copy in S3
    forever, silently consuming storage no UI ever shows again.
    """
    if not s3_enabled():
        return

    client = _client()
    prefix = f"runs/{run_id}/"
    paginator = client.get_paginator("list_objects_v2")
    keys_to_delete = []
    for page in paginator.paginate(Bucket=S3_RUNS_BUCKET, Prefix=prefix):
        keys_to_delete += [{"Key": obj["Key"]} for obj in page.get("Contents", [])]

    if keys_to_delete:
        client.delete_objects(Bucket=S3_RUNS_BUCKET, Delete={"Objects": keys_to_delete})
    print(f"[S3] Deleted {len(keys_to_delete)} object(s) for run {run_id}")


def presigned_download_url(run_id: str, filename: str, expires_in: int = 300) -> str:
    """
    Returns a temporary, signed URL for a single file in S3, valid for
    expires_in seconds (default 5 minutes). Used instead of FileResponse
    for narrative/snapshot-zip/file downloads when S3 is configured —
    the browser fetches directly from S3, the backend never streams the
    file's bytes through itself.
    """
    client = _client()
    key = f"runs/{run_id}/{filename}"
    try:
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_RUNS_BUCKET, "Key": key},
            ExpiresIn=expires_in,
        )
    except ClientError as e:
        raise FileNotFoundError(f"Could not generate URL for {key}: {e}")


def object_exists(run_id: str, filename: str) -> bool:
    """Cheap existence check without downloading — used before attempting a fetch/download."""
    client = _client()
    try:
        client.head_object(Bucket=S3_RUNS_BUCKET, Key=f"runs/{run_id}/{filename}")
        return True
    except ClientError:
        return False


def fetch_object_text(run_id: str, filename: str) -> str:
    """
    Reads a single object's full content as text directly into memory.
    Used for small JSON/HTML files the backend needs to read and return
    itself (dashboard_data.json, narrative_report.html) rather than just
    redirect the browser to — those routes parse or render the content,
    not just hand back a file.
    """
    client = _client()
    key = f"runs/{run_id}/{filename}"
    try:
        obj = client.get_object(Bucket=S3_RUNS_BUCKET, Key=key)
        return obj["Body"].read().decode("utf-8")
    except ClientError as e:
        raise FileNotFoundError(f"{key} not found in S3: {e}")


def list_run_files(run_id: str) -> list:
    """Returns [{name, size_bytes}, ...] for every file under a run's S3 prefix."""
    client = _client()
    prefix = f"runs/{run_id}/"
    paginator = client.get_paginator("list_objects_v2")
    files = []
    for page in paginator.paginate(Bucket=S3_RUNS_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            files.append({
                "name": obj["Key"].removeprefix(prefix),
                "size_bytes": obj["Size"],
            })
    return files
