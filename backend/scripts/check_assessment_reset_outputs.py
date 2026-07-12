import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.flow_engine import FlowEngine


class FakeDb:
    def __init__(self):
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return FakeResult()


class FakeResult:
    def scalars(self):
        return self

    def all(self):
        return []


async def main():
    db = FakeDb()
    await FlowEngine(db)._clear_project_assessment_outputs(7)

    deleted_tables = [statement.table.name for statement in db.statements if getattr(statement, "is_delete", False)]
    assert deleted_tables == [
        "remediation_tickets",
        "evidences",
        "evidences",
        "evidences",
        "questionnaire_records",
        "findings",
        "project_assessments",
    ]
    print("assessment reset outputs check passed")


if __name__ == "__main__":
    asyncio.run(main())
