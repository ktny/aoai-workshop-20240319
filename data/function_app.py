import hashlib
import json
import logging
import os

import azure.functions as func
from azure.core.credentials import AzureKeyCredential
from azure.cosmos import CosmosClient
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from langchain_community.document_loaders import UnstructuredMarkdownLoader
from openai import AzureOpenAI

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
cosmos_client = CosmosClient.from_connection_string(os.environ["CosmosKey"])
search_client = SearchClient(os.environ["SearchEndpoint"], "data", AzureKeyCredential(os.environ["SearchKey"]))
aoai_client = AzureOpenAI(azure_endpoint=os.environ["AoaiEndpoint"], api_key=os.environ["AoaiKey"], api_version="2024-02-15-preview")


@app.route(route="upload_data")
def upload_data(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Python HTTP trigger function processed a request.")
    container = cosmos_client.get_database_client("aoai").get_container_client("azure")

    markdown_path = "./data/cki-reference.mdx"
    loader = UnstructuredMarkdownLoader(markdown_path)
    data = loader.load()
    logging.info(data[0].page_content)
    filename = os.path.basename(markdown_path)

    document = {"id": hashlib.md5(filename.encode()).hexdigest(), "content": data[0].page_content, "filename": filename}
    container.upsert_item(document)

    return func.HttpResponse(
        "This HTTP triggered function executed successfully. Pass a name in the query string or in the request body for a personalized response.",
        status_code=200,
    )


@app.cosmos_db_trigger(arg_name="items", container_name="azure", database_name="aoai", connection="CosmosKey", feed_poll_delay=5000)
def cosmosdb_trigger(items: func.DocumentList):
    logging.info(items[0]["id"])

    documents = []

    for item in items:
        content = item["content"]
        content_vector = aoai_client.embeddings.create(input=content, model="text-embedding-ada-002").data[0].embedding

        documents.append(
            {
                "id": item["id"],
                "content": content,
                "content_vector": content_vector,
                "filename": item["filename"],
            }
        )

    search_client.merge_or_upload_documents(documents)


@app.route(route="chat", auth_level=func.AuthLevel.FUNCTION)
def chat(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Python HTTP trigger function processed a request.")

    query = req.params.get("query")
    query_vector = aoai_client.embeddings.create(input=query, model="text-embedding-ada-002").data[0].embedding

    vector = VectorizedQuery(vector=query_vector, k_nearest_neighbors=3, fields="content_vector")

    search_results = search_client.search(search_text="", vector_queries=[vector], select=["id", "filename", "content"])

    documents = []

    for search_result in search_results:
        # logging.info(search_result["content"])
        documents.append(
            {
                "id": search_result["id"],
                "content": search_result["content"],
                "filename": search_result["filename"],
            }
        )

    system_prompt = f"""
### instructions
あなたはKIというシステムのマニュアルを熟知したアシスタントです。
contentの内容のみを参照して質問に回答してください。

### content
{json.dumps(documents, ensure_ascii=False)}

    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query},
    ]

    llm_responce = aoai_client.chat.completions.create(model="gpt-4", messages=messages)
    answer = llm_responce.choices[0].message.content

    logging.info(answer)

    return func.HttpResponse(answer, status_code=200)
