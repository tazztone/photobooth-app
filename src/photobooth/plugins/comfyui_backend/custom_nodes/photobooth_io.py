import base64
from io import BytesIO

import numpy as np
import torch
from PIL import Image


class ETN_SaveImageBase64:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "images": ("IMAGE",),
                "format": (["PNG", "JPEG"],),
            },
        }

    RETURN_TYPES = ()
    FUNCTION = "execute"
    OUTPUT_NODE = True
    CATEGORY = "external/tooling"

    def execute(self, images: torch.Tensor, format: str):
        results = []
        for tensor in images:
            # Convert tensor to PIL
            array = 255.0 * tensor.cpu().numpy()
            image = Image.fromarray(np.clip(array, 0, 255).astype(np.uint8))

            # Save to buffer
            buffered = BytesIO()
            image.save(buffered, format=format)
            img_str = base64.b64encode(buffered.getvalue()).decode()

            results.append(f"data:image/{format.lower()};base64,{img_str}")

        return {"ui": {"images": results}}


NODE_CLASS_MAPPINGS = {"ETN_SaveImageBase64": ETN_SaveImageBase64}

NODE_DISPLAY_NAME_MAPPINGS = {"ETN_SaveImageBase64": "Save Image (Base64)"}
