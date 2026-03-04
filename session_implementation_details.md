# Session Implementation Details: ComfyUI Backend Plugin

This document provides a highly detailed, comprehensive technical reference for the `comfyui_backend` plugin implemented for the `photobooth-app`. It aims to serve as a complete guide for maintaining, extending, or debugging the plugin in the future.

---

## Session Accomplishments

This section captures the full scope of what was built and refined during the implementation session — from the initial request to replace a background removal model, all the way to a robust, high-performance, and deeply integrated AI generation backend.

### 1. Core Architecture & Workflow Conversion
Built an elegant `BaseFilter` plugin that seamlessly intercepts the photobooth's image pipeline. Implemented on-the-fly workflow conversion: users can save workflows directly from the ComfyUI frontend web UI, drop the `.json` into the `workflows/` folder, and the plugin automatically manages node mapping and image injection via the `__INPUT_B64__` sentinel.

### 2. Custom Transport Nodes
Created the `photobooth_nodes` extension (`ETN_SaveImageBase64`) for ComfyUI. This solves ComfyUI's biggest API headache by allowing high-speed Base64 image transport directly over the REST response, entirely bypassing disk writes or WebSocket plumbing.

### 3. Zero-Touch Installation (`server_manager.py`)
Built a native installer that handles downloading ComfyUI, creating isolated `.venv` environments, fetching custom node dependencies, and deploying bundled nodes. Avoided `git` entirely by using GitHub ZIP archives. Fortified with cross-platform support (Linux/Windows venv paths) and a safe `uv` → `pip` fallback.

### 4. UX & Performance Optimizations
- **In-memory LRU Cache**: A blazing-fast caching layer (`MAX_CACHE=5`, keyed by workflow name + image hash) makes switching back to a previously applied filter instantaneous.
- **Gallery Dominance**: Patched the media processing sequence to sort `ComfyuiBackend.*` filters to the top of the admin UI list.
- **Preview Fast-Path**: Skips ComfyUI payloads on small live-view frames to keep the booth running at 30 fps.

### 5. Hardening & Code Review Fixes
Addressed 12 code review findings including:
- `NameError` from `uv_path`/`pip_path` scope bug in `install()`
- Shared class-level `_process` instance bug in `ServerManager`
- Silent timeouts when workflows complete without producing image output
- Windows venv path incompatibility
- `progress_cb` dead API parameter
- Hardcoded magic number `800` in preview fast-path
- `install_cli.py` silently mutating config without user awareness
- Hardcoded `"ComfyuiBackend."` prefix string in `image.py`
- Fragile positional `widgets_values` parsing in `utils.py`
- Undocumented `__INPUT_B64__` sentinel convention
- Missing integrity checks for downloaded ZIP archives
- Missing explanatory comment for `ETN_LoadImageBase64` provenance

### 6. Documentation & Tests
Added comprehensive unit and integration tests covering plugin init, filter scanning, preview fast-path, health checks, workflow execution, stats, install logic, and error handling. Captured the full architecture, network behaviour, and troubleshooting guide in this document.

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

### Settings Included
- `comfyui_host` (str): Network address of the ComfyUI server (default: `127.0.0.1:18188`).
- `manage_server` (bool): Dictates whether the plugin should take ownership of spawning and terminating a local ComfyUI subprocess.
- `server_path` (Path): Target directory for local ComfyUI installations (default: `data/comfyui/`).
- `timeout` (int): Maximum wait time for image inference in seconds to prevent pipeline blocking indefinitely.
- `add_userselectable_filter` & `userselectable_workflows`: Toggles and defines which workflows populate the front-end user interfaces.

---

## 3. Server Management & Provisioning (`server_manager.py` & `resources.py`)
To enable an "out-of-the-box" experience without requiring users to manually configure a Python environment or install `git`, the plugin provides a self-managed server installation path.

### Zip-Based Provisioning
Instead of `git clone`, the `ServerManager` uses the GitHub archive API (`/archive/refs/tags/v0.15.1.zip`) to download ComfyUI and custom nodes.
- Extracts ZIPs directly into RAM via `io.BytesIO`.
- **Branch/Tag Fallback**: `_download_zip` intelligently tries the provided `ref` (tag), then falls back to `main` and `master` branches if 404s occur.
- **Path Traversal Protection**: Every ZIP entry is checked for `..` and leading `/` before extraction.
- **Dependencies Installed**:
  - `ComfyUI` (pinned to `v0.15.1`)
  - `comfyui-tooling-nodes` (for Base64 transport via `ETN_LoadImageBase64`)
  - `ComfyUI-RMBG` (for background removal; handles its own model downloads on first run)

### Subprocess Execution
- Starts `main.py` as an asynchronous subprocess targeting the provisioned `.venv` (`bin/python` on POSIX, `Scripts/python.exe` on Windows).
- Stores the `subprocess.Popen` object as an **instance** attribute (not class-level) to guarantee `stop()` reliably terminates the correct process.
- **Critical Safety Feature**: `install()` is purposefully disconnected from `init()`. It must be triggered manually via the CLI or admin button to prevent the app freezing while downloading gigabytes of models on startup.
- **Custom Node Deployment**: The bundled `photobooth_io.py` (containing `ETN_SaveImageBase64`) is deployed to `custom_nodes/photobooth_nodes/` alongside a valid `__init__.py` so ComfyUI correctly registers the module.

