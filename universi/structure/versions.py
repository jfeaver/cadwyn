from contextvars import ContextVar
import datetime
import functools
from collections.abc import Callable, Sequence
from enum import Enum
from typing import Any, ClassVar, ParamSpec, TypeAlias, TypeVar, overload

from fastapi.routing import _prepare_response_content
from universi.exceptions import UniversiStructureError

from universi.header import api_version_var
from universi.structure.endpoints import AlterEndpointSubInstruction
from universi.structure.enums import AlterEnumSubInstruction

from .._utils import Sentinel
from .common import Endpoint, VersionedModel
from .responses import AlterResponseInstruction
from .schemas import AlterSchemaInstruction

_P = ParamSpec("_P")
_R = TypeVar("_R")
VersionDate: TypeAlias = datetime.date


class AbstractVersionChange:
    side_effects: ClassVar[bool] = False
    description: ClassVar[str] = Sentinel
    instructions_to_migrate_to_previous_version: ClassVar[
        Sequence[AlterSchemaInstruction | AlterEndpointSubInstruction | AlterEnumSubInstruction]
    ] = Sentinel
    alter_schema_instructions: ClassVar[Sequence[AlterSchemaInstruction]] = Sentinel
    alter_enum_instructions: ClassVar[Sequence[AlterEnumSubInstruction]] = Sentinel
    alter_endpoint_instructions: ClassVar[Sequence[AlterEndpointSubInstruction]] = Sentinel
    alter_response_instructions: ClassVar[dict[Endpoint, AlterResponseInstruction]] = Sentinel

    def __init_subclass__(cls) -> None:
        assert isinstance(cls.side_effects, bool)
        if cls.description is Sentinel:
            raise UniversiStructureError(f"Version change description is not set on '{cls.__name__}' but is required.")
        if cls.instructions_to_migrate_to_previous_version is Sentinel:
            raise UniversiStructureError(
                f"Attribute 'instructions_to_migrate_to_previous_version' is not set on '{cls.__name__}' but is required.",
            )
        if not isinstance(cls.instructions_to_migrate_to_previous_version, Sequence):
            raise UniversiStructureError(
                f"Attribute 'instructions_to_migrate_to_previous_version' must be a sequence in '{cls.__name__}'.",
            )
        for attr_name, attr_value in cls.__dict__.items():
            if not isinstance(attr_value, AlterResponseInstruction) and attr_name not in {
                "description",
                "side_effects",
                "instructions_to_migrate_to_previous_version",
                "__module__",
                "__doc__",
            }:
                raise UniversiStructureError(
                    f"Found: '{attr_name}' attribute in {cls.__name__}. Only migration instructions are allowed in version change classes.",
                )

        cls.alter_schema_instructions = []
        cls.alter_enum_instructions = []
        cls.alter_endpoint_instructions = []
        for alter_instruction in cls.instructions_to_migrate_to_previous_version:
            if isinstance(alter_instruction, AlterSchemaInstruction):
                cls.alter_schema_instructions.append(alter_instruction)
            elif isinstance(alter_instruction, AlterEnumSubInstruction):
                cls.alter_enum_instructions.append(alter_instruction)
            else:
                cls.alter_endpoint_instructions.append(alter_instruction)
        cls.alter_response_instructions = {
            endpoint: instruction
            for instruction in cls.__dict__.values()
            if isinstance(instruction, AlterResponseInstruction)
            for endpoint in instruction.endpoints
        }
        repetitions = set()
        for alter_instruction in cls.alter_schema_instructions:
            assert (
                alter_instruction.schema not in repetitions
            ), f"Model {alter_instruction.schema} got repeated. Please, merge these instructions."
            repetitions.add(alter_instruction.schema)

        if cls.mro() != [cls, AbstractVersionChange, object]:
            raise TypeError(
                f"Can't subclass {cls.__name__} as it was never meant to be subclassed.",
            )

    def __init__(self) -> None:
        raise TypeError(
            f"Can't instantiate {self.__class__.__name__} as it was never meant to be instantiated.",
        )


