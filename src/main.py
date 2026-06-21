from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from src.database.init_db import init_db
from src.routes.approve_routes import router as approve_router
from src.routes.block_routes import router as block_router
from src.routes.b2b_event_routes import router as b2b_event_router
from src.routes.blocking_reason_routes import router as blocking_reason_router
from src.routes.queue_routes import router as queue_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(lifespan=lifespan)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if isinstance(exc.detail, dict) and "code" in exc.detail and "message" in exc.detail:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.detail["code"],
                "message": exc.detail["message"],
            },
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={
            "code": "INVALID_REQUEST",
            "message": exc.errors()[0].get("msg", "Validation error"),
        },
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(approve_router, prefix="/api/v1")
app.include_router(block_router, prefix="/api/v1")
app.include_router(blocking_reason_router, prefix="/api/v1")
app.include_router(queue_router, prefix="/api/v1")
app.include_router(b2b_event_router, prefix="/api/v1")
