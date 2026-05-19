"""Walk the installed `anyscale` wheel's docgen registry and emit reference.json.

The introspector imports `ALL_MODULES` from the installed `anyscale` package
and extracts all the data the renderer needs (CLI command shapes, SDK
signatures, model fields, examples, legacy SDK/model markdown). It writes one
JSON file under docs/reference/_data/ that the renderer consumes.

Usage:
    python -m docgen.introspect <output_json_path>
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
import sys
from dataclasses import fields as dataclass_fields
from typing import Any, Callable, Dict, List, Optional

from util import escape_mdx_content, strip_sphinx_docstring, type_to_string


SCHEMA_VERSION = 1


# Hide semantics
# ==============
#
# A wheel can mark whole CLI commands, SDK methods, model classes, or entire
# docgen modules as hidden so they remain functional but absent from the
# generated reference. This mirrors the parameter-level filter already in
# place (`param["hidden"]` for CLI options, `__hidden_args__` for SDK args
# — see anyscale/product PR #39685).
#
# The signals introspect honors:
#   - CLI command:  `click.Command.hidden` (Click's native attribute)
#   - SDK method:   `__hidden__` magic attribute, set by `hidden=True` on the
#                   `@sdk_command` / `@sdk_docs` / `@sdk_command_v2` /
#                   `@deprecated_sdk_command` decorators
#   - Model class:  `__hidden__` class attribute (set directly on the class)
#   - Module:       `Module.hidden` boolean field
#
# All getattr() lookups fall back to False so older wheels stay introspectable.
# A non-hidden SDK function that references a hidden model raises during
# extraction, since dropping the model would leave a dangling anchor link.


def _is_hidden_cli_command(c: Any) -> bool:
    return bool(getattr(c, "hidden", False))


def _is_hidden_sdk_command(c: Any) -> bool:
    return bool(getattr(c, "__hidden__", False))


def _is_hidden_model(t: Any) -> bool:
    return bool(getattr(t, "__hidden__", False))


def _is_hidden_module(m: Any) -> bool:
    return bool(getattr(m, "hidden", False))


def _collect_examples(t: Any) -> Dict[str, Optional[str]]:
    return {
        "yaml": getattr(t, "__doc_yaml_example__", None),
        "python": getattr(t, "__doc_py_example__", None),
        "cli": getattr(t, "__doc_cli_example__", None),
    }


def _build_model_index(
    all_modules: List[Any], *, allow_duplicates: bool = False
) -> Dict[str, str]:
    """Map model class name to the filename of the module that owns it.

    Raises if two modules export a model with the same class name. The link
    registry uses the bare class name as the ID (`model/<ModelName>`) on the
    assumption that names are globally unique; making this explicit prevents
    silent overwrites.

    Set `allow_duplicates=True` to downgrade the error to a stderr warning
    and keep the first occurrence — used when introspecting older anyscale
    wheels that registered the same model class in two docgen modules
    (e.g. `CloudDeployment` in both compute-config-api and cloud across
    0.26.48-0.26.52).
    """
    index: Dict[str, str] = {}
    duplicates: List[str] = []
    for m in all_modules:
        for model in m.models or []:
            name = model.__name__
            if name in index and index[name] != m.filename:
                msg = (
                    f"Model class name '{name}' is exported by both "
                    f"{index[name]} and {m.filename}. Names must be globally "
                    f"unique across docgen modules."
                )
                if allow_duplicates:
                    duplicates.append(msg)
                    continue  # keep the first occurrence
                raise ValueError(msg)
            index[name] = m.filename
    if duplicates:
        print(
            "Warning: duplicate model names (keeping first occurrence):",
            file=sys.stderr,
        )
        for msg in duplicates:
            print(f"  {msg}", file=sys.stderr)
    return index


class _NeverMatch:
    """Sentinel type used in isinstance() when an optional product type is
    missing from an older wheel. No real object will be an instance of this."""


def _import_command_types():
    """Resolve AnyscaleCommand / DeprecatedAnyscaleCommand / LegacyAnyscaleCommand
    from the installed wheel. Older wheels (pre-deprecation, pre-legacy-split)
    may be missing some of these types; substitute a never-matching sentinel."""
    from anyscale.commands import util  # noqa: PLC0415

    return (
        getattr(util, "AnyscaleCommand", _NeverMatch),
        getattr(util, "DeprecatedAnyscaleCommand", _NeverMatch),
        getattr(util, "LegacyAnyscaleCommand", _NeverMatch),
    )


def _extract_cli_command(
    c: Any, *, default_cli_prefix: str, group_prefix: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Capture everything the renderer reads off a Click command.

    Returns None when the command is marked hidden (`click.Command.hidden`),
    signaling that the caller should drop it.
    """
    import click  # noqa: PLC0415

    if _is_hidden_cli_command(c):
        return None

    AnyscaleCommand, DeprecatedAnyscaleCommand, LegacyAnyscaleCommand = (
        _import_command_types()
    )

    ctx = click.Context(command=c)
    usage_str = " ".join(c.collect_usage_pieces(ctx))
    info_dict: Dict[str, Any] = c.to_info_dict(ctx)

    cli_prefix = f"{default_cli_prefix} {group_prefix}" if group_prefix else default_cli_prefix

    is_anyscale_command = isinstance(
        c, (AnyscaleCommand, DeprecatedAnyscaleCommand, LegacyAnyscaleCommand)
    )

    if isinstance(c, LegacyAnyscaleCommand):
        kind = "legacy_cli"
        legacy_prefix = c.get_legacy_prefix()
        new_c = c.get_new_cli()
        new_cli_prefix = c.get_new_prefix()
        legacy_meta = {
            "is_limited_support": c.is_limited_support(),
            "legacy_prefix": legacy_prefix,
            "new_cli_name": new_c.name if new_c else None,
            "new_cli_prefix": new_cli_prefix,
        }
        deprecated_meta = None
        # Legacy commands override the prefix with their own.
        cli_prefix = legacy_prefix or cli_prefix
    elif isinstance(c, DeprecatedAnyscaleCommand):
        kind = "deprecated"
        legacy_meta = None
        removal_date = getattr(c, "__removal_date__", None)
        formatted_date = (
            c._format_removal_date(removal_date) if removal_date else None  # noqa: SLF001
        )
        deprecated_meta = {
            "deprecation_message": getattr(c, "__deprecation_message__", None),
            "removal_date": formatted_date,
            "alternative": getattr(c, "__alternative__", None),
        }
    elif isinstance(c, AnyscaleCommand) and c.is_alpha:
        kind = "alpha"
        legacy_meta = None
        deprecated_meta = None
    elif isinstance(c, AnyscaleCommand) and c.is_beta:
        kind = "beta"
        legacy_meta = None
        deprecated_meta = None
    else:
        kind = "regular"
        legacy_meta = None
        deprecated_meta = None

    options = []
    for param in info_dict["params"]:
        if param.get("param_type_name") != "option":
            continue
        # Mirror product-side filter: Click options marked `hidden=True` are
        # excluded from `--help` and from the generated reference, even though
        # they remain functional. See anyscale/product PR #39685.
        if param.get("hidden"):
            continue
        opts = list(param.get("opts", []))
        secondary_opts = list(param.get("secondary_opts", []))
        options.append(
            {
                "name": param.get("name"),
                "opts": opts,
                "secondary_opts": secondary_opts,
                "help": param.get("help"),
            }
        )

    return {
        "name": c.name,
        "kind": kind,
        "is_anyscale_command": is_anyscale_command,
        "cli_prefix": cli_prefix,
        "usage": usage_str,
        "help": info_dict.get("help"),
        "options": options,
        "examples": _collect_examples(c),
        "legacy_meta": legacy_meta,
        "deprecated_meta": deprecated_meta,
    }