class Version:
    def __init__(
        self,
        date: VersionDate,
        *version_changes: type[AbstractVersionChange],
    ) -> None:
        self.date = date
        self.version_changes = version_changes


class Versions:
    def __init__(self, *versions: Version, api_version_var: ContextVar[VersionDate | None] = api_version_var) -> None:
        self.versions = versions
        self.api_version_var = api_version_var
        if sorted(versions, key=lambda v: v.date, reverse=True) != list(versions):
            raise ValueError(
                "Versions are not sorted correctly. Please sort them in descending order.",
            )

    @functools.cached_property
    def versioned_schemas(self) -> dict[str, type[VersionedModel]]:
        return {
            instruction.schema.__module__ + instruction.schema.__name__: instruction.schema
            for version in self.versions
            for version_change in version.version_changes
            for instruction in version_change.alter_schema_instructions
        }

    @functools.cached_property
    def versioned_enums(self) -> dict[str, type[Enum]]:
        return {
            instruction.enum.__module__ + instruction.enum.__name__: instruction.enum
            for version in self.versions
            for version_change in version.version_changes
            for instruction in version_change.alter_enum_instructions
        }

    @functools.cached_property
    def _version_changes_to_version_mapping(self) -> dict[type[AbstractVersionChange], VersionDate]:
        return {version_change: version.date for version in self.versions for version_change in version.version_changes}

    def is_active(self, version_change: type[AbstractVersionChange]) -> bool:
        api_version = self.api_version_var.get()
        if api_version is None:
            return False
        return self._version_changes_to_version_mapping[version_change] <= api_version

    # TODO: It might need caching for iteration to speed it up
    def data_to_version(
        self,
        endpoint: Endpoint,
        data: dict[str, Any],
        version: VersionDate,
    ) -> dict[str, Any]:
        for v in self.versions:
            if v.date <= version:
                break
            for version_change in v.version_changes:
                if endpoint in version_change.alter_response_instructions:
                    version_change.alter_response_instructions[endpoint](data)
        return data

    @overload
    def versioned(self, endpoint: Endpoint[_P, _R]) -> Endpoint[_P, _R]:
        ...

    @overload
    def versioned(
        self,
        endpoint: None = None,
    ) -> Callable[[Endpoint[_P, _R]], Endpoint[_P, _R]]:
        ...

    def versioned(
        self,
        endpoint: Endpoint | None = None,
    ) -> Callable[[Endpoint[_P, _R]], Endpoint[_P, _R]] | Endpoint[_P, _R]:
        if endpoint is not None:

            @functools.wraps(endpoint)
            async def decorator(*args: _P.args, **kwargs: _P.kwargs) -> _R:
                return await self._convert_endpoint_response_to_version(
                    endpoint,
                    args,
                    kwargs,
                )

            decorator.func = endpoint  # pyright: ignore[reportGeneralTypeIssues]
            return decorator

        def wrapper(endpoint: Endpoint[_P, _R]) -> Endpoint[_P, _R]:
            @functools.wraps(endpoint)
            async def decorator(*args: _P.args, **kwargs: _P.kwargs) -> _R:
                return await self._convert_endpoint_response_to_version(
                    endpoint,
                    args,
                    kwargs,
                )

            decorator.func = endpoint  # pyright: ignore[reportGeneralTypeIssues]
            return decorator

        return wrapper

    async def _convert_endpoint_response_to_version(
        self,
        endpoint: Endpoint,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        response = await endpoint(*args, **kwargs)
        api_version = self.api_version_var.get()
        if api_version is None:
            return response
        # TODO We probably need to call this in the same way as in fastapi instead of hardcoding exclude_unset.
        # We have such an ability if we force passing the route into this wrapper. Or maybe not... Important!
        response = _prepare_response_content(response, exclude_unset=False)
        return self.data_to_version(endpoint, response, api_version)
