"""Back up, migrate and verify only Douban image references.

Backups are encrypted using a key derived from the existing integration token.
They can be restored in an authorized environment with that same token; tokens,
signed image URLs and private page properties are never written to Actions logs.
"""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet
from covers import CoverStore, external_douban_url
from notion_helper import NotionHelper


def cipher(kind):
    token = os.getenv("NOTION_TOKEN") or os.getenv(kind.upper() + "_NOTION_TOKEN")
    if not token:
        raise ValueError("Missing Notion integration token")
    key = hashlib.sha256(("douban-cover-backup-v1:" + token).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def unaffected(page):
    return {
        "id": page["id"],
        "archived": page.get("archived", False),
        "properties": {k: v for k, v in page["properties"].items()
                       if k != "封面" and v.get("type") not in ("last_edited_time", "last_edited_by")},
    }


def needs_repair(page):
    return any(external_douban_url(f) for f in page.get("properties", {}).get("封面", {}).get("files", [])) or any(
        external_douban_url(page.get(k)) for k in ("icon", "cover"))


def restore_payload(page):
    return {"properties": {"封面": {"files": page["properties"]["封面"]["files"]}},
            "icon": page.get("icon"), "cover": page.get("cover")}


def prepare(helper, kind, folder, limit):
    rows = helper.query_all(getattr(helper, kind + "_database_id"))
    candidates = [p for p in rows if needs_repair(p)]
    # Stable canary selection: newest movie/book first.
    candidates.sort(key=lambda p: p.get("created_time", ""), reverse=True)
    if limit:
        candidates = candidates[:limit]
    payload = {"kind": kind, "total": len(rows), "rows": candidates}
    original = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    encrypted = cipher(kind).encrypt(original)
    folder.mkdir(parents=True, exist_ok=True)
    backup = folder / (kind + "-before.enc")
    backup.write_bytes(encrypted)
    restored = cipher(kind).decrypt(backup.read_bytes())
    if restored != original:
        raise RuntimeError("Backup round-trip validation failed")
    # Exercise a restore against isolated copies before touching production.
    for page in json.loads(restored)["rows"]:
        simulated = json.loads(json.dumps(page))
        simulated["properties"]["封面"] = {"files": []}
        simulated["icon"] = None
        original_fields = restore_payload(page)
        simulated["properties"]["封面"] = {**page["properties"]["封面"], **original_fields["properties"]["封面"]}
        simulated["icon"] = original_fields["icon"]
        simulated["cover"] = original_fields["cover"]
        if simulated != page:
            raise RuntimeError("Isolated backup restore failed")
    print(json.dumps({"stage": "backup", "kind": kind, "total": len(rows),
                      "selected": len(candidates), "backup_sha256": hashlib.sha256(encrypted).hexdigest(),
                      "restore_verified": True}), flush=True)


def apply(helper, kind, folder):
    backup = json.loads(cipher(kind).decrypt((folder / (kind + "-before.enc")).read_bytes()))
    store = CoverStore(helper.client)
    results = []
    for index, before in enumerate(backup["rows"], 1):
        try:
            current = store.call(helper.client.pages.retrieve, page_id=before["id"])
            if unaffected(current) != unaffected(before):
                raise RuntimeError("Non-cover properties changed since backup")
            if restore_payload(current) != restore_payload(before):
                if not needs_repair(current):
                    results.append({"id": before["id"], "status": "already_hosted"})
                    continue
                raise RuntimeError("Cover changed since backup")
            payload = store.repair_payload(current)
            if payload:
                updated = store.call(helper.client.pages.update, page_id=current["id"], **payload)
                if unaffected(updated) != unaffected(before):
                    raise RuntimeError("Non-cover properties differ after update")
                if needs_repair(updated):
                    raise RuntimeError("External Douban reference remains")
            results.append({"id": before["id"], "status": "repaired"})
            if len(backup["rows"]) <= 2:
                print(json.dumps({"stage": "canary", "kind": kind, "page_id": before["id"]}), flush=True)
        except Exception as exc:
            # Do not log HTTP bodies, signed URLs or page contents.
            results.append({"id": before["id"], "status": "failed", "error": type(exc).__name__})
            print(json.dumps({"stage": "error", "kind": kind, "index": index,
                              "error": type(exc).__name__, "http_status": getattr(exc, "status", None) or getattr(getattr(exc, "response", None), "status_code", None),
                              "detail": str(exc)[:150] if isinstance(exc, (ValueError, RuntimeError)) else ""}), flush=True)
        if index % 10 == 0 or index == len(backup["rows"]):
            print(json.dumps({"stage": "progress", "kind": kind, "completed": index,
                              "selected": len(backup["rows"]),
                              "failed": sum(r["status"] == "failed" for r in results)}), flush=True)
        # Abort early if the canary/route is broken rather than hammering the CDN.
        if len(results) >= 3 and all(r["status"] == "failed" for r in results[-3:]):
            break
    # Keep receipt encrypted too: row identifiers need not be public.
    (folder / (kind + "-result.enc")).write_bytes(cipher(kind).encrypt(json.dumps(results).encode()))
    all_after = helper.query_all(getattr(helper, kind + "_database_id"))
    receipt = {"kind": kind, "total_before": backup["total"], "total_after": len(all_after),
               "selected": len(backup["rows"]), "processed": len(results),
               "repaired": sum(r["status"] == "repaired" for r in results),
               "failed": sum(r["status"] == "failed" for r in results),
               "remaining_external": sum(bool(needs_repair(p)) for p in all_after)}
    (folder / (kind + "-summary.json")).write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps({"stage": "final", **receipt}), flush=True)
    if receipt["total_before"] != receipt["total_after"] or receipt["failed"] or len(results) != len(backup["rows"]):
        raise RuntimeError("Cover repair did not pass verification; see encrypted receipt")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare", "apply"])
    parser.add_argument("kind", choices=["movie", "book"])
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--folder", type=Path, default=Path("cover-repair"))
    args = parser.parse_args()
    helper = NotionHelper(args.kind)
    if args.mode == "prepare":
        prepare(helper, args.kind, args.folder, args.limit)
    else:
        apply(helper, args.kind, args.folder)
