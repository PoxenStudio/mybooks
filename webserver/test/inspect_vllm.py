import os
os.environ["VLLM_TARGET_DEVICE"] = "cpu"
import vllm.platforms
print(f"Current platform: {vllm.platforms.current_platform}")
try:
    from vllm.platforms.cpu import CpuPlatform
    print("CpuPlatform found")
except ImportError:
    print("CpuPlatform NOT found")

try:
    import torch
    print(f"Torch version: {torch.__version__}")
    print(f"Torch cuda available: {torch.cuda.is_available()}")
except ImportError:
    print("Torch not found")
