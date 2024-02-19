from typing import Optional, List

from neo4j.exceptions import Neo4jError
from pydantic import BaseModel, Field
from cognitive_architecture.database.graphdb.graph import Neo4jGraphDB
from cognitive_architecture.database.relationaldb.models.memory import MemoryModel
import os
from cognitive_architecture.database.relationaldb.database_crud import (
    session_scope,
    update_entity_graph_summary,
)
from cognitive_architecture.database.relationaldb.database import AsyncSessionLocal
from cognitive_architecture.utils import generate_letter_uuid
import instructor
from openai import OpenAI
from cognitive_architecture.vectorstore_manager import Memory
from cognitive_architecture.database.relationaldb.database_crud import fetch_job_id
import uuid
from cognitive_architecture.database.relationaldb.models.sessions import Session
from cognitive_architecture.database.relationaldb.models.operation import Operation
from cognitive_architecture.database.relationaldb.database_crud import (
    session_scope,
    add_entity,
    update_entity,
    fetch_job_id,
)
from cognitive_architecture.database.relationaldb.models.metadatas import MetaDatas
from cognitive_architecture.database.relationaldb.models.docs import DocsModel
from cognitive_architecture.database.relationaldb.models.memory import MemoryModel
from cognitive_architecture.database.relationaldb.models.user import User
from cognitive_architecture.classifiers.classify_summary import classify_summary
from cognitive_architecture.classifiers.classify_documents import classify_documents
from cognitive_architecture.classifiers.classify_user_query import classify_user_query
from cognitive_architecture.classifiers.classify_user_input import classify_user_input

aclient = instructor.patch(OpenAI())
DEFAULT_PRESET = "promethai_chat"
preset_options = [DEFAULT_PRESET]
PROMETHAI_DIR = os.path.join(os.path.expanduser("~"), ".")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
from cognitive_architecture.config import Config

config = Config()
config.load()

from cognitive_architecture.utils import get_document_names
from sqlalchemy.orm import selectinload, joinedload, contains_eager
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from cognitive_architecture.utils import (
    get_document_names,
    generate_letter_uuid,
    get_memory_name_by_doc_id,
    get_unsumarized_vector_db_namespace,
    get_vectordb_namespace,
    get_vectordb_document_name,
)
from cognitive_architecture.shared.language_processing import (
    translate_text,
    detect_language,
)

async def fetch_document_vectordb_namespace(
    session: AsyncSession, user_id: str, namespace_id: str, doc_id: str = None
):
    logging.info("user id is", user_id)
    memory = await Memory.create_memory(
        user_id, session, namespace=namespace_id, memory_label=namespace_id
    )

    # Managing memory attributes
    existing_user = await Memory.check_existing_user(user_id, session)
    print("here is the existing user", existing_user)
    await memory.manage_memory_attributes(existing_user)
    print("Namespace id is %s", namespace_id)
    await memory.add_dynamic_memory_class(namespace_id.lower(), namespace_id)
    namespace_class = namespace_id + "_class"

    dynamic_memory_class = getattr(memory, namespace_class.lower(), None)

    methods_to_add = ["add_memories", "fetch_memories", "delete_memories"]

    if dynamic_memory_class is not None:
        for method_name in methods_to_add:
            await memory.add_method_to_class(dynamic_memory_class, method_name)
            print(f"Memory method {method_name} has been added")
    else:
        print(f"No attribute named  in memory.")

    print("Available memory classes:", await memory.list_memory_classes())
    result = await memory.dynamic_method_call(
        dynamic_memory_class,
        "fetch_memories",
        observation="placeholder",
        search_type="summary_filter_by_object_name",
        params=doc_id,
    )
    logging.info("Result is %s", str(result))

    return result, namespace_id


