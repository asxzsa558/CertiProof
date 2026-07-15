import asyncio

from app.services.knowledge_graph import KnowledgeGraphService


def test_multi_block_graph_matches_previous_node_before_writing(monkeypatch):
    service = KnowledgeGraphService()
    queries = []

    async def capture(_db, query):
        queries.append(query)

    monkeypatch.setattr(service, "_cypher", capture)
    asyncio.run(service.sync_document_structure(
        None,
        project_id=1,
        assessment_id=2,
        phase_id=3,
        task_id=None,
        run_id=4,
        file_id=5,
        blocks=[
            {"id": 10, "ordinal": 0, "content_sha256": "a"},
            {"id": 11, "ordinal": 1, "content_sha256": "b"},
        ],
    ))

    second_block_query = queries[2]
    assert second_block_query.index('MATCH (previous:Block {uid: "block:10"})') < second_block_query.index("MERGE (b:Block")
    assert "MERGE (previous)-[:NEXT]->(b)" in second_block_query
