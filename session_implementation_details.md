# Session Implementation Details: ComfyUI Backend Plugin

This document provides a highly detailed, comprehensive technical reference for the `comfyui_backend` plugin implemented for the `photobooth-app`. It aims to serve as a complete guide for maintaining, extending, or debugging the plugin in the future.

---

## 1. Plugin Architecture & Hook Engine Integration
The plugin is structured as an optional extension that hooks into the `photobooth-app`'s core `pluggy` architecture. It subclasses `BaseFilter` to seamlessly participate in the image processing pipeline.

### Core Hooks Implemented
- **`mp_avail_filter`**: Discovers available filters at module import time. To avoid network latency or startup crashes when a ComfyUI server is down, this scans the local `workflows/` directory for `.json` files.
- **`mp_userselectable_filter`**: Returns a subset of available workflows that are allowed to be selected by the end user via the UI, determined by the `userselectable_workflows` config value.
- **`Plugin Filter Sorting`**: Built-in support within `mediaprocessing` prioritizes `ComfyuiBackend.*` filters to display at the top of the gallery UI list.
- **`mp_filter_pipeline_step`**: The main execution block. Intercepts the image frame. Crucially handles a fast-path (`if image.width < PREVIEW_SKIP_MAX_WIDTH`) to ensure that heavy network payloads do not block the live-view feed. Additionally, implements an **in-memory LRU cache** (size 5, based on image hash and workflow name) to ensure switching back to a previously applied filter is instantaneous.
- **`init`, `start`, `stop`**: Standard lifecycle hooks.
- **`get_stats`**: Implements `photobooth.models.genericstats.GenericStats` and `SubStats` to reflect the current reachability of the ComfyUI server in the admin dashboard.

---

## 2. Configuration Model (`config.py`)
The plugin leverages `pydantic-settings` to manage configuration, persisting state to `plugin_comfyui_backend.json`.

### Settings Included:
- `comfyui_host` (str): Network address of the ComfyUI server (default: `127.0.0.1:8188`).
- `manage_server` (bool): Dictates whether the plugin should take ownership of spawning and terminating a local ComfyUI subprocess.
- `server_path` (Path): Target directory for local ComfyUI installations (default: `data/comfyui/`).
- `timeout` (int): Maximum wait time for image inference in seconds to prevent pipeline blocking indefinitely.
- `add_userselectable_filter` & `userselectable_workflows`: Toggles and defines which workflows populate the front-end user interfaces.

---

## 3. Server Management & Provisioning (`server_manager.py` & `resources.py`)
To enable an "out-of-the-box" experience without requiring users to manually configure a Python environment or install `git`, the plugin provides a self-managed server installation path.

### Zip-Based Provisioning
Instead of `git clone`, the `ServerManager` uses the GitHub archive API (`/archive/refs/heads/main.zip`) to download ComfyUI and custom nodes.
- Extracts ZIPs directly into RAM via `io.BytesIO`.
- **Branch/Tag Fallback**: `_download_zip` intelligently tries the provided `ref` (tag), then falls back to `main` and `master` branches if 404s occur.
- **Dependencies Installed**:
  - `ComfyUI` (Pinned to `v0.15.1`)
  - `comfyui-tooling-nodes` (for base64 transport)
  - `ComfyUI-RMBG` (for background removal)
  - *Note: RMBG node automatically handles model downloads on first execution.*

### Subprocess Execution
- Starts the `main.py` entry point as an asynchronous subprocess targeting the provisioned `.venv` (`bin/python` on POSIX, `Scripts/python.exe` on Windows).
- Captures the `subprocess.Popen` object as an instance attribute to guarantee that `stop()` can reliably terminate the server.
- **Critical Safety Feature**: `install()` is purposefully disconnected from `init()`. It must be triggered manually via a CLI script or admin button to prevent the app from completely freezing while downloading gigabytes of models on startup.
- **Custom Node Deployment**: The bundled `photobooth_io.py` containing `ETN_SaveImageBase64` is deployed to `custom_nodes/photobooth_nodes/` alongside a valid `__init__.py` to ensure ComfyUI correctly registers the module.

