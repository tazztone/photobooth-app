import logging

logger = logging.getLogger(__name__)


def convert_frontend_to_api(workflow: dict) -> dict:
    """
    Converts a ComfyUI Frontend 'Save' JSON into an 'API Prompt' JSON.
    This allows users to save workflows directly in the UI and use them in the app.
    """
    if "nodes" not in workflow:
        # Already in API format or unknown
        return workflow

    api_prompt = {}

    # 1. Map links from [link_id] -> (origin_node_id, origin_output_index)
    links_map = {}
    for link in workflow.get("links", []):
        if not link:
            continue
        # link format: [id, origin_node_id, origin_output_idx, target_node_id, target_input_idx, type]
        link_id, origin_id, origin_idx, _target_id, _target_idx, _type = link
        links_map[link_id] = [str(origin_id), origin_idx]

    # 2. Iterate over nodes to build the API prompt
    for node in workflow.get("nodes", []):
        node_id = str(node["id"])
        class_type = node["type"]

        inputs = {}

        # B. Handle connected inputs (links)
        for input_data in node.get("inputs", []):
            input_name = input_data["name"]
            link_id = input_data.get("link")
            if link_id is not None and link_id in links_map:
                inputs[input_name] = links_map[link_id]

        # C. Handle widgets (values not linked)
        if "widgets_values" in node:
            w_vals = node["widgets_values"]
            if class_type == "ETN_SaveImageBase64" and len(w_vals) >= 1:
                inputs["format"] = w_vals[0]
            elif class_type == "ETN_SendImageWebSocket" and len(w_vals) >= 1:
                inputs["format"] = w_vals[0]
            elif class_type == "ETN_LoadImageBase64" and len(w_vals) >= 1:
                # If image is empty string, default to placeholder
                inputs["image"] = w_vals[0] if w_vals[0] else "__INPUT_B64__"
            elif class_type == "BiRefNetRMBG":
                keys = ["model", "mask_blur", "mask_offset", "invert_output", "refine_foreground", "background", "background_color"]
                for i, key in enumerate(keys):
                    if i < len(w_vals):
                        inputs[key] = w_vals[i]
            elif class_type == "RMBG":
                keys = [
                    "model",
                    "sensitivity",
                    "process_res",
                    "mask_blur",
                    "mask_offset",
                    "invert_output",
                    "refine_foreground",
                    "background",
                    "background_color",
                ]
                for i, key in enumerate(keys):
                    if i < len(w_vals):
                        inputs[key] = w_vals[i]

        api_prompt[node_id] = {
            "inputs": inputs,
            "class_type": class_type,
        }

    # Preserving the photobooth specific key
    if "__photobooth_output_node__" in workflow:
        api_prompt["__photobooth_output_node__"] = workflow["__photobooth_output_node__"]

    return api_prompt
