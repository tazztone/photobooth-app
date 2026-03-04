import json
from pathlib import Path

from photobooth.plugins.comfyui_backend.utils import convert_frontend_to_api


def test_convert_frontend_to_api():
    # Load the user's working workflow
    # Detect root relative to this file
    this_dir = Path(__file__).parent
    # src/tests/tests/plugins/file -> plugins/tests/tests/src/root
    root = this_dir.parent.parent.parent.parent
    wf_path = root / "src" / "photobooth" / "plugins" / "comfyui_backend" / "workflows" / "birefnet_bg_remove.json"

    with open(wf_path) as f:
        frontend_wf = json.load(f)

    api_prompt = convert_frontend_to_api(frontend_wf)

    # Assertions
    # In the user's JSON, nodes have IDs 1, 2, 3
    # 1: ETN_SendImageWebSocket
    # 2: ETN_LoadImageBase64
    # 3: BiRefNetRMBG
    assert "1" in api_prompt
    assert "2" in api_prompt
    assert "3" in api_prompt

    # Check node 3 inputs (BiRefNetRMBG)
    node3 = api_prompt["3"]
    assert node3["class_type"] == "BiRefNetRMBG"
    assert node3["inputs"]["model"] == "BiRefNet_lite"
    assert node3["inputs"]["image"] == ["2", 0]  # Link 2 from Node 2 output 0

    # Check node 1 inputs (SendImageWebSocket)
    node1 = api_prompt["1"]
    assert node1["inputs"]["images"] == ["3", 0]  # Link 1 from Node 3 output 0


if __name__ == "__main__":
    test_convert_frontend_to_api()
    print("Converter test passed!")
