import importlib
import inspect
import json
import re
from datetime import date
from enum import Enum
from pathlib import Path
from textwrap import dedent
import time
from types import ModuleType
from typing import Any
from pydantic import BaseModel

import pytest

from universi import regenerate_dir_to_all_versions, Field
from universi.exceptions import CodeGenerationError, InvalidGenerationInstructionError
from universi.structure import (
    AbstractVersionChange,
    Version,
    Versions,
    enum,
    schema,
    field,
)
from universi.structure.versions import AbstractVersionChange, Version, Versions
from tests._data import latest
from enum import auto

CURRENT_DIR = Path(__file__).parent


def serialize(enum: type[Enum]) -> dict[str, Any]:
    return {member.name: member.value for member in enum}


def generate_test_version_packages(*instructions, package: ModuleType = latest) -> tuple[ModuleType, ModuleType]:
    class SomeVersionChange(AbstractVersionChange):
        description = "..."
        instructions_to_migrate_to_previous_version = instructions

    regenerate_dir_to_all_versions(
        package,
        Versions(
            Version(date(2001, 1, 1), SomeVersionChange),
            Version(date(2000, 1, 1)),
        ),
    )

    from tests._data import v2000_01_01, v2001_01_01

    return v2000_01_01, v2001_01_01


def assert_field_had_changes_apply(model: type[BaseModel], attr: str, attr_value: Any):
    v2000_01_01, v2001_01_01 = generate_test_version_packages(
        schema(getattr(latest, model.__name__), field("foo").had(**{attr: attr_value}))
    )
    # For some reason it said that auto and Field were not defined, even though I was importing them
    d1 = {"auto": auto, "Field": Field}
    d2 = {"auto": auto, "Field": Field}
    # Otherwise, when re-importing and rewriting the same files many times, at some point python just starts
    # putting the module into a hardcore cache that cannot be updated by removing entry from sys.modules or
    # using importlib.reload -- only by waiting around 1.5 seconds in-between tests.
    exec(inspect.getsource(v2000_01_01), d1, d1)
    exec(inspect.getsource(v2001_01_01), d2, d2)
    assert getattr(d1[model.__name__].__fields__["foo"].field_info, attr) == attr_value
    assert getattr(d2[model.__name__].__fields__["foo"].field_info, attr) == getattr(
        getattr(latest, model.__name__).__fields__["foo"].field_info, attr
    )


def test__latest_enums_are_unchanged():
    """If it is changed -- all tests will break

    So I suggest checking this test first :)
    """
    # insert_assert(serialize(latest.EmptyEnum))
    assert serialize(latest.EmptyEnum) == {}
    # insert_assert(serialize(latest.EnumWithOneMember))
    assert serialize(latest.EnumWithOneMember) == {"a": 1}
    # insert_assert(serialize(latest.EnumWithTwoMembers))
    assert serialize(latest.EnumWithTwoMembers) == {"a": 1, "b": 2}


def test__enum_had__original_enum_is_empty():
    v2000_01_01, v2001_01_01 = generate_test_version_packages(enum(latest.EmptyEnum).had(b=7))
    # insert_assert(serialize(v2000_01_01.EmptyEnum))
    assert serialize(v2000_01_01.EmptyEnum) == {"b": 7}
    assert serialize(v2001_01_01.EmptyEnum) == serialize(latest.EmptyEnum)


def test__enum_had__original_enum_is_nonempty():
    v2000_01_01, v2001_01_01 = generate_test_version_packages(enum(latest.EnumWithOneMember).had(b=7))
    # insert_assert(serialize(v2000_01_01.EnumWithOneMember))
    assert serialize(v2000_01_01.EnumWithOneMember) == {"a": 1, "b": 7}
    assert serialize(v2001_01_01.EnumWithOneMember) == serialize(latest.EnumWithOneMember)


def test__enum_didnt_have__original_enum_has_one_member():
    v2000_01_01, v2001_01_01 = generate_test_version_packages(enum(latest.EnumWithOneMember).didnt_have("a"))
    # insert_assert(serialize(v2000_01_01.EnumWithOneMember))
    assert serialize(v2000_01_01.EnumWithOneMember) == {}
    assert serialize(latest.EnumWithOneMember) == serialize(v2001_01_01.EnumWithOneMember)


def test__enum_didnt_have__original_enum_has_two_members():
    v2000_01_01, v2001_01_01 = generate_test_version_packages(enum(latest.EnumWithTwoMembers).didnt_have("a"))
    # insert_assert(serialize(v2000_01_01.EnumWithTwoMembers))
    assert serialize(v2000_01_01.EnumWithTwoMembers) == {"b": 2}
    assert serialize(latest.EnumWithTwoMembers) == serialize(v2001_01_01.EnumWithTwoMembers)


