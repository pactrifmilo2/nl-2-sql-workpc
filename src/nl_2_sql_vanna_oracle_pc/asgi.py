from .app import create_server
from .logging_config import configure_logging
from .settings import settings

configure_logging(settings)

app = create_server().create_app()

