"""Local REST service for researchers and simulated clients."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from qianji_data_mini.db import Database
from qianji_data_mini.ingest import ingest_daily


class IngestRequest(BaseModel):
    source: str = Field(pattern="^(mock|tushare|wind|choice|ifind)$")
    symbols: list[str]
    start_date: date
    end_date: date


def verify_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.getenv("QIANJI_API_KEY", "").strip()
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid X-API-Key")


def create_app(database_path: str | Path | None = None) -> FastAPI:
    app = FastAPI(title="Qianji Data Mini API", version="0.1.0")
    database = Database(database_path)

    @app.get("/health")
    def health():
        return {"status": "ok", "database": str(database.path)}

    @app.get("/sources", dependencies=[Depends(verify_api_key)])
    def sources():
        return database.source_status().to_dict(orient="records")

    @app.post("/ingest/daily", dependencies=[Depends(verify_api_key)])
    def ingest(request: IngestRequest):
        return ingest_daily(
            source=request.source,
            symbols=request.symbols,
            start_date=request.start_date,
            end_date=request.end_date,
            database_path=database.path,
        ).model_dump(mode="json")

    @app.get("/v1/equity/price/historical", dependencies=[Depends(verify_api_key)])
    def historical(
        symbol: str,
        start_date: date | None = None,
        end_date: date | None = None,
        source: str = Query(default="auto", pattern="^(auto|mock|tushare|wind|choice|ifind)$"),
        adjustment: str = "unadjusted",
    ):
        rows = database.query_daily(
            symbol=symbol, start_date=start_date, end_date=end_date,
            source=source, adjustment=adjustment,
        )
        return {"results": rows, "provider": "qianji", "source": source, "count": len(rows)}

    return app


app = create_app()


def run() -> None:
    import uvicorn
    uvicorn.run(
        "qianji_data_mini.service:app",
        host=os.getenv("QIANJI_API_HOST", "127.0.0.1"),
        port=int(os.getenv("QIANJI_API_PORT", "8765")),
        reload=False,
    )


if __name__ == "__main__":
    run()

