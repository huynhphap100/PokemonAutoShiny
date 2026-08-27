# Minimal fast hook for PyTorch (bypasses the 3-minute submodule scan)
from PyInstaller.utils.hooks import collect_data_files

hiddenimports = [
    "torch",
    "torch.nn",
    "torch.nn.functional",
    "torch.autograd",
    "torch.serialization",
    "torchvision",
    "torchvision.transforms",
    "torchvision.transforms.functional",
]

# Torch data without C++ headers or tests
raw_datas = collect_data_files("torch")
datas = [
    item for item in raw_datas
    if not any(k in item[0].replace("\\", "/").lower() for k in ["/include/", "/test/", "/share/", "/docs/"])
]
