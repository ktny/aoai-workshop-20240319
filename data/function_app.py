import azure.functions as func
import logging
from langchain_community.document_loaders import UnstructuredMarkdownLoader
from azure.cosmos import CosmosClient
import os
import hashlib

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
cosmos_client = CosmosClient.from_connection_string(os.environ["CosmosKey"])


@app.route(route="upload_data")
def upload_data(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')
    container = cosmos_client.get_database_client("aoai").get_container_client("azure")

    markdown_path = "./data/aggregate.mdx"
    loader = UnstructuredMarkdownLoader(markdown_path)
    data = loader.load()
    logging.info(data[0].page_content)
    filename = os.path.basename(markdown_path)

    document = {
        "id": hashlib.md5(filename.encode()).hexdigest(),
        "content": data[0].page_content,
        "filename": filename
    }
    container.upsert_item(document)

    return func.HttpResponse(
            "This HTTP triggered function executed successfully. Pass a name in the query string or in the request body for a personalized response.",
            status_code=200
    )