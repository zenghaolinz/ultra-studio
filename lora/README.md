# Image LoRA Models

Place Flux image-generation LoRA models here.

- Put Flux 4B LoRAs in `4b/`.
- Put Flux 9B LoRAs in `9b/`.
- A file placed directly in this directory is detected only when its filename includes `4B` or `9B`.
- Supported formats: `.safetensors`, `.pt`, `.ckpt`.

The application exposes only the LoRAs compatible with the currently selected Flux quality mode. When selected for generation or editing, a hard link with an `ultra_studio_4b_` or `ultra_studio_9b_` prefix is created in ComfyUI's `models/loras/` directory so the model file is not duplicated and ComfyUI can refresh its model list reliably.