---

## 4. API Client Integration (`client.py`)
All communication with ComfyUI is strictly stateless HTTP/REST, avoiding complex WebSocket lifecycle issues during synchronous image pipeline steps.

### Health Checking
Uses a rapid 2-second timeout against `/system_stats`. This endpoint is fast and does not require touching the GPU, ensuring `check_health()` is instantaneous.

### Workflow Execution Lifecycle
1. **Serialization**: Converts the inbound `PIL.Image` into a base64 encoded PNG string.
2. **Injection**: Reads the workflow JSON and performs a string replacement for `__INPUT_B64__`. This places the image directly inside the `ETN_LoadImageBase64` node.
3. **Submission**: POSTs to `/prompt` and receives a `prompt_id`.
4. **Polling**: Enters a tight polling loop against `/history/{prompt_id}`.
5. **Extraction**: Once finished, parses the JSON tree for the exact outputs of `ETN_GetImageAsBase64`, decodes the returned string, and reconstructs the `PIL.Image`.

### Error Handling & Logging
- Translates `500 Internal Server Error` responses into detailed Python exceptions.
- Hard limits the polling loop matching the user-defined `timeout`.
- Prevents silent timeouts by strictly checking `history[prompt_id].get("status", {}).get("completed")`. If the job finishes without generating an `images` array (e.g., node breakdown), it raises a clear error immediately.
- Sanitizes logs automatically via `_truncate_b64_for_log` to prevent massive Base64 strings from crashing terminal output.

---

## 5. Workflows
Workflows are portable JSON files saved directly from the ComfyUI web UI (with minor modifications for base64 injection).

### Current Default: `birefnet_bg_remove.json`
Utilizes the BiRefNet model to create highly accurate segmentation masks, effectively removing backgrounds. Because the raw nodes are encapsulated in the JSON file, the backend python code never needs to know *what* ComfyUI is doing, only *how* to feed it an image and get one back.

---

## 6. Verification and Test Suite Configuration
A robust suite is maintained in `src/tests/tests/plugins/test_comfyui_backend.py`.

- **Mocking**: Utilizes `pytest-httpserver` to simulate ComfyUI API responses locally without loading PyTorch.
- **Test Scenarios**:
  - `test_plugin_init`: Ensures class instantiation and config loading.
  - `test_mp_avail_filter`: Validates that import-time scanning works correctly against temporary directories.
  - `test_preview_fast_path`: Proves that preview frames instantly return `None` without HTTP calls.
  - `test_client_check_health` & `test_client_run_workflow`: Validates base64 packaging, network requests, and payload unpacking.
  - `test_get_stats`: Hard-checks that `GenericStats` typing errors are avoided.
  - `test_server_manager_install_logic`: Uses an in-memory simulated GitHub ZIP payload to test the extraction and renaming logic path.
  - `test_client_error_handling`: Specifically checks 500 error catch behavior and timeouts.

---

## 7. Known Limitations & Future Enhancements
- **Python Virtual Environments**: The `install()` logic currently assumes the existing environment (`uv`) will have the dependencies required by ComfyUI, or that a wrapper script handles VENV creation. Production usage may require explicit `uv pip install -r requirements.txt` subprocess calls.
- **Model Checksums**: The `resources.py` manifest includes a `skip_hash` attribute. Implementing SHA256 verification on multi-gigabyte safetensors downloads is recommended for robustness in the future.
- **WebSocket Feedback**: While `/history` polling is simple and reliable for synchronous steps, large workflows might benefit from WebSocket tracking for fine-grained progress bars if the PhotoBooth UI supports it in the future.

---

