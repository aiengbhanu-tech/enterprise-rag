import argparse
import hashlib
import json
import os
import secrets
from pathlib import Path

from .connectors import (
    drive_text,
    export_json,
    notion_page,
    pdf,
    slack_thread,
    sqlite_table,
    website,
)
from .models import DenseEmbedding, HashEmbedding
from .store import Store


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    token = sub.add_parser("token")
    token.add_argument("--tenant", required=True)
    token.add_argument("--user", required=True)
    token.add_argument("--group", action="append", default=[])
    token.add_argument("--admin", action="store_true")
    token.add_argument("--out", required=True, help="New credential config file; refuses overwrite")
    sync = sub.add_parser("sync")
    sync.add_argument("--db", required=True)
    sync.add_argument("--tenant", required=True)
    sync.add_argument("--source", required=True)
    sync.add_argument("--profile", choices=["smoke", "learned"], default="learned")
    sync.add_argument("--strategy", choices=["fixed", "semantic"], default="semantic")
    sync.add_argument("--export")
    sync.add_argument("--pdf")
    sync.add_argument("--website")
    sync.add_argument("--host", action="append", default=[])
    sync.add_argument("--drive")
    sync.add_argument("--notion")
    sync.add_argument("--slack-channel")
    sync.add_argument("--slack-thread")
    sync.add_argument("--sqlite")
    sync.add_argument("--table")
    sync.add_argument("--id-column", default="id")
    sync.add_argument("--text-column", action="append", default=[])
    sync.add_argument("--acl", action="append", default=[], help="Verified upstream ACL; default denies all")
    args = parser.parse_args()
    if args.command == "token":
        secret = secrets.token_urlsafe(32)
        item = {
            "sha256": hashlib.sha256(secret.encode()).hexdigest(),
            "tenant": args.tenant,
            "user": args.user,
            "groups": args.group,
            "admin": args.admin,
        }
        fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump([item], stream, indent=2)
        print("Bearer token (shown once): " + secret)
        return
    choices = [args.export, args.pdf, args.website, args.drive, args.notion, args.slack_channel, args.sqlite]
    if sum(bool(x) for x in choices) != 1:
        parser.error("Select exactly one ingestion input")
    embedder = HashEmbedding() if args.profile == "smoke" else DenseEmbedding(revision=os.getenv("RAG_EMBED_REVISION"))
    cursor, deleted = "", []
    if args.export:
        docs, cursor, deleted = export_json(args.export)
    elif args.pdf:
        docs = [pdf(args.pdf, Path(args.pdf).name, args.acl)]
    elif args.website:
        docs = [website(args.website, args.acl, set(args.host))]
    elif args.drive:
        docs = [drive_text(args.drive, os.environ["DRIVE_TOKEN"], args.acl)]
    elif args.notion:
        docs = [notion_page(args.notion, os.environ["NOTION_TOKEN"], args.acl)]
    elif args.slack_channel:
        if not args.slack_thread:
            parser.error("--slack-thread is required")
        docs = [slack_thread(args.slack_channel, args.slack_thread, os.environ["SLACK_TOKEN"], args.acl)]
    else:
        docs = sqlite_table(args.sqlite, args.table, args.id_column, args.text_column, args.acl)
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    print(
        json.dumps(
            Store(args.db).sync(
                args.tenant, args.source, docs, embedder, strategy=args.strategy, cursor=cursor, deleted=deleted
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
