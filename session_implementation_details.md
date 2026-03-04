# Session Implementation Details: ComfyUI Backend Plugin

This document provides a highly detailed, comprehensive technical reference for the `comfyui_backend` plugin implemented for the `photobooth-app`. It aims to serve as a complete guide for maintaining, extending, or debugging the plugin in the future.

---

## 1. Plugin Architecture & Hook Engine Integration
The plugin is structured as an optional extension that hooks into the `photobooth-app`'s core `pluggy` architecture. It subclasses `BaseFilter` to seamlessly participate in the image processing pipeline.

### Core Hooks Implemented
- **`mp_avail_filter`**: Discovers available filters at module import time. To avoid network latency or startup crashes when a ComfyUI server is down, this scans the local `workflows/` directory for `.json` files.
- **`mp_userselectable_filter`**: Returns a subset of available workflows that are allowed to be selected by the end user via the UI, determined by the `userselectable_workflows` config value.
- **`mp_filter_pipeline_step`**: The main execution block. Intercepts the image frame. Crucially handles a fast-path (`if preview: return None`) to ensure that heavy network payloads and inference times do not block the 15-30 FPS live-view feed.
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
- Intelligently renames the top-level extraction folder (`RepoName-main`) to the correct destination folder name (`dest`).
- **Dependencies Installed**:
  - Base `ComfyUI`
  - `comfyui-tooling-nodes` (for base64 transport)
  - `ComfyUI-BiRefNet-lite` (for background removal)
  - `BiRefNet-general.safetensors` model file.

### Subprocess Execution
- Starts the `main.py` entry point as an asynchronous subprocess.
- Captures the `subprocess.Popen` object to guarantee that `stop()` can reliably terminate the server when the photobooth shuts down.
- **Critical Safety Feature**: `install()` is purposefully disconnected from `init()`. It must be triggered manually via a CLI script or admin button to prevent the app from completely freezing while downloading gigabytes of models on startup.

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

### Error Handling
- Translates `500 Internal Server Error` responses into detailed Python exceptions.
- Hard limits the polling loop matching the user-defined `timeout`.

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

## 8. Audited Gaps & Technical Debt (Actionable Improvements)
Following a comprehensive audit of the implemented session, the following technical gaps were identified as highly recommended improvements before full production deployment:

### 1. Memory Exhaustion Risk During Large Downloads
In `server_manager.py`, the `_download_file` and `_download_zip` wrapper methods currently use `urllib.request.urlopen(url).read()`, which buffers the entire file into RAM before writing to disk.
- **Risk**: Downloading a 2GB `.safetensors` model (like BiRefNet) will consume 2GB of RAM, potentially causing `MemoryError` and crashing the photobooth application on lower-end hardware (e.g., Raspberry Pi or 8GB RAM mini-PCs).
- **Fix**: Replace `.read()` with chunked writing using `shutil.copyfileobj(response, file)` or iterate over chunks (`response.read(8192)`).

### 2. Lack of Isolated Virtual Environment for ComfyUI
The `install()` method downloads the ComfyUI source code but skips provisioning an isolated Python virtual environment (`venv`).
- **Risk**: ComfyUI requires heavy dependencies (PyTorch, torchvision, torchaudio, etc.) that conflict with or unnecessarily bloat the core `photobooth-app` environment. 
- **Fix**: Enhance `install()` to execute `python -m venv .venv` inside the `server_path`, followed by executing the venv's pip: `path/to/.venv/bin/pip install -r requirements.txt`.

### 3. Subprocess Execution Uses System Python
In `start()`, the subprocess command is hardcoded to `cmd = ["python", "main.py", "--listen", "127.0.0.1"]`.
- **Risk**: This executes whatever `python` is currently in the system PATH (often the photobooth's environment). Since the photobooth environment lacks `torch`, ComfyUI will immediately fail to start.
- **Fix**: The command should explicitly target the provisioned virtual environment: `cmd = [str(self.server_path / ".venv" / "bin" / "python"), "main.py", "--listen", "127.0.0.1"]`.

### 4. Missing Progress Feedback for Long Installations
The `install()` method uses `logger.info`, but downloading gigabytes of data can take several minutes.
- **Risk**: The user or admin UI has no visibility into the download progress, potentially leading to premature aborts.
- **Fix**: Implement a tqdm-style progress hook or expose the percentage via the optional `progress_cb` callback stubbed in the `install()` method signature.
