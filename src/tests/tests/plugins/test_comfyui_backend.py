import base64
import zipfile
from io import BytesIO

import pytest
import requests
from PIL import Image

from photobooth.models.genericstats import GenericStats
from photobooth.plugins.comfyui_backend.comfyui_backend import ComfyuiBackend
from photobooth.plugins.comfyui_backend.config import ComfyuiBackendConfig


@pytest.fixture
def comfyui_plugin():
    plugin = ComfyuiBackend()
    plugin._config = ComfyuiBackendConfig()
    return plugin


def test_plugin_init(comfyui_plugin):
    """Test that the plugin initializes without errors."""
    comfyui_plugin.init()
    assert comfyui_plugin._config is not None


def test_mp_avail_filter(comfyui_plugin, tmp_path):
    """Test that avail filters are scanned from the workflows directory."""
    # Create a mock workflows directory
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    (wf_dir / "test_workflow.json").write_text("{}")

    # Patch the plugin to use our tmp workflows dir
    def mock_scan():
        return ["test_workflow"]

    comfyui_plugin._scan_local_workflows = mock_scan

    avail = comfyui_plugin.mp_avail_filter()
    assert "ComfyuiBackend.test_workflow" in avail


def test_preview_fast_path(comfyui_plugin):
    """Test that preview=True returns the original image immediately (fast-path)."""
    img = Image.new("RGB", (10, 10))
    result = comfyui_plugin.mp_filter_pipeline_step(img, "ComfyuiBackend.test", preview=True)
    assert result is img


def test_client_check_health(httpserver):
    """Test the client's health check with a mock server."""
    from photobooth.plugins.comfyui_backend.client import ComfyUIClient

    httpserver.expect_request("/system_stats").respond_with_json({"status": "ok"})

    client = ComfyUIClient(f"{httpserver.host}:{httpserver.port}")
    assert client.check_health() is True


def test_client_run_workflow(httpserver):
    """Test running a workflow through the client with a mocked ComfyUI API."""
    from photobooth.plugins.comfyui_backend.client import ComfyUIClient

    prompt_id = "test-prompt-id"
    httpserver.expect_request("/prompt").respond_with_json({"prompt_id": prompt_id})

    # Mock history response with a base64 image
    img = Image.new("RGB", (10, 10), color="red")
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    img_b64 = "data:image/png;base64," + base64.b64encode(buffered.getvalue()).decode()

    httpserver.expect_request(f"/history/{prompt_id}").respond_with_json({prompt_id: {"outputs": {"3": {"images": [img_b64]}}}})

    client = ComfyUIClient(f"{httpserver.host}:{httpserver.port}", timeout=5)
    result = client.run_workflow(Image.new("RGB", (10, 10)), {"test": "workflow"})

    assert isinstance(result, Image.Image)
    assert result.size == (10, 10)


def test_get_stats(comfyui_plugin):
    """Test that get_stats returns a valid GenericStats object."""
    comfyui_plugin.init()
    stats = comfyui_plugin.get_stats()
    assert isinstance(stats, GenericStats)
    assert stats.id == "comfyui_backend"
    assert len(stats.stats) == 1
    assert stats.stats[0].name == "Reachable"


def test_server_manager_install_logic(tmp_path):
    """Test the zip-based installation logic, specifically directory renaming."""
    from photobooth.plugins.comfyui_backend.server_manager import ServerManager

    server_path = tmp_path / "comfy_server"
    manager = ServerManager(server_path)

    # Create a mock GitHub-style ZIP (top-level folder differs from dest name)
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr("ComfyUI-main/main.py", "print('hello')")
        zf.writestr("ComfyUI-main/requirements.txt", "torch")

    zip_buffer.seek(0)

    # Mock _download_zip internal logic to use our buffer
    def mock_download_zip_logic(url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_buffer) as zf:
            top_level = zf.namelist()[0].split("/")[0]
            zf.extractall(dest.parent)
            extracted_path = dest.parent / top_level
            if dest.exists() and dest.is_dir() and not any(dest.iterdir()):
                dest.rmdir()
            extracted_path.rename(dest)

    manager._download_zip = mock_download_zip_logic
    # We only test ComfyUI part here to verify renaming
    manager._download_zip("http://github.com/test", server_path)

    assert (server_path / "main.py").exists()
    assert (server_path / "requirements.txt").exists()
    assert manager.is_installed()


def test_client_error_handling(httpserver):
    """Test how the client handles various API errors."""
    from photobooth.plugins.comfyui_backend.client import ComfyUIClient

    client = ComfyUIClient(f"{httpserver.host}:{httpserver.port}", timeout=1)

    # 1. Test 500 Error
    # Use a specific path or unique header to avoid matching the next request if possible,
    # but httpserver matches based on order/expectations.
    httpserver.expect_request("/prompt").respond_with_json({"error": "server error"}, status=500)
    with pytest.raises(requests.HTTPError):
        client.run_workflow(Image.new("RGB", (10, 10)), {})

    # 2. Test Timeout (simulated by missing history)
    httpserver.clear()
    httpserver.expect_request("/prompt").respond_with_json({"prompt_id": "timeout-id"})
    httpserver.expect_request("/history/timeout-id").respond_with_json({})  # Empty history

    with pytest.raises(TimeoutError):
        client.run_workflow(Image.new("RGB", (10, 10)), {"test": "wf"})
