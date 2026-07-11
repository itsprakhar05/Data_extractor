# from fastapi import FastAPI
# from fastapi.middleware.cors import CORSMiddleware
# from app.api.routes import ingest, query, delete, evaluate
# import logging
# from slowapi import Limiter
# from slowapi.util import get_remote_address
# from slowapi.errors import RateLimitExceeded
# logging.basicConfig(level=logging.INFO)

# app = FastAPI(title="OpenDataLoader Solr RAG Engine", version="1.0.0")
# limiter = Limiter(key_func=get_remote_address)

# app.state.limiter = limiter
# app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# app.include_router(ingest.router)
# app.include_router(query.router)
# app.include_router(delete.router)
# app.include_router(evaluate.router)

# @app.get("/")
# async def root_healthcheck():
#     return {"status": "online"}


from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.api.routes import ingest, query, delete, evaluate
from app.core.dependency import init_pipeline
import logging

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_pipeline()   # runs once at startup — loads model, connects Solr, inits DB
    yield
    # shutdown cleanup here if needed


app = FastAPI(
    title="OpenDataLoader Solr RAG Engine",
    version="1.0.0",
    lifespan=lifespan,
)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest.router)
app.include_router(query.router)
app.include_router(delete.router)
app.include_router(evaluate.router)


@app.get("/")
async def root_healthcheck():
    return {"status": "online"}