---

## 4. API Client Integration (`client.py`)
All communication with ComfyUI is strictly stateless HTTP/REST, avoiding complex WebSocket lifecycle issues during synchronous image pipeline steps.

### Health Checking
Uses a rapid 2-second timeout against `/system_stats`. This endpoint is fast and does not require touching the GPU, making `check_health()` instantaneous.

### Workflow Execution Lifecycle
1. **Serialization**: Converts the inbound `PIL.Image` into a Base64-encoded PNG string.
2. **Injection**: Reads the workflow JSON and performs a recursive string replacement for `__INPUT_B64__`, placing the image directly into the `ETN_LoadImageBase64` node.
3. **Submission**: POSTs to `/prompt` and receives a `prompt_id`.
4. **Polling**: Enters a polling loop against `/history/{prompt_id}`.
5. **Extraction**: Once finished, parses the JSON tree for `ETN_SaveImageBase64` outputs, decodes the returned Base64 string, and reconstructs the `PIL.Image`.

### Error Handling & Logging
- Translates `500 Internal Server Error` responses into detailed Python exceptions with the response body included.
- Hard-limits the polling loop to the user-defined `timeout`.
- Prevents silent infinite waits: if the job is marked `completed` but produced no `images` array (e.g., a node error), it raises a clear `RuntimeError` immediately rather than looping to timeout.
- Sanitizes debug logs to prevent massive Base64 strings from flooding terminal output.

---

## 5. Workflows

Workflows are portable JSON files saved directly from the ComfyUI web UI. Because all image I/O is encapsulated in the JSON node graph, the backend Python code never needs to understand *what* ComfyUI is doing — only *how* to feed it an image and get one back.

### Current Bundled Workflows
- **`birefnet_bg_remove.json`**: Uses the BiRefNet model for highly accurate subject segmentation and background removal.
- **`rmbg_bg_remove.json`**: Uses the RMBG model as a lighter-weight alternative for background removal.

### How to Add a Custom Workflow

One of the biggest architectural wins is that the Photobooth doesn't need to understand anything about what your AI is doing. This means you can build completely new AI styles — turning photos into cartoons, applying vintage film effects, swapping backgrounds with generated scenes — and the Photobooth will adopt them as standard filters automatically.

#### Step 1 — Build Your Workflow in the ComfyUI GUI

Open the ComfyUI web interface (e.g. `http://localhost:18188`) and build your custom node graph exactly as you want it (e.g. `Load Image → ControlNet → KSampler → VAE Decode`). Test it until the output looks correct.

#### Step 2 — Add the Tooling Nodes (The Magic Bridge)

The Photobooth needs to inject the camera picture into your workflow and extract the result without saving to disk. Replace the standard load/save nodes with:

| Standard Node | Replacement | Source |
|---|---|---|
| `Load Image` | `ETN_LoadImageBase64` | `comfyui-tooling-nodes` (auto-installed) |
| `Save Image` | `ETN_SaveImageBase64` | `photobooth_nodes` (bundled) |

**Crucial step for the input node**: Leave the text box on `ETN_LoadImageBase64` completely **empty**. The backend detects the empty value and automatically injects the camera picture as a Base64 string at runtime via the `__INPUT_B64__` sentinel.

#### Step 3 — Save the Workflow to `.json`

Once your graph works correctly, click the standard **Save** button in the ComfyUI web menu. ComfyUI will download a `.json` file (e.g. `comic_book_style.json`).

> **Note**: You do not need to use a special "Save (API format)" button. The `convert_frontend_to_api` parser in `utils.py` converts the standard UI save format automatically at runtime.

#### Step 4 — Drop it into the Workflows Folder

Place the `.json` file into:

```
src/photobooth/plugins/comfyui_backend/workflows/
```

#### Step 5 — Restart the Photobooth

On startup the plugin runs `mp_avail_filter`, scans `workflows/`, discovers your new file, and automatically creates a filter named `ComfyuiBackend.comic_book_style`. Navigate to **Admin → Media Processing → Filter** and your workflow will appear at the top of the list, ready to use.

---

## 6. Workflow Conversion: Frontend → API Format (`utils.py`)

The `convert_frontend_to_api()` function bridges the gap between the JSON format produced by the ComfyUI web UI's Save button and the API prompt format accepted by `/prompt`.

### What It Does
1. Builds a `links_map` from the `links` array, mapping each `link_id` to its `[origin_node_id, origin_output_index]`.
2. Iterates over all nodes, resolving connected inputs via the links map.
3. For nodes with `widgets_values` (static, non-linked values), maps positional values to named keys for known node types: `ETN_SaveImageBase64`, `ETN_LoadImageBase64`, `BiRefNetRMBG`, `RMBG`.
4. Preserves the `__photobooth_output_node__` key if present, for fast-path output extraction.

