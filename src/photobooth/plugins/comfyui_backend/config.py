from pathlib import Path
from pydantic import Field
from pydantic_settings import SettingsConfigDict
from ... import CONFIG_PATH
from ...services.config.baseconfig import BaseConfig

class ComfyuiBackendConfig(BaseConfig):
    model_config = SettingsConfigDict(
        title="ComfyUI Backend Plugin Config",
        json_file=f"{CONFIG_PATH}plugin_comfyui_backend.json",
        env_prefix="comfyui-backend-",
    )

    comfyui_host: str = Field(
        default="127.0.0.1:8188",
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
    userselectable_workflows: list[str] = Field(
        default=["birefnet_bg_remove"],
        description="List of workflow names (without .json extension) to make available to users.",
    )
