"""FastAPI server with voice-to-text enabled chat UI."""

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from vanna.servers.base.templates import get_index_html
from vanna.servers.fastapi import VannaFastAPIServer

from .auth_middleware import BasicAuthMiddleware
from .settings import settings

STATIC_DIR = Path(__file__).resolve().parent / "static"


def get_index_html_with_voice(
    *,
    dev_mode: bool = False,
    static_path: str = "/static",
    cdn_url: str = "https://img.vanna.ai/vanna-components.js",
    api_base_url: str = "",
    speech_lang: str = "vi-VN",
) -> str:
    html = get_index_html(
        dev_mode=dev_mode,
        static_path=static_path,
        cdn_url=cdn_url,
        api_base_url=api_base_url,
    )

    config_script = (
        "<script>"
        f"window.VOICE_INPUT_CONFIG = {{ lang: {speech_lang!r}, continuous: false }};"
        "</script>"
    )
    voice_script = f'<script src="{static_path}/voice-input.js" defer></script>'
    injection = f"\n    {config_script}\n    {voice_script}\n"

    return html.replace("</body>", f"{injection}</body>")


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

        if settings.basic_auth_enabled:
            app.add_middleware(
                BasicAuthMiddleware,
                username=settings.app_basic_auth_user,
                password=settings.app_basic_auth_password,
            )

        return app