def test__enum_had__original_schema_is_empty():
    v2000_01_01, v2001_01_01 = generate_test_version_packages(enum(latest.EmptyEnum).had(b=7))
    # insert_assert(serialize(v2000_01_01.EmptyEnum))
    assert serialize(v2000_01_01.EmptyEnum) == {"b": 7}
    assert serialize(v2001_01_01.EmptyEnum) == serialize(latest.EmptyEnum)


def test__field_existed_with__original_schema_is_empty():
    v2000_01_01, v2001_01_01 = generate_test_version_packages(
        schema(latest.EmptySchema, field("bar").existed_with(type=int, info=Field(description="hewwo")))
    )
    assert len(v2001_01_01.EmptySchema.__fields__) == 0
    # insert_assert(inspect.getsource(v2000_01_01.EmptySchema))
    assert (
        inspect.getsource(v2000_01_01.EmptySchema)
        == "class EmptySchema(BaseModel):\n    bar: int = Field(description='hewwo')\n"
    )


def test__field_existed_with__original_schema_has_a_field():
    v2000_01_01, v2001_01_01 = generate_test_version_packages(
        schema(latest.SchemaWithOneStrField, field("bar").existed_with(type=int, info=Field(description="hewwo")))
    )
    # insert_assert(inspect.getsource(v2000_01_01.SchemaWithOneStrField))
    assert (
        inspect.getsource(v2000_01_01.SchemaWithOneStrField)
        == "class SchemaWithOneStrField(BaseModel):\n    foo: str = Field(default='foo')\n    bar: int = Field(description='hewwo')\n"
    )
    # insert_assert(inspect.getsource(v2001_01_01.SchemaWithOneStrField))
    assert (
        inspect.getsource(v2001_01_01.SchemaWithOneStrField)
        == "class SchemaWithOneStrField(BaseModel):\n    foo: str = Field(default='foo')\n"
    )


def test__field_didnt_exist():
    v2000_01_01, v2001_01_01 = generate_test_version_packages(
        schema(latest.SchemaWithOneStrField, field("foo").didnt_exist)
    )
    # insert_assert(inspect.getsource(v2000_01_01.SchemaWithOneStrField))
    assert inspect.getsource(v2000_01_01.SchemaWithOneStrField) == "class SchemaWithOneStrField(BaseModel):\n    pass\n"
    # insert_assert(inspect.getsource(v2001_01_01.SchemaWithOneStrField))
    assert (
        inspect.getsource(v2001_01_01.SchemaWithOneStrField)
        == "class SchemaWithOneStrField(BaseModel):\n    foo: str = Field(default='foo')\n"
    )


# TODO: Make a list of fields we don't include with explanations and write a test that this list stays the same
@pytest.mark.parametrize(
    ["attr", "attr_value"],
    [
        ("default", 100),
        ("alias", "myalias"),
        ("title", "mytitle"),
        ("description", "mydescription"),
        ("gt", 3),
        ("ge", 4),
        ("lt", 5),
        ("le", 6),
        ("multiple_of", 7),
        ("repr", False),
    ],
)
def test__field_had__int_field(attr: str, attr_value: Any):
    """This test is here to guarantee that we can handle all parameter types we provide"""
    assert_field_had_changes_apply(latest.SchemaWithOneIntField, attr, attr_value)


@pytest.mark.parametrize(
    ["attr", "attr_value"],
    [
        ("min_length", 20),
        ("max_length", 50),
        ("regex", r"hewwo darkness"),
    ],
)
def test__field_had__str_field(attr: str, attr_value: Any):
    assert_field_had_changes_apply(latest.SchemaWithOneStrField, attr, attr_value)


@pytest.mark.parametrize(
    ["attr", "attr_value"],
    [
        ("max_digits", 12),
        ("decimal_places", 15),
    ],
)
def test__field_had__decimal_field(attr: str, attr_value: Any):
    assert_field_had_changes_apply(latest.SchemaWithOneDecimalField, attr, attr_value)


def test__field_had__default_factory():
    v2000_01_01, v2001_01_01 = generate_test_version_packages(
        schema(
            latest.SchemaWithOneIntField,
            field("foo").had(default_factory=lambda: 91),  # pragma: no cover
        )
    )

    assert v2000_01_01.SchemaWithOneIntField.__fields__["foo"].default_factory() == 91
    assert (
        v2001_01_01.SchemaWithOneIntField.__fields__["foo"].default_factory
        is latest.SchemaWithOneIntField.__fields__["foo"].default_factory
    )


def test__field_had__type():
    v2000_01_01, v2001_01_01 = generate_test_version_packages(
        schema(latest.SchemaWithOneIntField, field("foo").had(type=bytes))
    )

    assert v2000_01_01.SchemaWithOneIntField.__fields__["foo"].annotation is bytes
    assert (
        v2001_01_01.SchemaWithOneIntField.__fields__["foo"].annotation
        is latest.SchemaWithOneIntField.__fields__["foo"].annotation
    )