def _assert_no_hidden_model_refs(
    *,
    sdk_qualname: str,
    arg_name: Optional[str],
    type_str: str,
    hidden_models: set,
) -> None:
    """Raise if `type_str` references a model that's marked hidden.

    Dropping a hidden model from the emitted module would leave dangling
    `[ModelName](file.md#anchor)` links elsewhere. Catch this at extract time
    with a clear error rather than letting it ship as a silent broken anchor.
    """
    for model_name in hidden_models:
        # `type_to_string` emits the model name inside square brackets when it
        # renders a cross-page anchor link, e.g. `[ModelName](file.md#...)`.
        # That bracketed form is the unambiguous match.
        if f"[{model_name}]" in type_str:
            location = (
                f"argument '{arg_name}'" if arg_name else "return type"
            )
            raise ValueError(
                f"SDK command '{sdk_qualname}' {location} references hidden "
                f"model '{model_name}'. Either un-hide the model or also hide "
                f"the SDK command."
            )


def _extract_sdk_command(
    c: Callable,
    *,
    sdk_prefix: str,
    model_index: Dict[str, str],
    hidden_models: set,
    current_module_filename: str,
) -> Dict[str, Any]:
    if not c.__doc__:
        raise ValueError(
            f"SDK command '{sdk_prefix}.{c.__name__}' is missing a docstring."
        )

    sdk_qualname = f"{sdk_prefix}.{c.__name__}"
    signature = inspect.signature(c)
    has_any_parameters = len(signature.parameters) > 0
    # SDK decorators in newer wheels can mark args as hidden via
    # `hidden_args={...}`, which gets stashed on the wrapped function as
    # `__hidden_args__`. Older wheels lack the attribute and we treat the
    # set as empty. See anyscale/product PR #39685.
    hidden_args = set(getattr(c, "__hidden_args__", set()) or set())
    parameters: List[Dict[str, Any]] = []
    for name, param in signature.parameters.items():
        if name.startswith("_"):
            continue
        if name in hidden_args:
            continue
        if param.annotation is inspect.Parameter.empty:
            raise AssertionError(
                f"SDK command '{sdk_qualname}' is missing a type "
                f"hint for argument '{name}'"
            )
        type_str = type_to_string(
            param.annotation, model_index, current_module_filename
        )
        _assert_no_hidden_model_refs(
            sdk_qualname=sdk_qualname,
            arg_name=name,
            type_str=type_str,
            hidden_models=hidden_models,
        )
        default = (
            None
            if param.default is inspect.Parameter.empty
            else f"{param.default!s}"
        )
        arg_docs = getattr(c, "__arg_docstrings__", {}).get(name, None)
        if not arg_docs:
            raise ValueError(
                f"SDK command '{sdk_qualname}' is missing a "
                f"docstring for argument '{name}'"
            )
        parameters.append(
            {
                "name": name,
                "type_str": type_str,
                "default": default,
                "docstring": arg_docs,
            }
        )

    return_type_str: Optional[str] = None
    if signature.return_annotation is not inspect.Signature.empty:
        return_type_str = type_to_string(
            signature.return_annotation, model_index, current_module_filename
        )
        _assert_no_hidden_model_refs(
            sdk_qualname=sdk_qualname,
            arg_name=None,
            type_str=return_type_str,
            hidden_models=hidden_models,
        )

    return {
        "name": c.__name__,
        "docstring": c.__doc__,
        "has_any_parameters": has_any_parameters,
        "parameters": parameters,
        "return_type_str": return_type_str,
        "skip_py_example": getattr(c, "__skip_py_example__", False),
        "examples": _collect_examples(c),
    }


