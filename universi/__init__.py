import importlib.metadata

from .codegen import regenerate_dir_to_all_versions
from .fields import Field
from .header import api_version_var
from .routing import VersionedAPIRouter
from .structure import Versions

__version__ = importlib.metadata.version("universi")
__all__ = ["Field", "VersionedAPIRouter", "api_version_var", "regenerate_dir_to_all_versions", "Versions"]
