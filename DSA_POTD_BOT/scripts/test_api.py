import asyncio
import sys
import aiohttp

from groq import AsyncGroq
from config.settings import settings

CODEFORCES_URL = settings.CF_API_BASE
LEETCODE_URL = settings.LEETCODE_API_BASE
GROQ_API_KEY = settings.LLM_API_KEY
GROQ_MODEL = settings.LLM_MODEL

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)

def _pass(service: str, detail: str) -> None:
    print(f"[PASS] {service} — {detail}")


def _fail(service : str, reason: str) ->None:
    print(f"[Fail] {service}-{reason}")


# LEETCODE API TEST
# ---------- Check 2: LeetCode wrapper (alfa-leetcode-api) ----------
async def check_leetcode(session: aiohttp.ClientSession) -> bool:
    service = "LeetCode wrapper"

    if not LEETCODE_URL:
        _fail(service, "LEETCODE_API_URL not set in config/settings.py")
        return False

    # Base URL me /problems append karo agar already nahi hai
    url = LEETCODE_URL.rstrip("/")
    if not url.endswith("/problems"):
        url = f"{url}/problems?limit=10"

    try:
        async with session.get(url, timeout=REQUEST_TIMEOUT) as resp:
            if resp.status != 200:
                _fail(service, f"HTTP {resp.status} from {url}")
                return False

            try:
                data = await resp.json(content_type=None)
            except Exception:
                text = await resp.text()
                _fail(service, f"non-JSON response (first 100 chars: {text[:100]!r})")
                return False

        # alfa-leetcode-api ka actual key: problemsetQuestionList
        items = data.get("problemsetQuestionList") if isinstance(data, dict) else None

        if not items:
            _fail(
                service,
                f"no problems found; top-level keys={list(data)[:5] if isinstance(data, dict) else type(data).__name__}"
            )
            return False

        sample = items[0].get("title") if isinstance(items[0], dict) else "?"
        total = data.get("totalQuestions", len(items))
        _pass(service, f"got {len(items)}/{total} problems (sample: {sample})")
        return True

    except asyncio.TimeoutError:
        _fail(service, f"timed out hitting {url} (Render cold start? try again)")
        return False
    except aiohttp.ClientError as e:
        _fail(service, f"client error: {e}")
        return False
    except Exception as e:
        _fail(service, f"unexpected: {type(e).__name__}: {e}")
        return False

# CODEFORCES
async def check_codeforces(session: aiohttp.ClientSession) -> bool:
    service = "Codeforces API"

    url = CODEFORCES_URL.rstrip("/")
    if not url.endswith("/problemset.problems"):
        url = f"{url}/problemset.problems"

    try:
        async with session.get(url, timeout=REQUEST_TIMEOUT) as resp:
            if resp.status != 200:
                _fail(service, f"HTTP {resp.status} from {url}")
                return False

            try:
                data = await resp.json(content_type=None)
            except Exception:
                text = await resp.text()
                _fail(service, f"non-JSON response (first 100 chars: {text[:100]!r})")
                return False

        if data.get("status") != "OK":
            _fail(
                service,
                f"status={data.get('status')!r}, comment={data.get('comment')!r}"
            )
            return False

        problems = data.get("result", {}).get("problems", [])
        if not problems:
            _fail(service, "empty problems list")
            return False

        sample = problems[0].get("name") if isinstance(problems[0], dict) else "?"
        _pass(service, f"got {len(problems)} problems (sample: {sample})")
        return True

    except asyncio.TimeoutError:
        _fail(service, f"timed out hitting {url}")
        return False
    except aiohttp.ClientError as e:
        _fail(service, f"client error: {e}")
        return False
    except Exception as e:
        _fail(service, f"unexpected: {type(e).__name__}: {e}")
        return False



# MAIN
async def main() -> int:
    print("Running API health checks...\n")

    async with aiohttp.ClientSession() as session:
        cf_ok  = await check_codeforces(session)
        lc_ok  = await check_leetcode(session)
       # gr_ok  = await check_groq()

    results = [ lc_ok,cf_ok]
    passed  = sum(results)
    total   = len(results)

    print(f"\n{passed}/{total} checks passed.")
    return 0 if passed == total else 1