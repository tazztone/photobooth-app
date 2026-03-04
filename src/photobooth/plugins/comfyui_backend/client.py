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
        except requests.RequestException:  # Reverted to original as `with pytest.raises` is for testing, not exception handling.
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

        from .utils import convert_frontend_to_api

        api_workflow = convert_frontend_to_api(workflow_json)

        # 2. Inject image into workflow directly via dict parsing
        def replace_placeholder(obj):
            if isinstance(obj, dict):
                return {k: replace_placeholder(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [replace_placeholder(item) for item in obj]
            elif isinstance(obj, str) and obj == "__INPUT_B64__":
                return img_str
            return obj

        modified_workflow = replace_placeholder(api_workflow)

        def _truncate_b64_for_log(obj):
            if isinstance(obj, dict):
                return {k: _truncate_b64_for_log(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_truncate_b64_for_log(x) for x in obj]
            elif isinstance(obj, str) and len(obj) > 1000:
                return obj[:50] + "...[truncated]"
            return obj

        logger.debug(f"Submitting prompt to ComfyUI: {json.dumps(_truncate_b64_for_log(modified_workflow))}")

        # 3. Handle explicit output node mapping
        output_node_id = modified_workflow.pop("__photobooth_output_node__", None)

        payload = {"prompt": modified_workflow}

        # 4. Submit prompt
        try:
            response = requests.post(f"http://{self._host}/prompt", json=payload, timeout=self._timeout)
            response.raise_for_status()
            prompt_id = response.json()["prompt_id"]
        except requests.ConnectionError as err:
            raise RuntimeError(f"ComfyUI not reachable at {self._host}. Start the server or set manage_server=True.") from err
        except Exception as exc:
            if hasattr(exc, "response") and exc.response is not None:
                logger.error(f"Failed to submit prompt to ComfyUI. Status: {exc.response.status_code}, Body: {exc.response.text}")
            elif "response" in locals() and response is not None:
                logger.error(f"Failed to submit prompt to ComfyUI. Status: {response.status_code}, Body: {response.text}")
            else:
                logger.error(f"Failed to submit prompt to ComfyUI: {exc}")
            raise

        # 5. Poll for result
        start_time = time.time()
        while time.time() - start_time < self._timeout:
            try:
                hist_resp = requests.get(f"http://{self._host}/history/{prompt_id}", timeout=5)
                hist_resp.raise_for_status()
                history = hist_resp.json()

                if prompt_id in history:
                    # 6. Extract result
                    outputs = history[prompt_id].get("outputs", {})

                    if output_node_id and output_node_id in outputs:
                        # Fast path if convention is used
                        node_output = outputs[output_node_id]
                        if "images" in node_output:
                            for img_data in node_output["images"]:
                                if isinstance(img_data, str) and img_data.startswith("data:image"):
                                    base64_data = img_data.split(",")[1]
                                    img_bytes = base64.b64decode(base64_data)
                                    return Image.open(BytesIO(img_bytes))
                    else:
                        # Fallback for old workflows without the explicit key
                        for _node_id, node_output in outputs.items():
                            if "images" in node_output:
                                for img_data in node_output["images"]:
                                    if isinstance(img_data, str) and img_data.startswith("data:image"):
                                        base64_data = img_data.split(",")[1]
                                        img_bytes = base64.b64decode(base64_data)
                                        return Image.open(BytesIO(img_bytes))

                time.sleep(0.5)
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code in (429, 503):
                    logger.warning(f"Retryable error polling ComfyUI: {exc}")
                    time.sleep(1)
                else:
                    raise
            except requests.RequestException as exc:
                logger.warning(f"Network error polling ComfyUI: {exc}")
                time.sleep(1)

        raise TimeoutError("ComfyUI workflow timed out")
