from cognee.infrastructure.databases.vector import get_vector_engine
from cognee.infrastructure.databases.graph.get_graph_engine import get_graph_engine
from cognee.infrastructure.databases.relational import get_relationaldb_config

async def prune_system(graph = True, vector = True, metadata = False):
    if graph:
        graph_engine = await get_graph_engine()
        await graph_engine.delete_graph()

    if vector:
        vector_engine = get_vector_engine()
        await vector_engine.prune()

    if metadata:
        db_config = get_relationaldb_config()
        db_engine = db_config.database_engine
        db_engine.delete_database()
