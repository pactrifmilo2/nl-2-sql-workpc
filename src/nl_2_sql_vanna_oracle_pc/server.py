"""FastAPI server with voice-to-text enabled chat UI."""

from html import escape
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send
from vanna.servers.base.templates import get_vanna_component_script
from vanna.servers.fastapi import VannaFastAPIServer

from .auth_middleware import BasicAuthMiddleware
from .content.vi import (
    CHAT_TITLE,
    PAGE_HEADING,
    PAGE_SUBTITLE,
    PAGE_TITLE,
)
from .reports import create_reports_router
from .settings import settings

UI_DIR = Path(__file__).resolve().parent / "ui"
STATIC_DIR = UI_DIR / "static"
INDEX_TEMPLATE = UI_DIR / "templates" / "index.html"


class ReportsCORSMiddleware(CORSMiddleware):
    """Apply cross-origin access only to the dedicated report API."""

    def __init__(self, app: ASGIApp, **kwargs: Any):
        super().__init__(app, **kwargs)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith(
            "/api/reports/"
        ):
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


def get_local_index_html(
    *,
    dev_mode: bool = False,
    static_path: str = "/static",
    cdn_url: str = "https://img.vanna.ai/vanna-components.js",
    api_base_url: str = "",
    page_title: str = PAGE_TITLE,
    page_heading: str = PAGE_HEADING,
    page_subtitle: str = PAGE_SUBTITLE,
    chat_title: str = CHAT_TITLE,
    extra_body_scripts: str = "",
) -> str:
    """Render the project-owned chat page instead of editing Vanna in site-packages."""
    component_script = get_vanna_component_script(dev_mode, static_path, cdn_url)
    replacements = {
        "__PAGE_TITLE__": escape(page_title),
        "__PAGE_HEADING__": escape(page_heading),
        "__PAGE_SUBTITLE__": escape(page_subtitle),
        "__CHAT_TITLE__": escape(chat_title),
        "__API_BASE_URL__": escape(api_base_url, quote=True),
        "__COMPONENT_SCRIPT__": component_script,
        "__EXTRA_BODY_SCRIPTS__": extra_body_scripts,
    }

    html = INDEX_TEMPLATE.read_text(encoding="utf-8")
    for placeholder, value in replacements.items():
        html = html.replace(placeholder, value)
    return html


def get_index_html_with_voice(
    *,
    dev_mode: bool = False,
    static_path: str = "/static",
    cdn_url: str = "https://img.vanna.ai/vanna-components.js",
    api_base_url: str = "",
    speech_lang: str = "vi-VN",
) -> str:
    config_script = (
        "<script>"
        f"window.VOICE_INPUT_CONFIG = {{ lang: {speech_lang!r}, continuous: false }};"
        "</script>"
    )
    voice_script = f'<script src="{static_path}/voice-input.js" defer></script>'
    injection = f"\n    {config_script}\n    {voice_script}\n"

    return get_local_index_html(
        dev_mode=dev_mode,
        static_path=static_path,
        cdn_url=cdn_url,
        api_base_url=api_base_url,
        extra_body_scripts=injection,
    )


def _replace_index_route(app: FastAPI, html: str) -> None:
    app.router.routes = [
        route
        for route in app.router.routes
        if not (
            isinstance(route, APIRoute)
            and route.path == "/"
            and "GET" in (route.methods or set())
        )
    ]

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index() -> str:
        return html


class VannaFastAPIServerWithVoice(VannaFastAPIServer):
    """Vanna FastAPI server with browser speech recognition on the chat input."""

    def create_app(self) -> FastAPI:
        app = super().create_app()

        if STATIC_DIR.is_dir():
            app.mount(
                "/static",
                StaticFiles(directory=str(STATIC_DIR)),
                name="nl2sql-static",
            )

        server_config: Dict[str, Any] = self.config or {}
        index_html = get_index_html_with_voice(
            dev_mode=server_config.get("dev_mode", False),
            static_path="/static",
            cdn_url=server_config.get(
                "cdn_url", "https://img.vanna.ai/vanna-components.js"
            ),
            api_base_url=server_config.get("api_base_url", ""),
            speech_lang=settings.speech_recognition_lang,
        )
        _replace_index_route(app, index_html)
        app.include_router(create_reports_router(settings))

        if settings.basic_auth_enabled:
            app.add_middleware(
                BasicAuthMiddleware,
                username=settings.app_basic_auth_user,
                password=settings.app_basic_auth_password,
            )

        if settings.report_api_cors_origins:
            app.add_middleware(
                ReportsCORSMiddleware,
                allow_origins=list(settings.report_api_cors_origins),
                allow_credentials=True,
                allow_methods=["GET"],
                allow_headers=[
                    "Accept",
                    "Authorization",
                    "Content-Type",
                    "X-API-Key",
                ],
            )

        return app
