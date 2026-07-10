"""Generate one real project report and check the MVP report contract."""

import asyncio
import os

from app.core.database import AsyncSessionLocal
from app.services.report_service import generate_html_report


async def main():
    project_id = int(os.getenv("PROJECT_ID", "6"))
    async with AsyncSessionLocal() as db:
        html = await generate_html_report(db, project_id)

    required = ("资产范围", "问题清单", "文档差距", "技术检测记录", "整改时间线", "复测对比", "资产与端口变化")
    assert all(section in html for section in required)
    assert "<html" in html and "</html>" in html
    print(f"report contract ok: project={project_id}, bytes={len(html.encode())}")


if __name__ == "__main__":
    asyncio.run(main())
