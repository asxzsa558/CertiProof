"""Generate one real project report and check the MVP report contract."""

import asyncio
import os

from app.core.database import AsyncSessionLocal
from app.services.report_service import generate_html_report


async def main():
    project_id = int(os.getenv("PROJECT_ID", "6"))
    async with AsyncSessionLocal() as db:
        html = await generate_html_report(db, project_id)

    required = (
        "自查结论",
        "当前待整改事项",
        "复测验证",
        "检测覆盖与执行结果",
        "执行状态",
        "检测结论",
        "文档合规核查",
        "问题闭环明细",
        "测评范围与变更",
    )
    assert all(section in html for section in required)
    assert "<html" in html and "</html>" in html
    print(f"report contract ok: project={project_id}, bytes={len(html.encode())}")


if __name__ == "__main__":
    asyncio.run(main())