async def load_documents_to_vectorstore(
    session: AsyncSession,
    user_id: str,
    content: str = None,
    job_id: str = None,
    loader_settings: dict = None,
    memory_type: str = "PRIVATE",
):
    namespace_id = str(generate_letter_uuid()) + "_" + "SEMANTICMEMORY"
    namespace_class = namespace_id + "_class"

    logging.info("Namespace created with id %s", namespace_id)
    try:
        new_user = User(id=user_id)
        await add_entity(session, new_user)
    except:
        pass
    if job_id is None:
        job_id = str(uuid.uuid4())

    await add_entity(
        session,
        Operation(
            id=job_id,
            user_id=user_id,
            operation_status="RUNNING",
            operation_type="DATA_LOAD",
        ),
    )
    memory = await Memory.create_memory(
        user_id,
        session,
        namespace=namespace_id,
        job_id=job_id,
        memory_label=namespace_id,
    )
    if content is not None:
        document_names = [content[:30]]
    if loader_settings is not None:
        document_source = (
            loader_settings.get("document_names")
            if isinstance(loader_settings.get("document_names"), list)
            else loader_settings.get("path", "None")
        )
        logging.info("Document source is %s", document_source)
        # try:
        document_names = get_document_names(document_source[0])
        logging.info(str(document_names))
        # except:
        #     document_names = document_source
    for doc in document_names:
        from cognitive_architecture.shared.language_processing import (
            translate_text,
            detect_language,
        )

        # translates doc titles to english
        if loader_settings is not None:
            logging.info("Detecting language of document %s", doc)
            loader_settings["single_document_path"] = (
                loader_settings.get("path", "None")[0] + "/" + doc
            )
            logging.info(
                "Document path is %s",
                loader_settings.get("single_document_path", "None"),
            )
            memory_category = loader_settings.get("memory_category", "PUBLIC")
        if loader_settings is None:
            memory_category = "CUSTOM"
        if detect_language(doc) != "en":
            doc_ = doc.strip(".pdf").replace("-", " ")
            doc_ = translate_text(doc_, "sr", "en")
        else:
            doc_ = doc
        doc_id = str(uuid.uuid4())

        logging.info("Document name is %s", doc_)
        await add_entity(
            session,
            DocsModel(
                id=doc_id,
                operation_id=job_id,
                graph_summary=False,
                memory_category=memory_category,
                doc_name=doc_,
            ),
        )
        # Managing memory attributes
        existing_user = await Memory.check_existing_user(user_id, session)
        await memory.manage_memory_attributes(existing_user)
        params = {"doc_id": doc_id}
        print("Namespace id is %s", namespace_id)
        await memory.add_dynamic_memory_class(namespace_id.lower(), namespace_id)

        dynamic_memory_class = getattr(memory, namespace_class.lower(), None)

        methods_to_add = ["add_memories", "fetch_memories", "delete_memories"]

        if dynamic_memory_class is not None:
            for method_name in methods_to_add:
                await memory.add_method_to_class(dynamic_memory_class, method_name)
                print(f"Memory method {method_name} has been added")
        else:
            print(f"No attribute named  in memory.")

        print("Available memory classes:", await memory.list_memory_classes())
        result = await memory.dynamic_method_call(
            dynamic_memory_class,
            "add_memories",
            observation=content,
            params=params,
            loader_settings=loader_settings,
        )
        await update_entity(session, Operation, job_id, "SUCCESS")
        return 1


async def user_query_to_graph_db(session: AsyncSession, user_id: str, query_input: str):
    try:
        new_user = User(id=user_id)
        await add_entity(session, new_user)
    except:
        pass

    job_id = str(uuid.uuid4())

    await add_entity(
        session,
        Operation(
            id=job_id,
            user_id=user_id,
            operation_status="RUNNING",
            operation_type="USER_QUERY_TO_GRAPH_DB",
        ),
    )

    detected_language = detect_language(query_input)

    if detected_language != "en":
        translated_query = translate_text(query_input, detected_language, "en")
    else:
        translated_query = query_input

    neo4j_graph_db = Neo4jGraphDB(
        url=config.graph_database_url,
        username=config.graph_database_username,
        password=config.graph_database_password,
    )

    cypher_query = (
        await neo4j_graph_db.generate_cypher_query_for_user_prompt_decomposition(
            user_id, translated_query
        )
    )
    result = await neo4j_graph_db.query(cypher_query)

    await neo4j_graph_db.run_merge_query(
        user_id=user_id, memory_type="SemanticMemory", similarity_threshold=0.8
    )
    await neo4j_graph_db.run_merge_query(
        user_id=user_id, memory_type="EpisodicMemory", similarity_threshold=0.8
    )
    await neo4j_graph_db.close()

    await update_entity(session, Operation, job_id, "SUCCESS")

    return result



