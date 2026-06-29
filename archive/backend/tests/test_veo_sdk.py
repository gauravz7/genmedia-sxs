import asyncio
from providers.vertex_provider import generate_with_veo
import os
import json

async def main():
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/Users/gauravz/.config/gcloud/application_default_credentials.json"
    res = await generate_with_veo("A cat playing piano", "veo-2.0-generate-001", "16:9", "t2v", None)
    print(res)

if __name__ == "__main__":
    asyncio.run(main())
