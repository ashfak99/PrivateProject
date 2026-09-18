import asyncio

from db.base import Base
from db.session import engine

from db.model import User, Questions, User_Question_Log, Daily_Question_Log, Payment

async def init_db() -> None:

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await engine.dispose()

    print("Table is created successfully")


# if __name__=="__main__":
#     asyncio.run(init_db())