async def add_documents_to_graph_db(
    session: AsyncSession, user_id: str = None, document_memory_types: list = None
):
    """"""
    if document_memory_types is None:
        document_memory_types = ["PUBLIC"]

    logging.info("Document memory types are", document_memory_types)
    try:
        # await update_document_vectordb_namespace(postgres_session, user_id)
        memory_details, docs = await get_unsumarized_vector_db_namespace(
            session, user_id
        )

        logging.info("Docs are", docs)
        memory_details = [
            detail for detail in memory_details if detail[1] in document_memory_types
        ]
        logging.info("Memory details", memory_details)
        for doc in docs:
            logging.info("Memory names are", memory_details)
            doc_name, doc_id = doc
            logging.info("Doc id is", doc_id)
            try:
                classification_content = await fetch_document_vectordb_namespace(
                    session, user_id, memory_details[0][0], doc_id
                )
                retrieval_chunks = [
                    item["text"]
                    for item in classification_content[0]["data"]["Get"][
                        memory_details[0][0]
                    ]
                ]
                logging.info("Classification content is", classification_content)
            except:
                classification_content = ""
                retrieval_chunks = ""
            # retrieval_chunks = [item['text'] for item in classification_content[0]['data']['Get'][memory_details[0]]]
            # Concatenating the extracted text values
            concatenated_retrievals = " ".join(retrieval_chunks)
            print(concatenated_retrievals)
            logging.info("Retrieval chunks are", retrieval_chunks)
            classification = await classify_documents(
                doc_name, document_id=doc_id, content=concatenated_retrievals
            )

            logging.info("Classification is %s", str(classification))
            neo4j_graph_db = Neo4jGraphDB(
                url=config.graph_database_url,
                username=config.graph_database_username,
                password=config.graph_database_password,
            )
            if document_memory_types == ["PUBLIC"]:
                await create_public_memory(
                    user_id=user_id, labels=["sr"], topic="PublicMemory"
                )
                ids = await neo4j_graph_db.retrieve_node_id_for_memory_type(
                    topic="PublicMemory"
                )
                await neo4j_graph_db.close()
                print(ids)
            else:
                ids = await neo4j_graph_db.retrieve_node_id_for_memory_type(
                    topic="SemanticMemory"
                )
                await neo4j_graph_db.close()
                print(ids)

            for id in ids:
                print(id.get("memoryId"))
                neo4j_graph_db = Neo4jGraphDB(
                    url=config.graph_database_url,
                    username=config.graph_database_username,
                    password=config.graph_database_password,
                )
                if document_memory_types == ["PUBLIC"]:
                    rs = neo4j_graph_db.create_document_node_cypher(
                        classification, user_id, public_memory_id=id.get("memoryId")
                    )
                    await neo4j_graph_db.close()
                else:
                    rs = neo4j_graph_db.create_document_node_cypher(
                        classification, user_id, memory_type="SemanticMemory"
                    )
                    await neo4j_graph_db.close()
                logging.info("Cypher query is %s", str(rs))
                neo4j_graph_db = Neo4jGraphDB(
                    url=config.graph_database_url,
                    username=config.graph_database_username,
                    password=config.graph_database_password,
                )
                await neo4j_graph_db.query(rs)
                await neo4j_graph_db.close()
            logging.info("WE GOT HERE")
            neo4j_graph_db = Neo4jGraphDB(
                url=config.graph_database_url,
                username=config.graph_database_username,
                password=config.graph_database_password,
            )
            if memory_details[0][1] == "PUBLIC":
                await neo4j_graph_db.update_document_node_with_db_ids(
                    vectordb_namespace=memory_details[0][0], document_id=doc_id
                )
                await neo4j_graph_db.close()
            else:
                await neo4j_graph_db.update_document_node_with_db_ids(
                    vectordb_namespace=memory_details[0][0],
                    document_id=doc_id,
                    user_id=user_id,
                )
                await neo4j_graph_db.close()
            # await update_entity_graph_summary(session, DocsModel, doc_id, True)
    except Exception as e:
        return e


class ResponseString(BaseModel):
    response: str = Field(
        default=None
    )  # Defaulting to None or you can use a default string like ""
    quotation: str = Field(default=None)  # Same here


def generate_graph(input) -> ResponseString:
    out = aclient.chat.completions.create(
        model="gpt-4-1106-preview",
        messages=[
            {
                "role": "user",
                "content": f"""Use the given context to answer query and use help of associated context: {input}. """,
            },
            {
                "role": "system",
                "content": """You are a top-tier algorithm
                designed for using context summaries based on cognitive psychology to answer user queries, and provide a simple response. 
                Do not mention anything explicit about cognitive architecture, but use the context to answer the query. If you are using a document, reference document metadata field""",
            },
        ],
        response_model=ResponseString,
    )
    return out