@pytest.mark.parametrize(
    ["attr", "attr_value"],
    [
        ("exclude", [16, 17, 18]),
        ("include", [19, 20, 21]),
        ("min_items", 10),
        ("max_items", 15),
        ("unique_items", True),
    ],
)
def test__field_had__list_of_int_field(attr: str, attr_value: Any):
    assert_field_had_changes_apply(latest.SchemaWithOneListOfIntField, attr, attr_value)


def test__field_had__float_field():
    assert_field_had_changes_apply(latest.SchemaWithOneFloatField, "allow_inf_nan", False)


def test__schema_field_had__change_to_the_same_field_type__error():
    with pytest.raises(
        InvalidGenerationInstructionError,
        match=re.escape(
            "You tried to change the type of field 'foo' to '<class 'int'>' in SchemaWithOneIntField but it already has type '<class 'int'>'"
        ),
    ):
        generate_test_version_packages(schema(latest.SchemaWithOneIntField, field("foo").had(type=int)))


def test__schema_field_had__schema_was_defined_with_pydantic_field__error():
    with pytest.raises(
        InvalidGenerationInstructionError,
        match=re.escape(
            "You have defined a Field using pydantic.fields.Field but you must use universi.Field in SchemaWithWrongFieldConstructor"
        ),
    ):
        generate_test_version_packages(schema(latest.SchemaWithWrongFieldConstructor, field("foo").had(type=int)))


def test__enum_had__same_name_as_other_value__error():
    with pytest.raises(
        InvalidGenerationInstructionError,
        match=re.escape(
            "Enum member 'a' already exists in enum 'tests._data.latestEnumWithOneMember' with the same value"
        ),
    ):
        generate_test_version_packages(enum(latest.EnumWithOneMember).had(a=1))


def test__enum_didnt_have__nonexisting_name__error():
    with pytest.raises(
        InvalidGenerationInstructionError,
        match=re.escape("Enum member 'foo' was not found in enum 'tests._data.latestEmptyEnum'"),
    ):
        generate_test_version_packages(enum(latest.EmptyEnum).didnt_have("foo"))


def test__codegen__with_deleted_source_file__error():
    Path("tests/_data/latest/another_temp1").mkdir(exist_ok=True)
    # Path("tests/_data/latest/another_temp1/__init__.py").touch()
    Path("tests/_data/latest/another_temp1/hello.py").touch()
    from tests._data.latest.another_temp1 import hello

    with pytest.raises(
        CodeGenerationError,
        match=re.escape(
            "Module <module 'tests._data.latest.another_temp1.hello' from '/home/ovsyanka/code/universi/tests/_data/latest/another_temp1/hello.py'> is not a package"
        ),
    ):
        generate_test_version_packages(enum(latest.EnumWithOneMember).didnt_have("foo"), package=hello)


def test__codegen__non_python_files__copied_to_all_dirs():
    generate_test_version_packages()
    assert json.loads(Path("tests/_data/v2000_01_01/json_files/foo.json").read_text()) == {"hello": "world"}
    assert json.loads(Path("tests/_data/v2001_01_01/json_files/foo.json").read_text()) == {"hello": "world"}


def test__codegen__non_pydantic_schema__error():
    with pytest.raises(
        CodeGenerationError,
        match=re.escape("Model <class 'tests._data.latest.NonPydanticSchema'> is not a subclass of BaseModel"),
    ):
        generate_test_version_packages(schema(latest.NonPydanticSchema, field("foo").didnt_exist))


def test__codegen__schema_that_overrides_fields_from_mro():
    v2000_01_01, v2001_01_01 = generate_test_version_packages(
        schema(latest.SchemaThatOverridesField, field("bar").existed_with(type=int, info=Field()))
    )

    # insert_assert(inspect.getsource(v2000_01_01.SchemaThatOverridesField))
    assert (
        inspect.getsource(v2000_01_01.SchemaThatOverridesField)
        == "class SchemaThatOverridesField(SchemaWithOneIntField):\n    foo: bytes = Field()\n    bar: int = Field()\n"
    )
    # insert_assert(inspect.getsource(v2001_01_01.SchemaThatOverridesField))
    assert (
        inspect.getsource(v2001_01_01.SchemaThatOverridesField)
        == "class SchemaThatOverridesField(SchemaWithOneIntField):\n    foo: bytes = Field()\n"
    )


def test__codegen__schema_defined_in_a_non_init_file():
    from tests._data.latest.some_schema import MySchema

    generate_test_version_packages(schema(MySchema, field("foo").didnt_exist))

    from tests._data.v2000_01_01.some_schema import MySchema as MySchema2000
    from tests._data.v2001_01_01.some_schema import MySchema as MySchema2001

    # insert_assert(inspect.getsource(MySchema2000))
    assert inspect.getsource(MySchema2000) == "class MySchema(BaseModel):\n    pass\n"
    # insert_assert(inspect.getsource(MySchema2001))
    assert inspect.getsource(MySchema2001) == "class MySchema(BaseModel):\n    foo: int = Field()\n"
