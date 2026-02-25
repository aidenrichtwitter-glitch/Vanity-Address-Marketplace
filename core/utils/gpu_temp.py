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


def get_gpu_name(device_index=0):
    if _nvml_available:
        try:
            if not _init_nvml():
                return _fallback_gpu_name()
            handle = pynvml.nvmlDeviceGetHandleByIndex(device_index)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8", errors="replace")
            return name.strip()
        except Exception:
            return _fallback_gpu_name()
    return _fallback_gpu_name()


def _fallback_gpu_name():
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            names = result.stdout.strip().split('\n')
            if names and names[0].strip():
                return names[0].strip()
    except Exception:
        pass
    return None


_GPU_TEMP_LIMITS = {
    "4090": 75,
    "4080": 78,
    "4070 ti super": 78,
    "4070 ti": 78,
    "4070 super": 78,
    "4070": 78,
    "4060 ti": 78,
    "4060": 78,
    "3090 ti": 73,
    "3090": 73,
    "3080 ti": 73,
    "3080": 73,
    "3070 ti": 75,
    "3070": 75,
    "3060 ti": 75,
    "3060": 75,
    "3050": 75,
    "2080 ti": 72,
    "2080 super": 72,
    "2080": 72,
    "2070 super": 73,
    "2070": 73,
    "2060 super": 73,
    "2060": 73,
    "1080 ti": 72,
    "1080": 72,
    "1070 ti": 72,
    "1070": 72,
    "1060": 72,
    "a6000": 78,
    "a5000": 78,
    "a4000": 78,
    "a100": 78,
    "rx 7900": 75,
    "rx 7800": 75,
    "rx 7700": 75,
    "rx 7600": 75,
    "rx 6900": 75,
    "rx 6800": 75,
    "rx 6700": 75,
    "rx 6600": 75,
}


def get_recommended_max_temp(gpu_name=None):
    if gpu_name is None:
        gpu_name = get_gpu_name()
    if gpu_name is None:
        return 80

    name_lower = gpu_name.lower()
    for key in sorted(_GPU_TEMP_LIMITS.keys(), key=len, reverse=True):
        if key in name_lower:
            return _GPU_TEMP_LIMITS[key]
    return 80


def shutdown_nvml():
    global _nvml_initialized
    if _nvml_available and _nvml_initialized:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass
        _nvml_initialized = False
