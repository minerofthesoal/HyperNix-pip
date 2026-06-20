# Frameworks — `compute_framework` & `workshop`

Hardware abstraction and model-framework templates for training and speech
pipelines.

## Compute Framework (`hypernix.compute_framework`)

Abstracts CUDA, MPS, CPU, and TPU backends with automatic DDP / FSDP / ZeRO
setup.

```python
from hypernix import ComputeFramework, ComputeArch

fw = ComputeFramework(
    arch=ComputeArch.CUDA,
    local_rank=0,
    world_size=1,
    use_ddp=False,
    use_fsdp=False,
    zero_stage=0,
)
model = fw.prepare_model(model)
fw.backward(loss)
fw.step(optimizer)
```

Pair with `lazy_suzan` for decentralized multi-GPU gradient compression on
machines without NVLink.

## Workshop (`hypernix.workshop`)

Pre-built templates for TTS, ASR, LLM, and Vision models plus speech pipelines.

| Engine | Purpose |
|---|---|
| `TTSEngine` | Text-to-speech synthesis |
| `ASREngine` | Automatic speech recognition |
| `ASRToTTS` | Direct speech-to-speech |
| `ASRToLLMToTTS` | Full conversational pipeline |

```bash
hypernix pipeline --audio input.wav --asr nano-whisper --llm qwen3.5-1b --tts nano-tacotron
hypernix assistant --voice
```

Supports 30+ architectures (Gemma 4, Qwen3.5, Phi-4, DeepSeek-V2.5, …) via
`FrameworkConfig` and the nano-nano collection.

See also: [Workshop.md](Workshop.md), [Training.md](Training.md).
