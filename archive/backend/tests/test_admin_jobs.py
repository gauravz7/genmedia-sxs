import asyncio
from main import get_admin_jobs

async def run():
    try:
        res = await get_admin_jobs()
        print("Success:", len(res))
    except Exception as e:
        import traceback
        traceback.print_exc()

asyncio.run(run())
