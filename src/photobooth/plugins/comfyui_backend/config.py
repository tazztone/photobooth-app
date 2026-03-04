from pathlib import Path
from typing import Literal, get_args

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from ... import CONFIG_PATH
from ...services.config.baseconfig import BaseConfig

# Discover available workflows at import time — mirrors the pilgram2 pattern.
# This produces a Literal type whose values pydantic exposes as an enum in the
# JSON schema, so the admin UI renders a multi-select checkbox list instead of
# a free-text field.
_WORKFLOWS_DIR = Path(__file__).parent / "workflows"
_workflow_stems = (
    tuple(p.stem for p in sorted(_WORKFLOWS_DIR.glob("*.json")))
    if _WORKFLOWS_DIR.exists()
    else ()
)

# Fallback to known bundled names if the directory doesn't exist yet
# (e.g. during a fresh install before the first startup).
if not _workflow_stems:
    _workflow_stems = ("birefnet_bg_remove", "rmbg_bg_remove")

# Tuples are flattened by Python's typing.Literal, so
# Literal[("a", "b")] is identical to Literal["a", "b"].
available_workflow = Literal[_workflow_stems]


class ComfyuiBackendConfig(BaseConfig):
    model_config = SettingsConfigDict(
        title="ComfyUI Backend Plugin Config",
        json_file=f"{CONFIG_PATH}plugin_comfyui_backend.json",
        env_prefix="comfyui-backend-",
    )

    comfyui_host: str = Field(
        default="127.0.0.1:18188",
        description="ComfyUI server address (host:port).",
    )
    manage_server: bool = Field(
        default=False,
        description="Automatically install and manage a local ComfyUI server instance.",
    )
    server_path: Path = Field(
        default=Path("data/comfyui/"),
        description="Path where the managed ComfyUI server will be installed.",
    )
    timeout: int = Field(
        default=60,
        description="Timeout in seconds for ComfyUI API requests.",
    )
    add_userselectable_filter: bool = Field(
        default=True,
        description="Add ComfyUI workflows to the list of filters users can choose from.",
    )
    userselectable_workflows: list[available_workflow] = Field(
        default=list(get_args(available_workflow)),
        description=(
            "Select workflows the user can choose from. "
            "Even if unselected here, the workflow is still available in the admin configuration."
        ),
    )
