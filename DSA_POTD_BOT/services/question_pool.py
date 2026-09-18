# services/question_pool.py

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.model import Questions, Source, Difficulty
from db.session import AsyncSessionLocal, engine

logger = logging.getLogger(__name__)

# ---- Codeforces rating -> Difficulty thresholds ----
CF_EASY_MAX = 1200
CF_MEDIUM_MAX = 1900

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=60)
LEETCODE_PAGE_SIZE = 100        # API hard cap


# =========================================================
# 1. Codeforces
# =========================================================
def _cf_rating_to_difficulty(rating: int | None) -> Difficulty:
    if rating is None:
        return Difficulty.medium
    if rating < CF_EASY_MAX:
        return Difficulty.easy
    if rating < CF_MEDIUM_MAX:
        return Difficulty.medium
    return Difficulty.hard


async def fetch_codeforces(http: aiohttp.ClientSession) -> list[dict[str, Any]]:
    base = settings.CF_API_BASE.rstrip("/")
    if not base.endswith("/problemset.problems"):
        base = f"{base}/problemset.problems"

    logger.info("Fetching Codeforces problems from %s", base)
    async with http.get(base, timeout=REQUEST_TIMEOUT) as resp:
        resp.raise_for_status()
        data = await resp.json(content_type=None)

    if data.get("status") != "OK":
        raise RuntimeError(f"Codeforces API Error: {data.get('comment')!r}")

    problems = data.get("result", {}).get("problems", [])
    logger.info("Codeforces returned %d problems", len(problems))

    normalized: list[dict[str, Any]] = []

    for p in problems:
        contest_id = p.get("contestId")
        index = p.get("index")
        if contest_id is None or index is None:
            continue

        title = (p.get("name") or "").strip()
        if not title:
            continue

        # ✅ FIX: CF API 'rating' field bhejta hai, 'points' nahi
        rating = p.get("rating")

        normalized.append({
            "source": Source.codeforces,
            "title": title[:500],
            # ✅ FIX: URL sahi path (extra /api/problems nahi)
            "url": f"https://codeforces.com/problemset/problem/{contest_id}/{index}"[:500],
            "difficulty": _cf_rating_to_difficulty(rating),
            "tags": p.get("tags") or [],
            "rating": rating,
            "external_id": f"codeforces_{contest_id}_{index}",
        })

    return normalized


# =========================================================
# 2. LeetCode (alfa-leetcode-api) — with pagination
# =========================================================
def _lc_difficulty(raw: str | None) -> Difficulty:
    val = (raw or "").strip().lower()
    if val == "easy":
        return Difficulty.easy
    if val == "hard":
        return Difficulty.hard
    # ✅ FIX: default MEDIUM (None/unknown ko hard nahi banana)
    return Difficulty.medium


async def fetch_leetcode(http: aiohttp.ClientSession) -> list[dict[str, Any]]:
    base = settings.LEETCODE_API_BASE.rstrip("/")
    if not base.endswith("/problems"):
        base = f"{base}/problems"

    # ✅ FIX: pagination loop — API max 100 deta hai per request
    all_items: list[dict[str, Any]] = []
    skip = 0

    while True:
        url = f"{base}?limit={LEETCODE_PAGE_SIZE}&skip={skip}"
        logger.info("Fetching LeetCode problems from %s", url)

        async with http.get(url, timeout=REQUEST_TIMEOUT) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)

        items = data.get("problemsetQuestionList") or []
        if not items:
            break

        all_items.extend(items)
        logger.info("LeetCode page skip=%d returned %d (total %d)",
                    skip, len(items), len(all_items))

        if len(items) < LEETCODE_PAGE_SIZE:
            break
        skip += LEETCODE_PAGE_SIZE

        # Safety guard
        if skip > 5000:
            logger.warning("LeetCode pagination hit safety cap at skip=%d", skip)
            break

    logger.info("LeetCode returned %d problems (all pages)", len(all_items))

    normalized: list[dict[str, Any]] = []
    skipped_paid = 0
    skipped_invalid = 0

    for q in all_items:
        if q.get("isPaidOnly") is True:
            skipped_paid += 1
            continue

        slug  = (q.get("titleSlug") or "").strip()
        title = (q.get("title") or "").strip()

        if not slug or not title:
            skipped_invalid += 1
            continue

        # ✅ FIX: 'q.get("name")' -> 't.get("name")' (bug tha)
        raw_tags = q.get("topicTags") or []
        tags = [
            t.get("name").strip()
            for t in raw_tags
            if isinstance(t, dict) and t.get("name")
        ]

        difficulty = _lc_difficulty(q.get("difficulty"))

        normalized.append({
            "source": Source.leetcode,
            "title": title[:500],
            "url": f"https://leetcode.com/problems/{slug}"[:500],
            "difficulty": difficulty,
            "tags": tags,
            "rating": None,
            "external_id": f"leetcode_{slug}",
        })

    logger.info(
        "LeetCode normalized: %d kept, %d paid-skipped, %d invalid-skipped",
        len(normalized), skipped_paid, skipped_invalid,
    )
    return normalized