def _import_model_base_types():
    """Resolve ModelBaseType / ModelEnumType. These have been present since
    docgen's inception, but we still wrap to keep the failure mode loud."""
    from anyscale._private.models.model_base import (  # noqa: PLC0415
        ModelBaseType,
        ModelEnumType,
    )

    return ModelBaseType, ModelEnumType


def _extract_model(
    t: Any,
    *,
    model_index: Dict[str, str],
    current_module_filename: str,
) -> Dict[str, Any]:
    ModelBaseType, ModelEnumType = _import_model_base_types()

    assert isinstance(t, (ModelBaseType, ModelEnumType))
    docstring = t.__doc__
    assert isinstance(docstring, str)

    if isinstance(t, ModelBaseType):
        kind = "base"
        is_config = t.__name__.endswith("Config")
        skip_py_example = getattr(t, "__skip_py_example__", False)
        if not skip_py_example and not getattr(t, "__doc_py_example__", None):
            raise ValueError(f"Model '{t.__name__}' is missing a '__doc_py_example__'.")
        if is_config and not getattr(t, "__doc_yaml_example__", None):
            raise ValueError(
                f"Config model '{t.__name__}' is missing a '__doc_yaml_example__'."
            )
        model_fields: List[Dict[str, Any]] = []
        for field in dataclass_fields(t):
            if field.name.startswith("_"):
                continue
            field_docstring = field.metadata.get("docstring", None)
            if not field_docstring:
                raise ValueError(
                    f"Model '{t.__name__}' is missing a docstring for field "
                    f"'{field.name}'"
                )
            model_fields.append(
                {
                    "name": field.name,
                    "type_str": type_to_string(
                        field.type, model_index, current_module_filename
                    ),
                    "docstring": field_docstring,
                    "customer_hosted_only": field.metadata.get(
                        "customer_hosted_only", False
                    ),
                }
            )
        return {
            "name": t.__name__,
            "kind": kind,
            "docstring": docstring,
            "is_config": is_config,
            "skip_py_example": skip_py_example,
            "fields": model_fields,
            "members": None,
            "examples": _collect_examples(t),
        }

    # ModelEnumType
    members: List[Dict[str, str]] = []
    for value in t.__members__:
        if str(value).startswith("_"):
            continue
        members.append(
            {"name": value, "docstring": t.__docstrings__[value]}
        )
    return {
        "name": t.__name__,
        "kind": "enum",
        "docstring": docstring,
        "is_config": False,
        "skip_py_example": False,
        "fields": None,
        "members": members,
        "examples": {"yaml": None, "python": None, "cli": None},
    }


