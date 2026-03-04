import io
import logging
import subprocess
import urllib.request
import zipfile
from pathlib import Path
from .resources import CUSTOM_NODES, MODELS

logger = logging.getLogger(__name__)

class ServerManager:
    _process: subprocess.Popen | None = None

    def __init__(self, server_path: Path):
        self.server_path = server_path

    def is_installed(self) -> bool:
        return (self.server_path / "main.py").exists()

    def install(self, progress_cb=None):
        """Install ComfyUI and required nodes/models.
        Zip-based installation to avoid git dependency.
        """
        logger.info(f"Installing ComfyUI to {self.server_path}")
        
        # 1. Download ComfyUI
        self._download_zip("https://github.com/comfyanonymous/ComfyUI", self.server_path)
        
        # 2. Setup Venv and install requirements (would use uv in a real scenario)
        # This part is simplified for the plan, assuming environment is already mostly ready
        # or that 'uv pip install' will be called.
        
        # 3. Download Custom Nodes
        for node in CUSTOM_NODES:
            dest = self.server_path / node.dest
            logger.info(f"Installing custom node {node.name} to {dest}")
            self._download_zip(node.url, dest)
            
        # 4. Download Models
        for model in MODELS:
            dest = self.server_path / model.dest
            logger.info(f"Downloading model {model.name} to {dest}")
            self._download_file(model.url, dest)

    def start(self):
        """Start the ComfyUI subprocess."""
        if self._process:
            logger.warning("ComfyUI server already running")
            return

        cmd = ["python", "main.py", "--listen", "127.0.0.1"]
        logger.info(f"Starting ComfyUI server: {' '.join(cmd)}")
        self._process = subprocess.Popen(
            cmd,
            cwd=self.server_path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )

    def stop(self):
        """Stop the ComfyUI subprocess."""
        if self._process:
            logger.info("Stopping ComfyUI server")
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

    def _download_zip(self, github_url: str, dest: Path):
        """Download and extract a GitHub repo as ZIP."""
        zip_url = f"{github_url.rstrip('/')}/archive/refs/heads/main.zip"
        dest.parent.mkdir(parents=True, exist_ok=True)
        
        with urllib.request.urlopen(zip_url) as r:
            with zipfile.ZipFile(io.BytesIO(r.read())) as zf:
                # GitHub ZIPs have a top-level folder 'RepoName-main'
                # We extract all, then rename the top-level folder to 'dest'
                top_level = zf.namelist()[0].split('/')[0]
                zf.extractall(dest.parent)
                
                extracted_path = dest.parent / top_level
                if dest.exists():
                     # if dest exists (e.g. empty dir created by parents=True), remove it if empty
                     if dest.is_dir() and not any(dest.iterdir()):
                         dest.rmdir()
                extracted_path.rename(dest)

    def _download_file(self, url: str, dest: Path):
        """Download a single file."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url) as r:
            with open(dest, "wb") as f:
                f.write(r.read())
