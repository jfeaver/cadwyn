import importlib
import inspect
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

Sentinel: Any = object()


def get_another_version_of_cls(cls_from_old_version: type[Any], new_version_dir: Path) -> None:
    # version_dir = /home/ovsyanka/package/companies/v2021_01_01

    module_from_old_version = sys.modules[cls_from_old_version.__module__]
    module = get_another_version_of_module(module_from_old_version, new_version_dir)
    return getattr(module, cls_from_old_version.__name__)


# TODO: WHat if the user puts model in __init__.py?
def get_another_version_of_module(module_from_old_version: ModuleType, new_version_dir: Path):
    file = inspect.getsourcefile(module_from_old_version)
    if file is None:
        raise Exception(f"Model {module_from_old_version} is not defined in a file")

    # /home/ovsyanka/package/companies/latest/__init__.py
    file = Path(file)
    if file.name == "__init__.py":
        # /home/ovsyanka/package/companies/latest/
        file = file.parent
    # /home/ovsyanka/package/companies
    root_dir = new_version_dir.parent
    # latest/schemas
    relative_file = file.relative_to(root_dir).with_suffix("")
    # ['latest', 'schemas']
    relative_file_parts = relative_file.parts
    # package.companies.latest.schemas.Payable
    model_python_path = module_from_old_version.__name__
    # ['package', 'companies', 'latest', 'schemas']
    model_split_python_path = model_python_path.split(".")

    # ['package', 'companies', 'latest', 'schemas']
    #                           ^^^^^^
    #                           index = -2

    # ['package', 'companies', 'v2021_01_01', 'schemas']
    model_split_python_path[-len(relative_file_parts)] = new_version_dir.name
    # package.companies.v2021_01_01.schemas
    new_model_module_python_path = ".".join(model_split_python_path)
    module = importlib.import_module(new_model_module_python_path)
    return module
