from typing import Any
from jinja2 import Environment, PackageLoader, select_autoescape

TEMPLATE_VERSION = "draft-1"
environment = Environment(
    loader=PackageLoader("hoanboy", "templates"), autoescape=select_autoescape()
)


def render(snapshot: dict[str, Any]) -> str:
    return environment.get_template("report.html").render(**snapshot)