def _parse_legacy_sources(docgen_pkg_dir: str) -> Dict[str, Any]:
    """Parse api.md and models.md shipped inside the wheel.

    Reuses the wheel's `parse_legacy_sdks` so the markdown transformations
    stay byte-identical with the product-side renderer. We capture the
    parsed objects' `name` and `docstring` strings only.
    """
    from anyscale._private.docgen.generator_legacy import parse_legacy_sdks  # noqa: PLC0415

    api_md = os.path.join(docgen_pkg_dir, "api.md")
    models_md = os.path.join(docgen_pkg_dir, "models.md")
    legacy_sdks, legacy_models = parse_legacy_sdks(api_md, models_md)
    return {
        "sdks": [{"name": s.name, "docstring": s.docstring} for s in legacy_sdks],
        "models": [{"name": m.name, "docstring": m.docstring} for m in legacy_models],
    }


def _extract_module(
    m: Any, *, model_index: Dict[str, str], hidden_models: set
) -> Dict[str, Any]:
    # Resolve group prefix per command using object identity (matching the
    # product-side renderer), since multiple commands can share a `name` across
    # different group prefixes (e.g. cloud's `setup` exists at the top level and
    # also under `cloud resource`).
    group_map = m.cli_command_group_prefix or {}

    cli_commands = []
    for c in m.cli_commands or []:
        group_prefix = group_map.get(c)
        extracted = _extract_cli_command(
            c, default_cli_prefix=m.cli_prefix, group_prefix=group_prefix
        )
        if extracted is not None:
            cli_commands.append(extracted)

    legacy_cli_commands = []
    for c in m.legacy_cli_commands or []:
        extracted = _extract_cli_command(
            c,
            default_cli_prefix=m.legacy_cli_prefix or m.cli_prefix,
            group_prefix=None,
        )
        if extracted is not None:
            legacy_cli_commands.append(extracted)

    sdk_commands = [
        _extract_sdk_command(
            c,
            sdk_prefix=m.sdk_prefix,
            model_index=model_index,
            hidden_models=hidden_models,
            current_module_filename=m.filename,
        )
        for c in m.sdk_commands or []
        if not _is_hidden_sdk_command(c)
    ]

    models = [
        _extract_model(
            t, model_index=model_index, current_module_filename=m.filename
        )
        for t in m.models or []
        if not _is_hidden_model(t)
    ]

    legacy_sdk_command_refs: List[Dict[str, Optional[str]]] = []
    if m.legacy_sdk_commands:
        for legacy_name, new_sdk in m.legacy_sdk_commands.items():
            legacy_sdk_command_refs.append(
                {
                    "legacy_name": legacy_name,
                    "new_sdk_name": new_sdk.__name__ if new_sdk else None,
                }
            )

    return {
        "title": m.title,
        "filename": m.filename,
        "cli_prefix": m.cli_prefix,
        "sdk_prefix": m.sdk_prefix,
        "cli_commands": cli_commands,
        "sdk_commands": sdk_commands,
        "models": models,
        "legacy_title": m.legacy_title,
        "legacy_cli_prefix": m.legacy_cli_prefix,
        "legacy_cli_commands": legacy_cli_commands,
        "legacy_sdk_command_refs": legacy_sdk_command_refs,
        "legacy_sdk_model_names": list(m.legacy_sdk_models or []),
    }


