import subprocess
import logging

_nvml_available = False
_nvml_initialized = False

try:
    import pynvml
    _nvml_available = True
except ImportError:
    _nvml_available = False


def _init_nvml():
    global _nvml_initialized
    if _nvml_initialized:
        return True
    try:
        pynvml.nvmlInit()
        _nvml_initialized = True
        return True
    except Exception:
        return False


def get_gpu_temp(device_index=0):
    if _nvml_available:
        try:
            if not _init_nvml():
                return _fallback_nvidia_smi()
            handle = pynvml.nvmlDeviceGetHandleByIndex(device_index)
            temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            return int(temp)
        except Exception:
            return _fallback_nvidia_smi()
    return _fallback_nvidia_smi()


def _fallback_nvidia_smi():
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            temps = result.stdout.strip().split('\n')
            if temps and temps[0].strip().isdigit():
                return int(temps[0].strip())
    except Exception:
        pass
    return None


def shutdown_nvml():
    global _nvml_initialized
    if _nvml_available and _nvml_initialized:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass
        _nvml_initialized = False
