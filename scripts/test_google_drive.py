import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from backend.app.services.google_drive_client import GoogleDriveClient


DOCUMENT_ID = "1M_wTECzM0G-3nxxsAG0UXXb5VMVLpk2Vtg7Scvu_vSc"


async def main():
    load_dotenv()

    client = GoogleDriveClient(
        os.getenv("GOOGLE_DRIVE_CLIENT_ID", ""),
        os.getenv("GOOGLE_DRIVE_CLIENT_SECRET", ""),
        os.getenv("GOOGLE_DRIVE_REFRESH_TOKEN", ""),
    )

    try:
        data = await client.export_docx(DOCUMENT_ID)

        print("Google Drive PDP: OK")
        print(f"Bytes recibidos: {len(data)}")
    finally:
        await client.close()


asyncio.run(main())
