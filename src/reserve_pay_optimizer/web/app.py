"""FastAPI adapter for the three-screen Phase-11 dashboard."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from reserve_pay_optimizer import __version__
from reserve_pay_optimizer.domain.errors import DomainValidationError
from reserve_pay_optimizer.reserve_pay.errors import ReservePayError
from reserve_pay_optimizer.web.errors import DashboardError
from reserve_pay_optimizer.web.schemas import (
    AgentDecideRequest,
    DynamicDemoRequest,
    MockAuthorizeRequest,
    OptimizeRequest,
    WhatIfRequest,
)
from reserve_pay_optimizer.web.services import DashboardService, DashboardSettings


def create_app(settings: DashboardSettings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            application.state.dashboard_service = DashboardService(settings)
            application.state.dashboard_load_error = None
        except DashboardError as exc:
            application.state.dashboard_service = None
            application.state.dashboard_load_error = exc
        yield

    application = FastAPI(
        title="Reserve Pay Block Optimizer Dashboard API",
        version=__version__,
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    def dashboard(request: Request) -> DashboardService:
        service = getattr(request.app.state, "dashboard_service", None)
        if service is None:
            error = getattr(request.app.state, "dashboard_load_error", None)
            if isinstance(error, DashboardError):
                raise error
            raise DashboardError(
                "dashboard_unavailable",
                "Dashboard services are not available.",
                status_code=503,
            )
        return service

    @application.exception_handler(DashboardError)
    async def dashboard_error_handler(_request: Request, exc: DashboardError):
        return JSONResponse(status_code=exc.status_code, content=exc.to_response())

    @application.exception_handler(DomainValidationError)
    async def domain_error_handler(_request: Request, exc: DomainValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_transaction",
                    "message": "Ride transaction validation failed.",
                    "details": [issue.to_dict() for issue in exc.issues],
                }
            },
        )

    @application.exception_handler(RequestValidationError)
    async def request_error_handler(_request: Request, exc: RequestValidationError):
        details = [
            {
                "field": ".".join(str(part) for part in item["loc"] if part != "body"),
                "code": item["type"],
                "message": item["msg"],
            }
            for item in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "Dashboard request validation failed.",
                    "details": details,
                }
            },
        )

    @application.exception_handler(ReservePayError)
    async def reserve_error_handler(_request: Request, exc: ReservePayError):
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": [exc.safe_metadata] if exc.safe_metadata else [],
                }
            },
        )

    @application.get("/api/health")
    def health(request: Request):
        loaded = getattr(request.app.state, "dashboard_service", None) is not None
        return {"status": "ok", "version": __version__, "models_loaded": loaded}

    @application.post("/api/optimize")
    def optimize(payload: OptimizeRequest, service: DashboardService = Depends(dashboard)):
        return service.optimize(payload)

    @application.post("/api/what-if")
    def what_if(payload: WhatIfRequest, service: DashboardService = Depends(dashboard)):
        return service.what_if(payload)

    @application.post("/api/mock/authorize")
    def mock_authorize(
        payload: MockAuthorizeRequest,
        service: DashboardService = Depends(dashboard),
    ):
        return service.authorize_mock(payload)

    @application.post("/api/dynamic-demo")
    def dynamic_demo(
        payload: DynamicDemoRequest,
        service: DashboardService = Depends(dashboard),
    ):
        return service.dynamic_demo(payload)

    @application.get("/api/evidence")
    def evidence(service: DashboardService = Depends(dashboard)):
        return service.evidence()

    @application.get("/api/demo-scenarios")
    def demo_scenarios(service: DashboardService = Depends(dashboard)):
        return service.demo_scenarios()

    @application.get("/api/agent/capabilities")
    def agent_capabilities(service: DashboardService = Depends(dashboard)):
        return service.agent_capabilities()

    @application.post("/api/agent/decide")
    def agent_decide(payload: AgentDecideRequest, service: DashboardService = Depends(dashboard)):
        return service.agent_decide(payload)

    @application.get("/api/agent/runs/{run_id}")
    def agent_run(run_id: str, service: DashboardService = Depends(dashboard)):
        return service.agent_run(run_id)

    return application


app = create_app()
