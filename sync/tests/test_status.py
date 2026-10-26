import asyncio
import json

import activities
from activities import merge_status


def entry(status, at="2026-10-16T07:31:05+03:00", **kw):
    return {"status": status, "message": "x", "updated_at": at, **kw}


def test_merge_keeps_other_sources():
    doc = {"sources": {"cal": entry("done")}}
    out = merge_status(doc, "amex", entry("scraping"))
    assert set(out["sources"]) == {"cal", "amex"}
    assert out["sources"]["cal"] == doc["sources"]["cal"]
    assert out["updated_at"] == "2026-10-16T07:31:05+03:00"


def test_last_success_moves_only_on_done():
    doc = merge_status(None, "amex", entry("done", at="2026-10-15T07:35:00+03:00"))
    assert doc["sources"]["amex"]["last_success_at"] == "2026-10-15T07:35:00+03:00"
    doc = merge_status(doc, "amex", entry("waiting_for_login", at="2026-10-16T07:31:00+03:00"))
    assert doc["sources"]["amex"]["last_success_at"] == "2026-10-15T07:35:00+03:00"
    doc = merge_status(doc, "amex", entry("done", at="2026-10-16T08:02:00+03:00"))
    assert doc["sources"]["amex"]["last_success_at"] == "2026-10-16T08:02:00+03:00"


def test_publish_status_writes_local_file_without_publish(tmp_path, monkeypatch):
    target = tmp_path / "digested" / "sync-status.json"
    monkeypatch.setattr(activities, "STATUS_FILE", target)
    monkeypatch.delenv("SYNC_PUBLISH", raising=False)
    assert asyncio.run(activities.publish_status("amex", entry("scraping", step=2, total_steps=4))) == "local"
    doc = json.loads(target.read_text())
    assert doc["sources"]["amex"]["status"] == "scraping"
    assert doc["sources"]["amex"]["step"] == 2


def test_publish_status_survives_a_corrupt_file(tmp_path, monkeypatch):
    target = tmp_path / "sync-status.json"
    target.write_text("{not json")
    monkeypatch.setattr(activities, "STATUS_FILE", target)
    monkeypatch.delenv("SYNC_PUBLISH", raising=False)
    assert asyncio.run(activities.publish_status("amex", entry("done"))) == "local"
    assert json.loads(target.read_text())["sources"]["amex"]["status"] == "done"


def test_publish_status_never_raises_when_upload_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(activities, "STATUS_FILE", tmp_path / "sync-status.json")
    monkeypatch.setenv("SYNC_PUBLISH", "1")
    monkeypatch.setenv("BUCKET", "b")
    monkeypatch.setattr(activities, "_bucket_cache", None)

    async def boom(*a, **k):
        raise OSError("aws: command not found")

    monkeypatch.setattr(activities, "run_cmd", boom)
    assert asyncio.run(activities.publish_status("amex", entry("done"))).startswith("error:")


def test_status_file_is_not_in_the_data_only_upload_list():
    """deploy.sh --data-only uploads a fixed list; it must not touch sync-status.json."""
    deploy = (activities.REPO_ROOT / "infra" / "deploy.sh").read_text()
    assert "sync-status" not in deploy


def _capture_db(monkeypatch, fail=False):
    calls = []

    def fake(url, source, e):
        if fail:
            raise OSError("db down")
        calls.append((url, source, e))

    monkeypatch.setattr(activities, "_db_upsert_status", fake)
    return calls


def test_publish_status_upserts_merged_entry_into_db(tmp_path, monkeypatch):
    target = tmp_path / "sync-status.json"
    monkeypatch.setattr(activities, "STATUS_FILE", target)
    monkeypatch.delenv("SYNC_PUBLISH", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    calls = _capture_db(monkeypatch)
    asyncio.run(activities.publish_status("amex", entry("done", at="2026-10-15T07:35:00+03:00")))
    asyncio.run(activities.publish_status("amex", entry("scraping", at="2026-10-16T07:31:00+03:00")))
    assert calls[0][:2] == ("postgresql://x", "amex")
    assert calls[1][2]["status"] == "scraping"
    assert calls[1][2]["last_success_at"] == "2026-10-15T07:35:00+03:00"


def test_publish_status_db_failure_does_not_break_json(tmp_path, monkeypatch):
    target = tmp_path / "sync-status.json"
    monkeypatch.setattr(activities, "STATUS_FILE", target)
    monkeypatch.delenv("SYNC_PUBLISH", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    _capture_db(monkeypatch, fail=True)
    assert asyncio.run(activities.publish_status("amex", entry("done"))) == "local"
    assert json.loads(target.read_text())["sources"]["amex"]["status"] == "done"


def test_publish_status_skips_db_without_url(tmp_path, monkeypatch):
    monkeypatch.setattr(activities, "STATUS_FILE", tmp_path / "sync-status.json")
    monkeypatch.delenv("SYNC_PUBLISH", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(activities, "REPO_ROOT", tmp_path)  # no .env here
    calls = _capture_db(monkeypatch)
    assert asyncio.run(activities.publish_status("amex", entry("done"))) == "local"
    assert calls == []


def test_seed_status_db_skips_without_database_url(tmp_path, monkeypatch):
    # The worker seeds sync_status from the JSON on start; no DB configured means a quiet no-op.
    monkeypatch.setattr(activities, "_database_url", lambda: None)
    assert activities.seed_status_db() == 0
