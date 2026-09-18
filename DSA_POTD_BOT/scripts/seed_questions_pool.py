import asyncio
import logging
import sys,os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


from services.question_pool import sync_questions_pool

async def main() ->int :
    summary = await sync_questions_pool()

    print("\n======Question Pool Summary======")
    print(f" Codeforces fetched :{summary['cf_fetched']}")
    print(f" Leetcode fetched : {summary['lc_fetched']}")
    print(f" New inserted : {summary['inserted']}")
    print(f" Existing Updated : {summary['updated']}")

    if summary["errors"]:
        print("\nErrors")
        for err in summary['errors']:
            print(f"   -{err}")
        return 1
    print("Done")
    return 0

if __name__=="__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    sys.exit(asyncio.run(main()))