### 1. Memory Exhaustion Risk During Large Downloads
- **Status**: ✅ **COMPLETED**.
- **Change**: Replaced `.read()` with chunked writing (`r.read(8192)`) in `_download_file`.
- **Note**: The ZIP downloader still buffers (~20-50MB for code repositories), but safetensor downloads (2GB+) are now fully streamed to disk.

### 2. URL and Branch Brittleness (404s)
- **Status**: ✅ **COMPLETED**.
- **Change**: Updated ComfyUI to `Comfy-Org` and added branch fallback logic (`main` -> `master`). Added support for tag pinning (`v0.15.1`).

### 2. Lack of Isolated Virtual Environment for ComfyUI
- **Status**: ✅ **COMPLETED**.
- **Change**: `install()` now creates a `.venv` and uses `uv pip install` to isolate dependencies.
- **Logic**: Keeps the photobooth's core environment lean and avoids version conflicts with PyTorch/ONNX.

### 3. Subprocess Execution Uses System Python
- **Status**: ✅ **COMPLETED**.
- **Change**: `start()` explicitly targets `bin/python` inside the provisioned `.venv`.
- **Logic**: Ensures ComfyUI runs with the correct ML libraries regardless of system PATH.

### 4. Missing Progress Feedback for Long Installations
- **Status**: ✅ **COMPLETED**.
- **Change**: The `install()` method logs step-by-step progress and is accessible via the CLI tool.

---

## 9. Helper Scripts

The following commands are available as shell scripts in the `scripts/` directory or directly via `poe`.

### Shell Scripts (Recommended)
Run these directly from the project root:
| Script | Description |
|--------|-------------|
| `./scripts/run.sh` | Starts the main Photobooth application. |
| `./scripts/dev.sh` | Starts the app in developer mode. |
| `./scripts/install_comfyui.sh` | Installs or updates ComfyUI and its custom nodes/models. |
| `./scripts/comfyui.sh` | Starts the managed ComfyUI server in standalone mode. |
| `./scripts/test.sh` | Runs the dedicated test suite for the ComfyUI backend plugin. |

### Poe Tasks (Alternative)
Run with `uv run poe <command>`:
| Command | Description |
|---------|-------------|
| `run` | Starts the main Photobooth application. |
| `install-comfyui` | Installs or updates ComfyUI. |
| `comfyui` | Starts the managed ComfyUI server. |
| `test-comfyui` | Runs the dedicated test suite. |

---

## 10. User Guide: Operating the ComfyUI Backend
This section describes how a photobooth operator can set up and use the plugin.

### Setup Option A: Managed Local Server (Recommended)
Use this if you want the photobooth to handle everything automatically on a single machine with a GPU.

1. **Trigger Installation**: Run the following command in your terminal:
   ```bash
   uv run poe install-comfyui
   ```
   *This will download ~2GB of models and dependencies. The installer will automatically enable `manage_server` in your configuration upon success.*
2. **Start Photobooth**: Once installed, starting the photobooth will automatically launch the ComfyUI backend in the background.

### Setup Option B: External Server
Use this if ComfyUI is already running on another machine on your network.

1. **Disable Management**: Ensure `manage_server` is `False`.
2. **Configure Host**: Set `comfyui_host` to the IP:Port of your server (e.g., `192.168.1.50:8188`).
3. **Verify Requirements**: Ensure the external server has `comfyui-tooling-nodes` and `BiRefNet-lite` installed.

### Configuring Background Removal
1. Go to **Media Processing** -> **Background Removal**.
2. Select `comfyui_backend:birefnet_bg_remove` from the filter dropdown.
3. Test by taking a photo. The first run may take a few seconds as the model loads into VRAM.

### Troubleshooting
- **Connection Errors**: If you see "ComfyUI not reachable", check if the server is running and the `comfyui_host` is correct.
- **Logs**: Managed server logs are suppressed by default. To debug installation issues, check the terminal output of the `install-comfyui` command.
- **Performance**: High-resolution workflows may time out. Increase the `timeout` setting if you are using complex Flux or SDXL chains.