# =========================================================
# 3. Upsert
# =========================================================
async def upsert_questions(
    db: AsyncSession,
    problems: list[dict[str, Any]],
) -> tuple[int, int]:
    if not problems:
        return 0, 0

    external_ids = [p["external_id"] for p in problems]

    result = await db.execute(
        select(Questions.external_id).where(Questions.external_id.in_(external_ids))
    )
    existing = {row[0] for row in result.all()}

    new_items      = [p for p in problems if p["external_id"] not in existing]
    existing_items = [p for p in problems if p["external_id"] in existing]

    if new_items:
        db.add_all([Questions(**item) for item in new_items])

    for item in existing_items:
        await db.execute(
            update(Questions)
            .where(Questions.external_id == item["external_id"])
            .values(
                title=item["title"],
                url=item["url"],
                difficulty=item["difficulty"],
                # ✅ FIX: 'tag' -> 'tags' (column ka naam tags hai)
                tags=item["tags"],
                rating=item["rating"],
            )
        )

    await db.commit()
    return len(new_items), len(existing_items)


# =========================================================
# 4. Top-level orchestrator
# =========================================================
async def sync_questions_pool() -> dict[str, Any]:
    summary: dict[str, Any] = {
        "cf_fetched": 0,
        "lc_fetched": 0,
        "inserted": 0,
        "updated": 0,
        "errors": [],
    }

    try:
        async with aiohttp.ClientSession() as http:
            cf_result, lc_result = await asyncio.gather(
                fetch_codeforces(http),
                fetch_leetcode(http),
                return_exceptions=True,
            )

        cf_problems: list[dict[str, Any]] = []
        lc_problems: list[dict[str, Any]] = []

        if isinstance(cf_result, Exception):
            msg = f"Codeforces fetch failed: {type(cf_result).__name__}: {cf_result}"
            logger.error(msg)
            summary["errors"].append(msg)
        else:
            cf_problems = cf_result
            summary["cf_fetched"] = len(cf_problems)

        if isinstance(lc_result, Exception):
            msg = f"LeetCode fetch failed: {type(lc_result).__name__}: {lc_result}"
            logger.error(msg)
            summary["errors"].append(msg)
        else:
            lc_problems = lc_result
            summary["lc_fetched"] = len(lc_problems)

        all_problems = cf_problems + lc_problems

        if all_problems:
            async with AsyncSessionLocal() as db:
                inserted, updated = await upsert_questions(db, all_problems)
            summary["inserted"] = inserted
            summary["updated"] = updated

    finally:
        # ✅ FIX: engine dispose — 'Event loop is closed' warning khatam
        await engine.dispose()

    return summary


# ---- Direct run (optional) ----
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    result = asyncio.run(sync_questions_pool())
    print("\n=== Sync Summary ===")
    print(f"Codeforces fetched : {result['cf_fetched']}")
    print(f"LeetCode fetched   : {result['lc_fetched']}")
    print(f"New inserted       : {result['inserted']}")
    print(f"Existing updated   : {result['updated']}")
    if result["errors"]:
        print("Errors:")
        for err in result["errors"]:
            print(f"  - {err}")