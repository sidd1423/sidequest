"""Create the Tiger Data `quests` table (if needed) and load the example quests.

Usage (from the project root, venv active):
    python -m tiger.seed               # create table + embed + upsert all seed quests
    python -m tiger.seed --check       # just test the connection and count rows
    python -m tiger.seed --skip-schema # table already created by hand

Safe to re-run: quests are upserted on quest_text.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).parent


def embedding_text(q: dict) -> str:
    """What we embed for each library quest - text plus its metadata."""
    return (
        f"{q['quest_text']} Category: {q['category']}. "
        f"Takes about {q['duration_minutes']} minutes. Difficulty: {q['difficulty']}. "
        f"Tags: {', '.join(q['tags'])}."
    )


def load_seed(path: Path) -> list[dict]:
    from backend.schemas import QuestExample

    rows = json.loads(path.read_text(encoding="utf-8"))
    for r in rows:  # validate shape and difficulty values early
        QuestExample(**r)
    return rows


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    from backend import retrieval
    from backend.embeddings import GeminiEmbedder

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", type=Path, default=HERE / "seed_quests.json")
    ap.add_argument("--skip-schema", action="store_true", help="don't run tiger/schema.sql")
    ap.add_argument("--check", action="store_true", help="only test the connection")
    args = ap.parse_args(argv)

    import psycopg

    url = retrieval.tiger_url()
    if not url:
        print("TIGER_DATABASE_URL is not set in .env", file=sys.stderr)
        return 1
    table = retrieval.table_name()

    with psycopg.connect(url, connect_timeout=15) as conn:
        print("Connected to Tiger Data:", conn.execute("select version()").fetchone()[0].split(",")[0])
        if args.check:
            try:
                n = conn.execute(f"select count(*), count(embedding) from {table}").fetchone()
                print(f"{table}: {n[0]} rows, {n[1]} with embeddings")
            except psycopg.errors.UndefinedTable:
                print(f"{table}: table does not exist yet")
            return 0

        embedder = GeminiEmbedder()
        if not args.skip_schema:
            sql = (HERE / "schema.sql").read_text(encoding="utf-8")
            sql = re.sub(r"\bquests(?=_|\b)", table, sql).replace("VECTOR(768)", f"VECTOR({embedder.dim})")
            conn.execute(sql)
            print(f"Schema ready ({table}, vector({embedder.dim}))")

        rows = load_seed(args.file)
        print(f"Embedding {len(rows)} quests with {embedder.model} ({embedder.dim} dims)...")
        vectors = embedder.embed([embedding_text(r) for r in rows], task="RETRIEVAL_DOCUMENT")

        with conn.cursor() as cur:
            for r, v in zip(rows, vectors):
                cur.execute(
                    f"""
                    INSERT INTO {table} (quest_text, category, duration_minutes, difficulty, tags, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s::vector)
                    ON CONFLICT (quest_text) DO UPDATE SET
                        category = EXCLUDED.category,
                        duration_minutes = EXCLUDED.duration_minutes,
                        difficulty = EXCLUDED.difficulty,
                        tags = EXCLUDED.tags,
                        embedding = EXCLUDED.embedding
                    """,
                    (r["quest_text"], r["category"], r["duration_minutes"], r["difficulty"], r["tags"],
                     "[" + ",".join(f"{x:.7f}" for x in v) + "]"),
                )
        total = conn.execute(f"select count(*) from {table}").fetchone()[0]
        print(f"Done - {len(rows)} quests upserted, {total} rows in {table}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
