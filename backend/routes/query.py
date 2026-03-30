from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from services.rag import query as rag_query

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


class QueryRequest(BaseModel):
    question: str = Field(..., max_length=2000)


@router.post("/query")
@limiter.limit("20/minute")
async def query(request: Request, body: QueryRequest):
    answer = rag_query(body.question)
    return {"question": body.question, "answer": answer}