async def user_context_enrichment(
    session,
    user_id: str,
    query: str,
    generative_response: bool = False,
    memory_type: str = None,
) -> str:
    """
    Asynchronously enriches the user context by integrating various memory systems and document classifications.

    This function uses cognitive architecture to access and manipulate different memory systems (semantic, episodic, and procedural) associated with a user.
     It fetches memory details from a Neo4j graph database, classifies document categories based on the user's query, and retrieves document IDs for relevant categories.
     The function also dynamically manages memory attributes and methods, extending the context with document store information to enrich the user's query response.

    Parameters:
    - session (AsyncSession): The database session for executing queries.
    - user_id (str): The unique identifier of the user.
    - query (str): The original query from the user.

    Returns:
    - str: The final enriched context after integrating various memory systems and document classifications.

    The function performs several key operations:
    1. Retrieves semantic and episodic memory details for the user from the Neo4j graph database.
    2. Logs and classifies document categories relevant to the user's query.
    3. Fetches document IDs from Neo4j and corresponding memory names from a PostgreSQL database.
    4. Dynamically manages memory attributes and methods, including the addition of methods like 'add_memories', 'fetch_memories', and 'delete_memories' to the memory class.
    5. Extends the context with document store information relevant to the user's query.
    6. Generates and logs the final result after processing and integrating all information.

    Raises:
    - Exception: Propagates any exceptions that occur during database operations or memory management.

    Example Usage:
    ```python
    enriched_context = await user_context_enrichment(session, "user123", "How does cognitive architecture work?")
    ```
    """
    neo4j_graph_db = Neo4jGraphDB(
        url=config.graph_database_url,
        username=config.graph_database_username,
        password=config.graph_database_password,
    )

    # await user_query_to_graph_db(session, user_id, query)

    semantic_mem = await neo4j_graph_db.retrieve_semantic_memory(user_id=user_id)
    await neo4j_graph_db.close()
    neo4j_graph_db = Neo4jGraphDB(
        url=config.graph_database_url,
        username=config.graph_database_username,
        password=config.graph_database_password,
    )
    episodic_mem = await neo4j_graph_db.retrieve_episodic_memory(user_id=user_id)
    logging.info("Episodic memory is %s", episodic_mem)
    await neo4j_graph_db.close()
    # public_mem = neo4j_graph_db.retrieve_public_memory(user_id=user_id)

    if detect_language(query) != "en":
        query = translate_text(query, "sr", "en")
    logging.info("Translated query is %s", str(query))

    if memory_type == "PublicMemory":
        neo4j_graph_db = Neo4jGraphDB(
            url=config.graph_database_url,
            username=config.graph_database_username,
            password=config.graph_database_password,
        )
        summaries = await neo4j_graph_db.get_memory_linked_document_summaries(
            user_id=user_id, memory_type=memory_type
        )
        await neo4j_graph_db.close()
        logging.info("Summaries are  is %s", summaries)
        # logging.info("Context from graphdb is %s", context)
        # result = neo4j_graph_db.query(document_categories_query)
        # summaries = [record.get("summary") for record in result]
        # logging.info('Possible document categories are', str(result))
        # logging.info('Possible document categories are', str(categories))

        max_attempts = 3
        relevant_summary_id = None

        for _ in range(max_attempts):
            relevant_summary_id = await classify_summary(
                query=query, document_summaries=str(summaries)
            )

            logging.info("Relevant summary id is %s", relevant_summary_id)

            if relevant_summary_id is not None:
                break

        # logging.info("Relevant categories after the classifier are %s", relevant_categories)
        neo4j_graph_db = Neo4jGraphDB(
            url=config.graph_database_url,
            username=config.graph_database_username,
            password=config.graph_database_password,
        )
        postgres_id = await neo4j_graph_db.get_memory_linked_document_ids(
            user_id, summary_id=relevant_summary_id, memory_type=memory_type
        )
        await neo4j_graph_db.close()
        # postgres_id  = neo4j_graph_db.query(get_doc_ids)
        logging.info("Postgres ids are %s", postgres_id)
        namespace_id = await get_memory_name_by_doc_id(session, postgres_id[0])
        logging.info("Namespace ids are %s", namespace_id)
        params = {"doc_id": postgres_id[0]}
        namespace_id = namespace_id[0]
        namespace_class = namespace_id + "_class"
        if memory_type == "PublicMemory":
            user_id = "system_user"

        memory = await Memory.create_memory(
            user_id,
            session,
            namespace=namespace_id,
            job_id="23232",
            memory_label=namespace_id,
        )

        existing_user = await Memory.check_existing_user(user_id, session)
        print("here is the existing user", existing_user)
        await memory.manage_memory_attributes(existing_user)

        print("Namespace id is %s", namespace_id)
        await memory.add_dynamic_memory_class(namespace_id.lower(), namespace_id)

        dynamic_memory_class = getattr(memory, namespace_class.lower(), None)

        methods_to_add = ["add_memories", "fetch_memories", "delete_memories"]

        if dynamic_memory_class is not None:
            for method_name in methods_to_add:
                await memory.add_method_to_class(dynamic_memory_class, method_name)
                print(f"Memory method {method_name} has been added")
        else:
            print(f"No attribute named  in memory.")

        print("Available memory classes:", await memory.list_memory_classes())
        results = await memory.dynamic_method_call(
            dynamic_memory_class,
            "fetch_memories",
            observation=query,
            params=postgres_id[0],
            search_type="summary_filter_by_object_name",
        )
        logging.info("Result is %s", str(results))

        search_context = ""

        for result in results["data"]["Get"][namespace_id]:
            # Assuming 'result' is a dictionary and has keys like 'source', 'text'
            source = (
                result["source"]
                .replace("-", " ")
                .replace(".pdf", "")
                .replace(".data/", "")
            )
            text = result["text"]
            search_context += f"Document source: {source}, Document text: {text} \n"

    else:
        search_context = "No relevant documents found"

    context = f""" You are a memory system that uses cognitive architecture to enrich the 
    LLM context and provide better query response.
    You have access to the following information:
    EPISODIC MEMORY: {episodic_mem}
    SEMANTIC MEMORY: {semantic_mem}
    PROCEDURAL MEMORY: NULL
    SEARCH CONTEXT: The following documents provided with sources they were 
    extracted from could be used to provide an answer {search_context}
    The original user query: {query}
    """
    if generative_response is not True:
        return context
    else:
        generative_result = generate_graph(context)
        logging.info("Generative result is %s", generative_result.model_dump_json())
        return generative_result.model_dump_json()


