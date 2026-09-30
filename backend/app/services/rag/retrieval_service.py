from app.services.rag.embedding_service import EmbeddingService
from app.services.rag.vectore_store_service import VectorStoreService


class RetrievalService:

    def __init__(
        self,
        embedding_service: EmbeddingService,
        vector_store_service: VectorStoreService,
    ):
        self.embedding_service = embedding_service
        self.vector_store_service = vector_store_service

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
    ):

        query_embedding = (
            self.embedding_service.embed_query(query)
        )

        results = self.vector_store_service.search(
            query_embedding=query_embedding,
            top_k=top_k,
        )

        return results