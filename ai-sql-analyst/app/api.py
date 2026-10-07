"""REST API.   uvicorn app.api:app --reload    ->   POST /ask {"question": "..."}"""
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlanalyst.agent import STRATEGIES, SQLAgent  # noqa: E402
from sqlanalyst.db import Database  # noqa: E402
from sqlanalyst.llm import AnthropicLLM  # noqa: E402

app = FastAPI(title="AI SQL Analyst", version="1.0.0")
_db = Database()
_agents: dict[str, SQLAgent] = {}


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    strategy: str = "full"
    max_rows: int = Field(default=200, le=1000)


class AskResponse(BaseModel):
    sql: str | None
    columns: list[str]
    rows: list[list]
    attempts: int
    chart: dict | None
    latency_s: float
    cost_usd: float


@app.get("/health")
def health():
    return {"status": "ok", "dialect": _db.dialect}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    if req.strategy not in STRATEGIES:
        raise HTTPException(400, f"strategy must be one of {list(STRATEGIES)}")
    agent = _agents.setdefault(req.strategy, SQLAgent(AnthropicLLM(), _db, strategy=req.strategy))
    ans = agent.ask(req.question)
    if not ans.ok:
        raise HTTPException(422, ans.error)
    data = ans.data.head(req.max_rows)
    return AskResponse(sql=ans.sql, columns=list(data.columns),
                       rows=data.astype(object).where(data.notna(), None).values.tolist(),
                       attempts=len(ans.attempts), chart=ans.chart,
                       latency_s=round(ans.latency_s, 2), cost_usd=ans.cost_usd)
