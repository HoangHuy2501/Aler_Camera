from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

import api
import auth
from db import connect_pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    with connect_pool() as pool:
        pool.wait(timeout=15)
        app.state.pool = pool
        yield


app = FastAPI(title="API cảnh báo camera", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(auth.router)
app.include_router(api.router)
app.include_router(api.admin)


@app.middleware("http")
async def prevent_private_cache(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": "Dữ liệu không hợp lệ. Vui lòng kiểm tra các trường."})


@app.get("/health")
def health():
    return {"status": "ok"}