> **Note on fragility**: The `widgets_values` mapping is positional and tied to the widget order of specific node versions. If an upstream node author changes widget ordering in an update, the mapping may silently produce wrong parameter values. A comment in the source records the expected node version for each mapping.

---

## 7. Verification and Test Suite Configuration
A robust suite is maintained in `src/tests/tests/plugins/`.

- **Mocking**: Uses `pytest-httpserver` to simulate ComfyUI API responses locally without loading PyTorch.
- **Test Scenarios**:
  - `test_plugin_init`: Ensures class instantiation and config loading.
  - `test_mp_avail_filter`: Validates import-time scanning against temporary directories.
  - `test_preview_fast_path`: Proves that preview frames return immediately without HTTP calls.
  - `test_client_check_health` & `test_client_run_workflow`: Validates Base64 packaging, network requests, and payload unpacking.
  - `test_get_stats`: Checks `GenericStats` typing correctness.
  - `test_server_manager_install_logic`: Uses an in-memory simulated GitHub ZIP payload to test extraction and rename logic.
  - `test_client_error_handling`: Checks 500 error catching and timeout behaviour.
  - `test_comfyui_converter`: Validates frontend-to-API conversion for known node types.
  - `test_comfyui_logic`: Covers cache behaviour, image hashing, and workflow loading.

---

## 8. Known Limitations & Future Enhancements
- **Model Checksums**: The `resources.py` manifest includes a `skip_hash` attribute. Implementing SHA256 verification on ZIP archive downloads (in addition to the existing single-file verification) is recommended for security.
- **`widgets_values` Versioning**: The positional widget mapping in `utils.py` is tied to specific node versions. A version-pinning or schema-validation approach would make this more robust.
- **WebSocket Feedback**: While `/history` polling is simple and reliable, large workflows might benefit from WebSocket tracking for fine-grained progress bars if the PhotoBooth UI supports it in the future.
- **`progress_cb` in `install()`**: The parameter is declared but not yet implemented. It should either be wired to log progress during long downloads or removed from the public API.

---

## 9. Change Log

### Fix: Memory Exhaustion During Large Downloads
- **Status**: ✅ Completed
- Replaced `.read()` with chunked writing (`r.read(8192)`) in `_download_file`. ZIP downloads (~20–50 MB) still buffer in RAM; safetensor downloads (2 GB+) are fully streamed to disk.

### Fix: URL and Branch Brittleness (404s)
- **Status**: ✅ Completed
- Updated ComfyUI organisation to `Comfy-Org`. Added branch fallback logic (`main` → `master`) and support for tag pinning (`v0.15.1`).

### Fix: Isolated Virtual Environment for ComfyUI
- **Status**: ✅ Completed
- `install()` now creates a `.venv` and uses `uv pip install` to isolate dependencies, keeping the photobooth's core environment lean.

### Fix: Subprocess Uses Correct Python
- **Status**: ✅ Completed
- `start()` explicitly targets `bin/python` (or `Scripts/python.exe` on Windows) inside the provisioned `.venv`.

### Fix: `NameError` for `uv_path`/`pip_path`
- **Status**: ✅ Completed
- Both variables are now initialised at the top of `install()` before any conditional blocks.

### Fix: Shared Class-Level `_process` Attribute
- **Status**: ✅ Completed
- `_process` is now assigned as an instance attribute in `__init__`, preventing cross-instance contamination.

---

## 10. Helper Scripts

### Shell Scripts (Recommended)
Run from the project root:

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

## 11. User Guide: Operating the ComfyUI Backend

### Setup Option A: Managed Local Server (Recommended)
Use this if you want the photobooth to handle everything automatically on a single machine with a GPU.

1. **Trigger Installation**:
   ```bash
   uv run poe install-comfyui
   ```
   This downloads ~2 GB of models and dependencies. The installer will automatically enable `manage_server` in your configuration upon success (a confirmation message is displayed before the config is written).
2. **Start Photobooth**: Starting the photobooth will automatically launch the ComfyUI backend in the background.

### Setup Option B: External Server
Use this if ComfyUI is already running on another machine on your network.

1. **Disable Management**: Ensure `manage_server` is `False`.
2. **Configure Host**: Set `comfyui_host` to the IP:Port of your server (e.g. `192.168.1.50:18188`).
3. **Verify Requirements**: Ensure the external server has `comfyui-tooling-nodes` and the photobooth custom nodes installed, plus the models required by your chosen workflows.

### Troubleshooting
- **Connection Errors**: If you see "ComfyUI not reachable", verify the server is running and `comfyui_host` is correct.
- **Workflow Errors**: If the job completes but no image is returned, check the ComfyUI console for node errors. The backend will now raise a clear `RuntimeError` rather than silently timing out.
- **Performance**: High-resolution or multi-model workflows may exceed the default `timeout`. Increase the `timeout` setting if you are using complex Flux or SDXL chains.
- **Logs**: Managed server stdout/stderr is suppressed by default. To debug, run `./scripts/comfyui.sh` directly and watch the terminal.
