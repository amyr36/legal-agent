from pathlib import Path

import chromadb


class VectorStoreService:

    def __init__(
        self,
        persist_directory: str = "storage/chroma",
        collection_name: str = "legal_documents",
    ):
        Path(persist_directory).mkdir(
            parents=True,
            exist_ok=True,
        )

        self.client = chromadb.PersistentClient(
            path=persist_directory
        )

        self.collection = self.client.get_or_create_collection(
            name=collection_name,
        )

    def add_documents(
        self,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> None:

        self.collection.add(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
    ):
        return self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
        )

    def delete_document(
        self,
        document_id: int,
    ) -> None:

        self.collection.delete(
            where={
                "document_id": document_id
            }
        )