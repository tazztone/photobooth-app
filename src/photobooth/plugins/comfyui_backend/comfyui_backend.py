import logging
import json
from pathlib import Path
from PIL import Image

from ...models.genericstats import GenericStats, SubStats, DisplayEnum
from .. import hookimpl
from ..base_plugin import BaseFilter
from .config import ComfyuiBackendConfig
from .client import ComfyUIClient
from .server_manager import ServerManager

logger = logging.getLogger(__name__)

class ComfyuiBackend(BaseFilter[ComfyuiBackendConfig]):
    def __init__(self):
        super().__init__()
        self._config = ComfyuiBackendConfig()
        self._client = ComfyUIClient(self._config.comfyui_host, self._config.timeout)
        self._server_manager: ServerManager | None = None

    # ── Filter registration (IMPORT TIME) ──────────────────────────
    @hookimpl
    def mp_avail_filter(self) -> list[str]:
        """Scans local workflow files. No network calls here."""
        return [self.unify(name) for name in self._scan_local_workflows()]

    @hookimpl
    def mp_userselectable_filter(self) -> list[str]:
        if self._config.add_userselectable_filter:
            local = set(self._scan_local_workflows())
            return [self.unify(w) for w in self._config.userselectable_workflows if w in local]
        return []

    def _scan_local_workflows(self) -> list[str]:
        wf_dir = Path(__file__).parent / "workflows"
        if not wf_dir.exists():
            return []
        return [p.stem for p in sorted(wf_dir.glob("*.json"))]

    # ── Lifecycle hooks ───────────────────────────────────────────
    @hookimpl
    def init(self):
        if self._config.manage_server:
            self._server_manager = ServerManager(self._config.server_path)
            if not self._server_manager.is_installed():
                logger.warning("ComfyUI not installed. Use admin UI or CLI to install.")
        
    @hookimpl
    def start(self):
        if self._server_manager and self._server_manager.is_installed():
            self._server_manager.start()
            # Wait for health check before accepting work
            if not self._client.wait_until_healthy(timeout=30):
                logger.error("ComfyUI server failed to start within 30 seconds")

    @hookimpl
    def stop(self):
        if self._server_manager:
            self._server_manager.stop()

    @hookimpl
    def get_stats(self) -> GenericStats | None:
        return GenericStats(
            id="comfyui_backend",
            name="ComfyUI Backend",
            stats=[
                SubStats(
                    name="Reachable",
                    val=self._client.check_health(),
                    display=DisplayEnum.checkbox,
                )
            ],
        )

    # ── Filter execution ──────────────────────────────────────────
    @hookimpl
    def mp_filter_pipeline_step(self, image: Image.Image, plugin_filter: str, preview: bool) -> Image.Image | None:
        if preview:
            return None  # Fast-path: live-view never calls ComfyUI

        workflow_name = self.deunify(plugin_filter)
        if workflow_name is None:
            return None

        try:
            workflow_json = self._load_workflow(workflow_name)
            return self._client.run_workflow(image, workflow_json)
        except Exception as exc:
            logger.error(f"ComfyUI processing failed for {workflow_name}: {exc}")
            raise

    def _load_workflow(self, name: str) -> dict:
        wf_path = Path(__file__).parent / "workflows" / f"{name}.json"
        if not wf_path.exists():
            raise FileNotFoundError(f"Workflow file {wf_path} not found")
        with open(wf_path, "r") as f:
            return json.load(f)