async def create_public_memory(
    user_id: str = None, labels: list = None, topic: str = None
) -> Optional[int]:
    """
    Create a public memory node associated with a user in a Neo4j graph database.
    If Public Memory exists, it will return the id of the memory.
    This is intended as standalone node that can be attached to any user.
    It is not attached to any user by default.

    Args:
        user_id (str): The unique identifier for the user.
        session (AsyncSession): An asynchronous session for database operations.

    Returns:
        Optional[int]: The ID of the created public memory node or None if an error occurs.
        :param labels: Label for the memory, to help filter for different countries
        :param topic: Topic for the memory, to help provide a name

    """
    # Validate input parameters
    if not labels:
        labels = ["sr"]  # Labels for the memory node

    if not topic:
        topic = "PublicMemory"

    try:
        neo4j_graph_db = Neo4jGraphDB(
            url=config.graph_database_url,
            username=config.graph_database_username,
            password=config.graph_database_password,
        )

        # Assuming the topic for public memory is predefined, e.g., "PublicMemory"
        # Create the memory node
        memory_id = await neo4j_graph_db.create_memory_node(labels=labels, topic=topic)
        await neo4j_graph_db.close()
        return memory_id
    except Neo4jError as e:
        logging.error(f"Error creating public memory node: {e}")
        return None


async def attach_user_to_memory(
    user_id: str = None, labels: list = None, topic: str = None
) -> Optional[int]:
    """
    Link user to public memory

    Args:
        user_id (str): The unique identifier for the user.
        topic (str): Memory name


    Returns:
        Optional[int]: The ID of the created public memory node or None if an error occurs.
        :param labels: Label for the memory, to help filter for different countries
        :param topic: Topic for the memory, to help provide a name

    """
    # Validate input parameters
    if not user_id:
        raise ValueError("User ID is required.")
    if not labels:
        labels = ["sr"]  # Labels for the memory node

    if not topic:
        topic = "PublicMemory"

    try:
        neo4j_graph_db = Neo4jGraphDB(
            url=config.graph_database_url,
            username=config.graph_database_username,
            password=config.graph_database_password,
        )

        # Assuming the topic for public memory is predefined, e.g., "PublicMemory"
        ids = await neo4j_graph_db.retrieve_node_id_for_memory_type(topic=topic)
        await neo4j_graph_db.close()

        for id in ids:
            neo4j_graph_db = Neo4jGraphDB(
                url=config.graph_database_url,
                username=config.graph_database_username,
                password=config.graph_database_password,
            )
            linked_memory = await neo4j_graph_db.link_public_memory_to_user(
                memory_id=id.get("memoryId"), user_id=user_id
            )
            await neo4j_graph_db.close()
        return 1
    except Neo4jError as e:
        logging.error(f"Error creating public memory node: {e}")
        return None


