import hashlib
import io
import logging
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from .resources import CUSTOM_NODES, MODELS

logger = logging.getLogger(__name__)


class ServerManager:
    def __init__(self, server_path: Path):
        self.server_path = server_path
        self._process: subprocess.Popen | None = None

    def is_installed(self) -> bool:
        return (self.server_path / "main.py").exists()

    def install(self):
        """Install ComfyUI and required nodes/models.
        Zip-based installation to avoid git dependency.
        """
        logger.info(f"Installing ComfyUI to {self.server_path}")

        # 1. Download ComfyUI (Pinned Version)
        self._download_zip("https://github.com/Comfy-Org/ComfyUI", self.server_path, ref="v0.15.1")

        # 2. Setup Venv and install requirements
        logger.info("Setting up Python virtual environment...")
        venv_path = self.server_path / ".venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv_path)], check=True)

        uv_path = shutil.which("uv")
        if sys.platform == "win32":
            pip_path = venv_path / "Scripts" / "pip.exe"
        else:
            pip_path = venv_path / "bin" / "pip"

        env = {"VIRTUAL_ENV": str(venv_path.resolve())} if uv_path else None

        requirements_path = self.server_path / "requirements.txt"
        if requirements_path.exists():
            logger.info("Installing dependencies...")

            if uv_path:
                logger.info(f"Using uv found at {uv_path}")
                cmd = [uv_path, "pip", "install", "-r", str(requirements_path.resolve())]
            else:
                logger.info("uv not found in PATH, falling back to pip")
                cmd = [str(pip_path.resolve()), "install", "-r", str(requirements_path.resolve())]

            subprocess.run(cmd, cwd=self.server_path, env=env, check=True)

        # 3. Download Custom Nodes
        for node in CUSTOM_NODES:
            dest = self.server_path / node.dest
            logger.info(f"Installing custom node {node.name} to {dest}")
            self._download_zip(node.url, dest)

        # 4. Install custom node requirements if they exist
        custom_nodes_dir = self.server_path / "custom_nodes"
        if custom_nodes_dir.exists():
            for req_file in custom_nodes_dir.rglob("requirements.txt"):
                logger.info(f"Installing requirements from {req_file}")
                # Reuse the same logic/env as the main requirements
                if uv_path:
                    cmd = [uv_path, "pip", "install", "-r", str(req_file.resolve())]
                else:
                    cmd = [str(pip_path.resolve()), "install", "-r", str(req_file.resolve())]

                subprocess.run(
                    cmd,
                    cwd=req_file.parent,
                    env=env,
                    check=True,
                )

        # 5. Deploy bundled custom nodes from the plugin
        bundled_nodes_src = Path(__file__).parent / "custom_nodes"
        if bundled_nodes_src.exists():
            target_dir = custom_nodes_dir / "photobooth_nodes"
            target_dir.mkdir(parents=True, exist_ok=True)
            for node_file in bundled_nodes_src.glob("*.py"):
                logger.info(f"Deploying bundled custom node {node_file.name} to {target_dir}")
                shutil.copy(node_file, target_dir / node_file.name)

        # 6. Download Models
        for model in MODELS:
            dest = self.server_path / model.dest
            logger.info(f"Downloading model {model.name} to {dest}")
            self._download_file(model.url, dest, sha256_expected=model.sha256, skip_hash=model.skip_hash)

    def start(self, host: str = "127.0.0.1:18188"):
        """Start the ComfyUI subprocess."""
        if self._process:
            logger.warning("ComfyUI server already running")
            return

        # Parse host:port
        if ":" in host:
            listen_ip, port = host.split(":", 1)
        else:
            listen_ip, port = host, "18188"

        if sys.platform == "win32":
            venv_python = self.server_path.resolve() / ".venv" / "Scripts" / "python.exe"
        else:
            venv_python = self.server_path.resolve() / ".venv" / "bin" / "python"

        cmd = [str(venv_python), "main.py", "--listen", listen_ip, "--port", port]
        logger.info(f"Starting ComfyUI server: {' '.join(cmd)}")
        self._process = subprocess.Popen(
            cmd,
            cwd=self.server_path.resolve(),
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

    def _download_zip(self, github_url: str, dest: Path, ref: str | None = None):
        """Download and extract a GitHub repo as ZIP. Tries provided ref, then 'main', then 'master'."""
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Try provided ref, then 'main', then 'master'
        refs_to_try = [ref] if ref else []
        refs_to_try.extend(["main", "master"])

        last_error = None
        for r_name in refs_to_try:
            if not r_name:
                continue

            prefix = "tags" if r_name.startswith("v") else "heads"
            zip_url = f"{github_url.rstrip('/')}/archive/refs/{prefix}/{r_name}.zip"

            logger.info(f"Trying download from {zip_url}...")
            try:
                with urllib.request.urlopen(zip_url, timeout=300) as r_content:
                    with zipfile.ZipFile(io.BytesIO(r_content.read())) as zf:
                        for name in zf.namelist():
                            if ".." in name or name.startswith("/"):
                                raise ValueError(f"Invalid path in archive: {name}")

                        zf.extractall(dest.parent)

                        top_level = zf.namelist()[0].split("/")[0]
                        extracted_path = dest.parent / top_level
                        if dest.exists():
                            logger.info(f"Removing existing directory/file at {dest} for clean install...")
                            if dest.is_dir():
                                shutil.rmtree(dest)
                            else:
                                dest.unlink()

                        extracted_path.rename(dest)
                        return  # Success!
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    last_error = e
                    continue
                raise
            except Exception:
                raise

        raise last_error or RuntimeError(f"Failed to download ZIP for {github_url}")

    def _download_file(self, url: str, dest: Path, max_size: int = 5 * 1024 * 1024 * 1024, sha256_expected: str = "", skip_hash: bool = False):
        """Download a single file with timeout, chunking, and size limit."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        hasher = hashlib.sha256()

        with urllib.request.urlopen(url, timeout=300) as r:
            content_length = r.headers.get("Content-Length")
            if content_length and int(content_length) > max_size:
                raise ValueError(f"File too large: {content_length} > {max_size}")

            with open(dest, "wb") as f:
                downloaded = 0
                while chunk := r.read(8192):
                    downloaded += len(chunk)
                    if downloaded > max_size:
                        raise ValueError(f"Download exceeded max_size limit {max_size}")
                    f.write(chunk)
                    if not skip_hash:
                        hasher.update(chunk)

        if not skip_hash and sha256_expected:
            computed_hash = hasher.hexdigest()
            if computed_hash != sha256_expected:
                dest.unlink()  # Remove corrupted file
                raise ValueError(f"SHA256 mismatch for {dest}. Expected {sha256_expected}, got {computed_hash}")
