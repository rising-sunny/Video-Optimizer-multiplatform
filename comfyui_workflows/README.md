# ComfyUI workflow presets

Place ComfyUI workflows exported with **Save / Export (API)** in this folder.

The app looks for `presets.json` first. Each preset points to a workflow file and
optionally maps fields that should be overwritten by the pipeline.

The client also replaces these placeholders anywhere in a workflow:

```text
__PROMPT__
__NEGATIVE_PROMPT__
__WIDTH__
__HEIGHT__
__SEED__
__BATCH_SIZE__
__FILENAME_PREFIX__
__STYLE__
```

Recommended preset names for the first Vast.ai setup:

```text
historical_vertical_schnell   (FLUX Schnell - 4 steps, fast)
historical_vertical_dev       (FLUX Dev - 25 steps, high quality)
thumbnail_16x9_schnell        (FLUX Schnell horizontal)
thumbnail_16x9_dev            (FLUX Dev horizontal)
coloring_sdxl_lineart
```

Model files expected by the included workflows:

```text
ComfyUI/models/checkpoints/flux1-schnell-fp8.safetensors
  - used by historical_vertical_schnell
  - used by thumbnail_16x9_schnell

ComfyUI/models/checkpoints/flux1-dev-fp8.safetensors
  - used by historical_vertical_dev
  - used by thumbnail_16x9_dev
  - download: huggingface-cli download Kijai/flux-fp8 flux1-dev-fp8.safetensors --local-dir ComfyUI/models/checkpoints/

ComfyUI/models/checkpoints/sd_xl_turbo_1.0_fp16.safetensors
  - used by coloring_sdxl_lineart
```

Keep ComfyUI private behind an SSH tunnel when using Vast.ai, then set:

```text
COMFYUI_BASE_URL=http://127.0.0.1:8188
COMFYUI_WORKFLOW_DIR=comfyui_workflows
COMFYUI_TIMEOUT_SECONDS=300
```