async def unlink_user_from_memory(
    user_id: str = None, labels: list = None, topic: str = None
) -> Optional[int]:
    """
    Unlink user from memory

    Args:
        user_id (str): The unique identifier for the user.
        topic (str): Memory name

    Returns:
        Optional[int]: The ID of the created public memory node or None if an error occurs.
        :param labels: Label for the memory, to help filter for different countries
        :param topic: Topic for the memory, to help provide a name

    """
    # Validate input parameters
    if not user_id:
        raise ValueError("User ID is required.")
    if not labels:
        labels = ["sr"]  # Labels for the memory node

    if not topic:
        topic = "PublicMemory"

    try:
        neo4j_graph_db = Neo4jGraphDB(
            url=config.graph_database_url,
            username=config.graph_database_username,
            password=config.graph_database_password,
        )

        # Assuming the topic for public memory is predefined, e.g., "PublicMemory"
        ids = await neo4j_graph_db.retrieve_node_id_for_memory_type(topic=topic)
        await neo4j_graph_db.close()

        for id in ids:
            neo4j_graph_db = Neo4jGraphDB(
                url=config.graph_database_url,
                username=config.graph_database_username,
                password=config.graph_database_password,
            )
            linked_memory = neo4j_graph_db.unlink_memory_from_user(
                memory_id=id.get("memoryId"), user_id=user_id
            )
            await neo4j_graph_db.close()
        return 1
    except Neo4jError as e:
        logging.error(f"Error creating public memory node: {e}")
        return None


async def relevance_feedback(query: str, input_type: str):
    max_attempts = 6
    result = None
    for attempt in range(1, max_attempts + 1):
        result = await classify_user_input(query, input_type=input_type)
        if isinstance(result, bool):
            break  # Exit the loop if a result of type bool is obtained
    return result