def _detect_features() -> Dict[str, bool]:
    """Probe the installed wheel for known docgen features.

    These flags are a forward-compat hook: the current renderer doesn't gate on
    them (the install will always be a recent enough wheel for `npm run sync`),
    but archive runs against older versions can read them and skip features
    that didn't exist yet. When eng changes the renderer surface in the future,
    add a flag here for it.
    """
    from anyscale.commands import util as commands_util  # noqa: PLC0415
    from anyscale._private.docgen import generator as wheel_generator  # noqa: PLC0415
    import inspect as _inspect  # noqa: PLC0415

    has_hidden_args_decorator = False
    has_hidden_method_decorator = False
    try:
        from anyscale._private.sdk import sdk_command  # noqa: PLC0415

        sdk_command_params = _inspect.signature(sdk_command).parameters
        has_hidden_args_decorator = "hidden_args" in sdk_command_params
        has_hidden_method_decorator = "hidden" in sdk_command_params
    except ImportError:
        pass

    module_dataclass = getattr(wheel_generator, "Module", None)
    has_hidden_module = False
    if module_dataclass is not None:
        has_hidden_module = "hidden" in {
            f.name for f in _dataclass_fields_or_empty(module_dataclass)
        }

    return {
        "has_deprecated_commands": hasattr(commands_util, "DeprecatedAnyscaleCommand"),
        "has_legacy_anyscale_command": hasattr(commands_util, "LegacyAnyscaleCommand"),
        "has_alpha_beta": hasattr(commands_util, "AnyscaleCommand")
        and "is_alpha" in dir(commands_util.AnyscaleCommand)
        and "is_beta" in dir(commands_util.AnyscaleCommand),
        "has_sphinx_stripping": hasattr(wheel_generator, "strip_sphinx_docstring"),
        "has_mdx_escaping": hasattr(wheel_generator, "_escape_mdx_content"),
        "has_legacy_split": hasattr(
            getattr(wheel_generator, "MarkdownGenerator", object),
            "_generate_legacy_content",
        ),
        "has_hidden_args_decorator": has_hidden_args_decorator,
        "has_hidden_method_decorator": has_hidden_method_decorator,
        "has_hidden_module": has_hidden_module,
    }


