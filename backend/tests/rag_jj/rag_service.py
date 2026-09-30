from app.services.rag.retrieval_service import RetrievalService


class RAGService:

    def __init__(
        self,
        retrieval_service: RetrievalService,
    ):
        self.retrieval_service = retrieval_service

    def retrieve_context(
        self,
        query: str,
        top_k: int = 5,
    ):
        return self.retrieval_service.retrieve(
            query=query,
            top_k=top_k,
        )