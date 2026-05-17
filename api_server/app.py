from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from extensions.db import cleanup_old_realtime_rows, init_db
from routers.health import router as health_router
from routers.interaction import router as interaction_router
from routers.sensor import router as sensor_router
from routers.sessions import router as sessions_router


def create_app() -> FastAPI:
    app = FastAPI(title="Marimo API Server", version="0.2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    app.include_router(sensor_router)
    app.include_router(sessions_router)
    app.include_router(interaction_router)

    @app.on_event("startup")
    def startup() -> None:
        init_db()
        cleanup_old_realtime_rows(force=True)

    return app


app = create_app()