def _dataclass_fields_or_empty(cls: Any) -> List[Any]:
    """`dataclasses.fields(cls)` if cls is a dataclass; otherwise empty list."""
    import dataclasses  # noqa: PLC0415

    if dataclasses.is_dataclass(cls):
        return list(dataclasses.fields(cls))
    return []


def build_reference_json(*, allow_duplicate_models: bool = False) -> Dict[str, Any]:
    import anyscale  # noqa: PLC0415
    import anyscale._private.docgen.__main__ as docgen_main  # noqa: PLC0415
    from anyscale._private.docgen import generator as wheel_generator  # noqa: PLC0415

    all_modules = docgen_main.ALL_MODULES
    docgen_pkg_dir = os.path.dirname(docgen_main.__file__)

    # Hidden modules drop entirely, both from the model index and from the
    # extracted output. Models inside a non-hidden module that are themselves
    # marked hidden stay in the model index (so `type_to_string` still
    # resolves them) but are filtered out of the module's emitted `models`
    # list. Any non-hidden SDK function that still references such a model
    # raises in `_extract_sdk_command`.
    visible_modules = [m for m in all_modules if not _is_hidden_module(m)]
    model_index = _build_model_index(
        visible_modules, allow_duplicates=allow_duplicate_models
    )
    hidden_models = {
        model.__name__
        for m in visible_modules
        for model in (m.models or [])
        if _is_hidden_model(model)
    }
    legacy_sources = _parse_legacy_sources(docgen_pkg_dir)
    modules = [
        _extract_module(m, model_index=model_index, hidden_models=hidden_models)
        for m in visible_modules
    ]

    # Pull renderer-policy constants from the installed wheel so the docs-side
    # renderer doesn't drift if product evolves them.
    cli_no_examples = sorted(getattr(wheel_generator, "CLI_NO_EXAMPLES", set()))
    cli_options_to_skip = sorted(getattr(wheel_generator, "CLI_OPTIONS_TO_SKIP", set()))

    return {
        "schema_version": SCHEMA_VERSION,
        "anyscale_version": getattr(anyscale, "__version__", None),
        "features": _detect_features(),
        "constants": {
            "cli_no_examples": cli_no_examples,
            "cli_options_to_skip": cli_options_to_skip,
        },
        "model_index": model_index,
        "legacy_sources": legacy_sources,
        "modules": modules,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Introspect installed anyscale wheel and emit reference.json."
    )
    parser.add_argument("output_path", help="Where to write the JSON.")
    parser.add_argument(
        "--allow-duplicate-models",
        action="store_true",
        help=(
            "Warn instead of raising on duplicate model class names. Used "
            "when introspecting older wheels that registered the same model "
            "in two docgen modules (e.g. CloudDeployment across "
            "anyscale 0.26.48-0.26.52)."
        ),
    )
    args = parser.parse_args()

    data = build_reference_json(allow_duplicate_models=args.allow_duplicate_models)
    os.makedirs(os.path.dirname(os.path.abspath(args.output_path)), exist_ok=True)
    with open(args.output_path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=False)
        f.write("\n")
    print(
        f"Wrote {args.output_path} (anyscale=={data['anyscale_version']}, "
        f"{len(data['modules'])} modules, "
        f"{len(data['legacy_sources']['sdks'])} legacy SDKs, "
        f"{len(data['legacy_sources']['models'])} legacy models).",
        file=sys.stderr,
    )
    # Imports above ensured the helpers are reachable; quiet unused warnings.
    _ = (escape_mdx_content, strip_sphinx_docstring)
    return 0


if __name__ == "__main__":
    sys.exit(main())
