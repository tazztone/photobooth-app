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
        name="ComfyUI-BiRefNet-lite",
        url="https://github.com/ZHO-ZHO-ZHO/ComfyUI-BiRefNet-lite",
        dest="custom_nodes/ComfyUI-BiRefNet-lite",
    ),
]

MODELS = [
    Resource(
        name="BiRefNet-general",
        url="https://huggingface.co/ZhengPeng7/BiRefNet/resolve/main/model.safetensors",
        dest="models/segmentation/BiRefNet-general.safetensors",
        sha256="",
        skip_hash=True,  # TODO: compute before production merge
    ),
]
