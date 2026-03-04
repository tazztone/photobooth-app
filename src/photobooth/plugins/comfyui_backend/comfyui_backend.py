import hashlib
import json
import logging
from collections import OrderedDict
from pathlib import Path
from threading import Lock

from PIL import Image

from ...models.genericstats import DisplayEnum, GenericStats, SubStats
from .. import hookimpl
from ..base_plugin import BaseFilter
from .client import ComfyUIClient
from .config import ComfyuiBackendConfig
from .server_manager import ServerManager

logger = logging.getLogger(__name__)

# Cache for processed images (mirrors RemovebgStep pattern)
# Key: "workflow_name:image_hash"
COMFYUI_CACHE: OrderedDict[str, Image.Image] = OrderedDict()
MAX_CACHE = 5
LOCK_CACHE = Lock()

# Max width to fast-path skip ComfyUI for live-view frames
PREVIEW_SKIP_MAX_WIDTH = 800


class ComfyuiBackend(BaseFilter[ComfyuiBackendConfig]):
    def __init__(self):
        super().__init__()
        self._config = ComfyuiBackendConfig()
        self._client: ComfyUIClient | None = None
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
        self._client = ComfyUIClient(self._config.comfyui_host, self._config.timeout)
        if self._config.manage_server:
            self._server_manager = ServerManager(self._config.server_path)
            if not self._server_manager.is_installed():
                logger.warning("ComfyUI not installed. Use admin UI or CLI to install.")

    @hookimpl
    def start(self):
        if self._server_manager and self._server_manager.is_installed():
            self._server_manager.start(host=self._config.comfyui_host)
            # Wait for health check before accepting work
            if self._client and not self._client.wait_until_healthy(timeout=30):
                logger.error("ComfyUI server failed to start within 30 seconds")

    @hookimpl
    def stop(self):
        if self._server_manager:
            self._server_manager.stop()

    @hookimpl
    def get_stats(self) -> GenericStats | None:
        if not self._client:
            return None
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
        # Fast-path for live-view stream: skip if preview is True AND image is small (likely camera steam)
        if preview and image.width < PREVIEW_SKIP_MAX_WIDTH:
            return image

        workflow_name = self.deunify(plugin_filter)
        if workflow_name is None:
            return None

        # Cache check
        cache_key = f"{workflow_name}:{self._hash_image(image)}"
        with LOCK_CACHE:
            if cache_key in COMFYUI_CACHE:
                logger.debug(f"ComfyUI cache hit for {workflow_name}")
                COMFYUI_CACHE.move_to_end(cache_key)
                return COMFYUI_CACHE[cache_key].copy()

        try:
            workflow_json = self._load_workflow(workflow_name)
            if not self._client:
                raise RuntimeError("ComfyUIClient not initialized")

            result = self._client.run_workflow(image, workflow_json)

            # Store in cache
            with LOCK_CACHE:
                logger.debug(f"Caching ComfyUI result for {workflow_name}")
                COMFYUI_CACHE[cache_key] = result.copy()
                COMFYUI_CACHE.move_to_end(cache_key)
                if len(COMFYUI_CACHE) > MAX_CACHE:
                    COMFYUI_CACHE.popitem(last=False)

            return result
        except Exception as exc:
            logger.error(f"ComfyUI processing failed for {workflow_name}: {exc}")
            raise

    def _hash_image(self, img: Image.Image) -> str:
        h = hashlib.sha256()
        h.update(img.mode.encode())
        h.update(str(img.size).encode())
        h.update(img.tobytes())
        return h.hexdigest()

    def _load_workflow(self, name: str) -> dict:
        wf_path = Path(__file__).parent / "workflows" / f"{name}.json"
        if not wf_path.exists():
            raise FileNotFoundError(f"Workflow file {wf_path} not found")
        with open(wf_path) as f:
            return json.load(f)
