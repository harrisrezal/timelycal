from fastapi import APIRouter
from pydantic import BaseModel
from services.rag import query as rag_query

router = APIRouter()


class QueryRequest(BaseModel):
    question: str


@router.post("/query")
async def query(request: QueryRequest):
    answer = rag_query(request.question)
    return {"question": request.question, "answer": answer}
