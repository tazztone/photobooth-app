from dataclasses import dataclass


@dataclass
class Resource:
    name: str
    url: str
    dest: str
    sha256: str = ""
    skip_hash: bool = False


CUSTOM_NODES = [
    Resource(
        name="comfyui-tooling-nodes",
        url="https://github.com/Acly/comfyui-tooling-nodes",
        dest="custom_nodes/comfyui-tooling-nodes",
    ),
    Resource(
        name="ComfyUI-RMBG",
        url="https://github.com/1038lab/ComfyUI-RMBG",
        dest="custom_nodes/ComfyUI-RMBG",
    ),
]

MODELS = [
    # RMBG node downloads its own models on first run
]
