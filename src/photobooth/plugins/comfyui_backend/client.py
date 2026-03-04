import base64
import json
import logging
import time
from io import BytesIO
import requests
from PIL import Image

logger = logging.getLogger(__name__)

class ComfyUIClient:
    def __init__(self, host: str, timeout: int = 60):
        self._host = host
        self._timeout = timeout

    def check_health(self) -> bool:
        """Check if ComfyUI server is reachable.
        WARNING: must not be called from event loop thread.
        """
        try:
            # system_stats is a lightweight endpoint
            response = requests.get(f"http://{self._host}/system_stats", timeout=2)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def wait_until_healthy(self, timeout: int = 30):
        """Poll health check until healthy or timeout."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.check_health():
                return True
            time.sleep(1)
        return False

    def run_workflow(self, image: Image.Image, workflow_json: dict) -> Image.Image:
        """Run a ComfyUI workflow with an input image.
        WARNING: must not be called from event loop thread.
        """
        # 1. Encode image to base64
        buffered = BytesIO()
        image.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()

        # 2. Inject image into workflow (logic depends on ETN_LoadImageBase64 node)
        # We look for nodes of type ETN_LoadImageBase64 and inject the image.
        # Alternatively, the workflow JSON uses a placeholder like __INPUT_B64__.
        wf_str = json.dumps(workflow_json).replace("__INPUT_B64__", img_str)
        payload = {"prompt": json.loads(wf_str)}

        # 3. Submit prompt
        try:
            response = requests.post(f"http://{self._host}/prompt", json=payload, timeout=self._timeout)
            response.raise_for_status()
            prompt_id = response.json()["prompt_id"]
        except Exception as exc:
            logger.error(f"Failed to submit prompt to ComfyUI: {exc}")
            raise

        # 4. Poll for result
        start_time = time.time()
        while time.time() - start_time < self._timeout:
            try:
                hist_resp = requests.get(f"http://{self._host}/history/{prompt_id}", timeout=5)
                hist_resp.raise_for_status()
                history = hist_resp.json()

                if prompt_id in history:
                    # 5. Extract result (logic depends on ETN_GetImageAsBase64 node)
                    outputs = history[prompt_id].get("outputs", {})
                    for node_id, node_output in outputs.items():
                        if "images" in node_output:
                            # ETN_GetImageAsBase64 returns base64 strings in 'images'
                            for img_data in node_output["images"]:
                                if isinstance(img_data, str) and img_data.startswith("data:image"):
                                    # Extract base64 part
                                    base64_data = img_data.split(",")[1]
                                    img_bytes = base64.b64decode(base64_data)
                                    return Image.open(BytesIO(img_bytes))
                                elif "filename" in img_data:
                                    # Fallback for standard SaveImage nodes if needed
                                    # For now we assume tooling nodes as per plan
                                    pass

                time.sleep(0.5)
            except Exception as exc:
                logger.warning(f"Error polling ComfyUI history: {exc}")
                time.sleep(1)

        raise TimeoutError("ComfyUI workflow timed out")
