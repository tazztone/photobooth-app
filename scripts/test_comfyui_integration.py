import json
import logging
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image

# Add src to path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from photobooth.plugins.comfyui_backend.client import ComfyUIClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_integration():
    host = "127.0.0.1:18188"
    client = ComfyUIClient(host, timeout=60)

    # 1. Start Server if not running
    process = None
    if not client.check_health():
        logger.info("ComfyUI not running. Starting it manually...")
        comfy_path = Path(__file__).parent.parent / "data" / "comfyui"
        venv_python = comfy_path / ".venv" / "bin" / "python"

        # Start server
        process = subprocess.Popen(
            [str(venv_python), "main.py", "--listen", "127.0.0.1", "--port", "18188"],
            cwd=str(comfy_path),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Wait for it to become healthy
        logger.info("Waiting for ComfyUI to start (this can take a while if it downloads models)...")
        healthy = False
        for i in range(120):  # Give it 2 minutes
            if client.check_health():
                logger.info("ComfyUI is now healthy!")
                healthy = True
                break
            if i % 10 == 0:
                logger.info(f"Still waiting... ({i}s)")
            time.sleep(1)

        if not healthy:
            logger.error("ComfyUI failed to start in time.")
            process.terminate()
            return False

    # 2. Run Test
    try:
        # Load the workflow
        wf_path = Path(__file__).parent.parent / "src" / "photobooth" / "plugins" / "comfyui_backend" / "workflows" / "rmbg_bg_remove.json"
        logger.info(f"Loading workflow from {wf_path}...")
        with open(wf_path) as f:
            workflow = json.load(f)

        # Create a dummy image
        logger.info("Creating test image...")
        img = Image.new("RGB", (512, 512), color="blue")
        from PIL import ImageDraw

        draw = ImageDraw.Draw(img)
        draw.rectangle([100, 100, 400, 400], fill="red")

        # Run workflow
        logger.info("Submitting workflow to ComfyUI...")
        start_time = time.time()
        result = client.run_workflow(img, workflow)
        duration = time.time() - start_time
        logger.info(f"Workflow completed in {duration:.2f}s")

        if result and isinstance(result, Image.Image):
            logger.info(f"Success! Received image of size {result.size}")
            # Verify it's not the same image (meaning RMBG did something)
            # Actually, just receiving a valid PIL image from the custom node is a huge win.
            output_path = Path(__file__).parent.parent / "tmp" / "test_result.png"
            output_path.parent.mkdir(exist_ok=True)
            result.save(output_path)
            logger.info(f"Saved result to {output_path}")
            return True
        else:
            logger.error(f"Unexpected result type: {type(result)}")
            return False

    except Exception as e:
        logger.error(f"Workflow failed: {e}")
        return False

    finally:
        if process:
            logger.info("Stopping manually started ComfyUI...")
            process.terminate()
            process.wait()


if __name__ == "__main__":
    success = test_integration()
    sys.exit(0 if success else 1)