async def main():
    user_id = "user_test_1_1"

    async with session_scope(AsyncSessionLocal()) as session:
        # await update_entity(session, DocsModel, "8cd9a022-5a7a-4af5-815a-f988415536ae", True)
        # output = await get_unsumarized_vector_db_namespace(session, user_id)

        class GraphQLQuery(BaseModel):
            query: str

        # gg = await user_query_to_graph_db(session, user_id, "How does cognitive architecture work?")
        # print(gg)

        # def cypher_statement_correcting( input: str) -> str:
        #     out = aclient.chat.completions.create(
        #         model=config.model,
        #         temperature=0,
        #         max_tokens=2000,
        #         messages=[
        #             {
        #                 "role": "user",
        #                 "content": f"""Check the cypher query for syntax issues, and fix any if found and return it as is: {input}. """,
        #
        #             },
        #             {"role": "system", "content": """You are a top-tier algorithm
        #                 designed for checking cypher queries for neo4j graph databases. You have to return input provided to you as is."""}
        #         ],
        #         response_model=GraphQLQuery,
        #     )
        #     return out
        #
        #
        # query= """WITH person1_4f21b68c73e24d0497e1010eb747b892, location2_dc0c68a9651142d38b6e117bfdc5c227, object3_4c7ba47babd24be1b35c30c42c87a3e9, product4_c984d5f9695f48ee9a43f58f57cc6740, location5_5e43f4c45b3c44ea897c12220db4c051, object6_5cdb87ad488c450c9dbce07b7daf3d8d, information7_f756e3f3720c4fe5aeb01287badaf088, event8_da6334e744454264900296319e14b532, action9_48e45419604e4d66b3e718ee1d6c095f, action10_f48acb1db4da4934afbe17363e9e63a4, user , semantic, episodic, buffer
        # CREATE (person1_4f21b68c73e24d0497e1010eb747b892)-[:EXPERIENCED]->(event8_da6334e744454264900296319e14b532)
        # CREATE (person1_4f21b68c73e24d0497e1010eb747b892)-[:HAS]->(object3_4c7ba47babd24be1b35c30c42c87a3e9)
        # CREATE (object3_4c7ba47babd24be1b35c30c42c87a3e9)-[:INCLUDES]->(product4_c984d5f9695f48ee9a43f58f57cc6740)
        # CREATE (product4_c984d5f9695f48ee9a43f58f57cc6740)-[:TO_BE_PURCHASED_AT]->(location5_5e43f4c45b3c44ea897c12220db4c051)
        # CREATE (person1_4f21b68c73e24d0497e1010eb747b892)-[:INTENDS_TO_PERFORM]->(action9_48e45419604e4d66b3e718ee1d6c095f)
        # CREATE (object6_5cdb87ad488c450c9dbce07b7daf3d8d)-[:A_CLASSICAL_BOOK_TO_BE_SUMMARIZED]->(information7_f756e3f3720c4fe5aeb01287badaf088)
        # CREATE (person1_4f21b68c73e24d0497e1010eb747b892)-[:NEEDS_TO_COMPLETE]->(action10_f48acb1db4da4934afbe17363e9e63a4)
        # WITH person1_4f21b68c73e24d0497e1010eb747b892, location2_dc0c68a9651142d38b6e117bfdc5c227, object3_4c7ba47babd24be1b35c30c42c87a3e9, product4_c984d5f9695f48ee9a43f58f57cc6740, location5_5e43f4c45b3c44ea897c12220db4c051, object6_5cdb87ad488c450c9dbce07b7daf3d8d, information7_f756e3f3720c4fe5aeb01287badaf088, event8_da6334e744454264900296319e14b532, action9_48e45419604e4d66b3e718ee1d6c095f, action10_f48acb1db4da4934afbe17363e9e63a4, user, semantic, episodic, buffer
        # CREATE (episodic)-[:HAS_EVENT]->(person1_4f21b68c73e24d0497e1010eb747b892)
        # CREATE (buffer)-[:CURRENTLY_HOLDING]->(person1_4f21b68c73e24d0497e1010eb747b892)
        # CREATE (episodic)-[:HAS_EVENT]->(location2_dc0c68a9651142d38b6e117bfdc5c227)
        # CREATE (buffer)-[:CURRENTLY_HOLDING]->(location2_dc0c68a9651142d38b6e117bfdc5c227)
        # CREATE (episodic)-[:HAS_EVENT]->(object3_4c7ba47babd24be1b35c30c42c87a3e9)
        # CREATE (buffer)-[:CURRENTLY_HOLDING]->(object3_4c7ba47babd24be1b35c30c42c87a3e9)
        # CREATE (episodic)-[:HAS_EVENT]->(product4_c984d5f9695f48ee9a43f58f57cc6740)
        # CREATE (buffer)-[:CURRENTLY_HOLDING]->(product4_c984d5f9695f48ee9a43f58f57cc6740)
        # CREATE (episodic)-[:HAS_EVENT]->(location5_5e43f4c45b3c44ea897c12220db4c051)
        # CREATE (buffer)-[:CURRENTLY_HOLDING]->(location5_5e43f4c45b3c44ea897c12220db4c051)
        # CREATE (episodic)-[:HAS_EVENT]->(object6_5cdb87ad488c450c9dbce07b7daf3d8d)
        # CREATE (buffer)-[:CURRENTLY_HOLDING]->(object6_5cdb87ad488c450c9dbce07b7daf3d8d)
        # CREATE (episodic)-[:HAS_EVENT]->(information7_f756e3f3720c4fe5aeb01287badaf088)
        # CREATE (buffer)-[:CURRENTLY_HOLDING]->(information7_f756e3f3720c4fe5aeb01287badaf088)
        # CREATE (episodic)-[:HAS_EVENT]->(event8_da6334e744454264900296319e14b532)
        # CREATE (buffer)-[:CURRENTLY_HOLDING]->(event8_da6334e744454264900296319e14b532)
        # CREATE (episodic)-[:HAS_EVENT]->(action9_48e45419604e4d66b3e718ee1d6c095f)
        # CREATE (buffer)-[:CURRENTLY_HOLDING]->(action9_48e45419604e4d66b3e718ee1d6c095f)
        # CREATE (episodic)-[:HAS_EVENT]->(action10_f48acb1db4da4934afbe17363e9e63a4)
        # CREATE (buffer)-[:CURRENTLY_HOLDING]->(action10_f48acb1db4da4934afbe17363e9e63a4)"""
        #
        # out = cypher_statement_correcting(query)
        # print(out)
        #
        # out = await user_query_to_graph_db(session, user_id, "I walked in the forest yesterday and added to my list I need to buy some milk in the store and get a summary from a classical book i read yesterday")
        # print(out)
        # load_doc_to_graph = await add_documents_to_graph_db(session, user_id)
        # print(load_doc_to_graph)
        # user_id = "test_user"
        # loader_settings = {
        #     "format": "PDF",
        #     "source": "DEVICE",
        #     "path": [".data"]
        # }
        # await load_documents_to_vectorstore(session, user_id, loader_settings=loader_settings)
        # await create_public_memory(user_id=user_id, labels=['sr'], topic="PublicMemory")
        # await add_documents_to_graph_db(session, user_id)
        #
        # neo4j_graph_db = Neo4jGraphDB(
        #     url=config.graph_database_url,
        #     username=config.graph_database_username,
        #     password=config.graph_database_password,
        # )
        #
        # out = neo4j_graph_db.run_merge_query(
        #     user_id=user_id, memory_type="SemanticMemory", similarity_threshold=0.5
        # )
        # bb = neo4j_graph_db.query(out)
        # print(bb)

        # await attach_user_to_memory(user_id=user_id, labels=['sr'], topic="PublicMemory")
        user_id = "test_user"
        return_ = await user_context_enrichment(user_id=user_id, query="I need to understand what did I do yesterday?", session=session, memory_type="SemanticMemory", generative_response=True)
        print(return_)
        # aa = await relevance_feedback("I need to understand what did I do yesterday", "PublicMemory")
        # print(aa)

        # document_summary = {
        #     'DocumentCategory': 'Science',
        #     'Title': 'The Future of AI',
        #     'Summary': 'An insightful article about the advancements in AI.',
        #     'd_id': 'doc123'
        # }
        #
        # # Example user ID
        # user_id = 'user'
        #
        # # value = await neo4j_graph_db.create_memory_node(labels=['sr'])
        # # print(value)
        # # neo4j_graph_db.close()
        #
        # await add_documents_to_graph_db(session, user_id)
        # neo4j_graph_db.link_public_memory_to_user(memory_id = 17,user_id=user_id)
        #
        # ids = neo4j_graph_db.retrieve_node_id_for_memory_type(topic="Document")
        # print(ids)
        #
        # for id in ids:
        #     print(id.get('memoryId'))
        #
        #     neo4j_graph_db.delete_memory_node(memory_id = id.get('memoryId'), topic="Document")
        #
        # neo4j_graph_db.delete_memory_node(memory_id=16, topic="PublicSerbianArchitecture")
        # neo4j_graph_db.unlink_memory_from_user(memory_id = 17,user_id=user_id)
        # cypher_query_public = neo4j_graph_db.create_document_node_cypher(document_summary, user_id, memory_type="PUBLIC")
        # neo4j_graph_db.query(cypher_query_public)
        # link_memory_to_user(user_id, session)

        # neo4j_graph_db.create_memory_node(labels=['sr'])
        # out = await get_vectordb_namespace(session, user_id)
        # params = {
        #     "version": "1.0",
        #     "agreement_id": "AG123456",
        #     "privacy_policy": "https://example.com/privacy",
        #     "terms_of_service": "https://example.com/terms",
        #     "format": "json",
        #     "schema_version": "1.1",
        #     "checksum": "a1b2c3d4e5f6",
        #     "owner": "John Doe",
        #     "license": "MIT",
        #     "validity_start": "2023-08-01",
        #     "validity_end": "2024-07-31",
        # }
        # loader_settings = {
        #     "format": "PDF",
        #     "source": "DEVICE",
        #     "path": [".data"],
        #     "strategy": "SUMMARY",
        # }
        # await load_documents_to_vectorstore(session, user_id, loader_settings=loader_settings)
        # await user_query_to_graph_db(session, user_id, "I walked in the forest yesterday and added to my list I need to buy some milk in the store and get a summary from a classical book i read yesterday")
        # await add_documents_to_graph_db(session, user_id, loader_settings=loader_settings)
        # await user_context_enrichment(session, user_id, query="Tell me about the book I read yesterday")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())