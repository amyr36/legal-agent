from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from api.routes import analyses
from core.config import settings

app = FastAPI()


class AnalyzeRequest(BaseModel):
    document_a: Optional[List[Dict[str, Any]]]
    document_b: Optional[List[Dict[str, Any]]]
    rebuild: bool = Field(default=False, description="rebuild Chunks and VectorDatabase")


class AnalyzeResponse(BaseModel):
    count: int
    relations: List[Dict[str, Any]]


app.include_router(analyses.router)


@app.get("/")
def health() -> Dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
