# Notion-hosted Douban covers

New movie and book records upload the actual image to Notion. The same upload is
used by the `封面` property and page icon. HTML challenges and CDN error bodies
are rejected, including HTTP 200 responses. Existing non-Douban images are kept.
If an old image has been removed, the uploader requests current metadata for
the record's exact Douban subject ID and validates that ID before trying its
current large/normal cover. It never substitutes an image from another work.

For existing records, run **repair Notion covers** with `limit=1`, inspect both
canary pages in Notion, then run with `limit=0`. The job backs up selected pages,
checks an isolated restore, and persists the encrypted backup artifact before
changing records. It only writes cover files, Douban page icons and Douban page
covers. The before/after comparison includes every other property. A failure
stops after three consecutive failed items; successfully hosted images are
skipped by later runs.

Artifacts contain encrypted page snapshots and repair receipts, plus counts.
Keep a local copy of the backup artifacts before their 90-day retention expires.
The encryption key is derived from the existing Notion integration token. Keep
that token available in its protected secret store until rollback is no longer
needed; do not log or commit it. Rotating the token requires preserving the old
one securely to decrypt an earlier backup.

Rollback: revert the code commit to restore the former sync behavior. This does
not revert already migrated covers. For those, decrypt the relevant
`*-before.enc` with `repair_covers.cipher(kind)` in an authorized environment
using the original token. Restore only the original Douban external entries in
`properties.封面.files`, `icon` and `cover`, retaining other current attachments
and all other properties. Verify a single restored item before a wider rollback.
Do not replace entire pages or databases from the snapshots.

Validation: `python -m unittest discover -s tests -v`; install
`cryptography==50.0.2` to include encrypted-backup tests. The ordinary sync does
not require cryptography.
