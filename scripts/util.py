"""Shared utilities for docs-side docgen (introspect + render + link registry)."""
from datetime import datetime
import re
import typing
from typing import Any, Dict, Optional, Type, Union


def url_route(filename: str) -> str:
    """Path component for a module filename under `/reference/cli|sdk/...`.

    Strips the `.md` extension and the legacy `-api` suffix so URLs such as
    `/reference/cli/compute-config-api` collapse to `/reference/cli/compute-config`.
    The raw filename in the upstream `Module.filename` is left untouched; the
    rewrite happens at the docs render boundary only.
    """
    return filename.removesuffix(".md").removesuffix("-api")


def sentence_case(text: str) -> str:
    """Lowercase every word after the first, preserving all-caps acronyms.

    Used to render module titles consistently in headings and sidebar labels:
    'Compute Config' -> 'Compute config', 'Cloud' -> 'Cloud'. Words that are
    already all-uppercase (>= 2 chars) are kept as-is so 'CLI', 'SDK',
    'SCIM', etc. don't get destroyed.
    """
    words = text.split(" ")
    if not words:
        return text
    out = [words[0]]
    for word in words[1:]:
        if len(word) >= 2 and word.isupper():
            out.append(word)
        else:
            out.append(word.lower())
    return " ".join(out)


def kebab_slug(text: str) -> str:
    """Lowercase + non-alphanumeric runs collapsed to single hyphens.

    Used to derive a stable module identifier from `Module.title`. Confirmed
    against current modules: 'Cloud' -> 'cloud', 'Compute Config' ->
    'compute-config', 'Resource quotas' -> 'resource-quotas',
    'Aggregated Instance Usage' -> 'aggregated-instance-usage'.
    """
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def cli_command_anchor(cli_prefix: str, name: str) -> str:
    """Anchor (no leading `#`) for `### \\`{cli_prefix} {name}\\``.

    Mirrors the legacy product-side `_get_cli_anchor`: hyphenate the prefix +
    name. CLI commands are already lowercase so no extra casing needed.
    """
    return f"{cli_prefix} {name}".replace(" ", "-")


def sdk_function_anchor(sdk_prefix: str, name: str) -> str:
    """Anchor for `### \\`{sdk_prefix}.{name}\\``.

    Mirrors product-side `_get_sdk_anchor`: drop the dots so
    `anyscale.cloud.create` becomes `anyscalecloudcreate`. Docusaurus auto-
    generates the same anchor from the heading text.
    """
    return f"{sdk_prefix}.{name}".replace(".", "")


def model_anchor(name: str) -> str:
    """Anchor for a current model heading. Lowercased class name."""
    return name.lower()


def legacy_sdk_anchor(name: str) -> str:
    """Anchor for a legacy SDK function heading. Heading uses no explicit
    anchor, so we mirror the auto-generated form: lowercased name with
    underscores preserved."""
    return name.lower()


def legacy_model_anchor(name: str) -> str:
    """Anchor for a legacy model heading.

    Legacy models use an explicit `{#name.lower()-legacy}` suffix when
    rendered into the main file, and `{#name.lower()}` when rendered into
    the legacy/ subfolder file. This returns the bare slug; callers append
    `-legacy` if pointing at the main file.
    """
    return name.lower()


# H2 sections that may appear inside a module's reference page. Order matches
# the order render.py emits them. The renderer omits any section whose source
# list is empty, so the helper below filters against the same module data.
MODULE_SECTIONS = (
    # (name,    display,   predicate-key)
    ("cli",     "CLI",     "cli_commands"),
    ("sdk",     "SDK",     "sdk_commands"),
    ("models",  "Models",  "models"),
)


def module_section_headings(module: Dict[str, Any]) -> list:
    """Return `[(name, display, anchor), ...]` for every H2 section the
    rendered main page will have, in render order.

    Single source of truth for the renderer's section list and the link
    registry's `section/<module>/<name>` entries. Anchor matches Docusaurus's
    auto-generated form: kebab-case of the heading text.
    """
    title = module["title"]
    title_slug = kebab_slug(title)
    out = []
    for name, display, key in MODULE_SECTIONS:
        if module.get(key):
            anchor = f"{title_slug}-{name}"
            out.append((name, display, anchor))
    return out


def cli_command_path(
    module_cli_prefix: str, command_cli_prefix: str, command_name: str
) -> str:
    """Path under the module for a CLI command, segments separated by `/`.

    `module_cli_prefix` is the module's base prefix (e.g., 'anyscale cloud').
    `command_cli_prefix` is what introspect attached to the specific command,
    including any group prefix (e.g., 'anyscale cloud config'). Returns the
    portion after the module prefix, with spaces replaced by `/`.

    Examples:
        anyscale cloud + 'anyscale cloud' / 'create' -> 'create'
        anyscale cloud + 'anyscale cloud config' / 'get' -> 'config/get'
        anyscale + 'anyscale auth' / 'show' -> 'auth/show' (Other module)
    """
    full = f"{command_cli_prefix} {command_name}"
    leader = f"{module_cli_prefix} "
    if full.startswith(leader):
        remaining = full[len(leader):]
    elif full == module_cli_prefix.rstrip():
        remaining = command_name
    else:
        # Fall back to stripping just the leading 'anyscale ' so we still
        # produce something for unexpected inputs rather than crashing.
        remaining = full.removeprefix("anyscale ").lstrip()
    return remaining.replace(" ", "/")


def escape_mdx_content(text: Optional[str]) -> str:
    """Escape content for MDX compatibility.

    Mirrors product-side _escape_mdx_content: angle brackets that look like HTML
    tags get escaped, and curly braces get escaped to prevent JSX expression
    interpretation.
    """
    if not text:
        return ""

    text = re.sub(r"<([a-zA-Z][a-zA-Z0-9\-]*?)>", r"\\<\1\\>", text)
    text = re.sub(r"(?<!\\)\{", r"\{", text)
    text = re.sub(r"(?<!\\)\}", r"\}", text)
    return text


def strip_sphinx_docstring(text: Optional[str]) -> str:
    """Strip sphinx/reStructuredText markers (:param, :return, etc.) from docstrings.

    Mirrors product-side strip_sphinx_docstring exactly.
    """
    if not text:
        return ""

    lines = text.split("\n")
    filtered_lines = []
    in_sphinx_block = False
    base_indent: Optional[int] = None

    for line in lines:
        stripped = line.strip()

        if re.match(r"^:[a-z]+(\s+\w+)?:", stripped):
            in_sphinx_block = True
            base_indent = len(line) - len(line.lstrip())
            continue

        if in_sphinx_block:
            assert base_indent is not None
            current_indent = len(line) - len(line.lstrip()) if line.strip() else 0
            if not stripped or (stripped and current_indent > base_indent):
                continue
            in_sphinx_block = False
            base_indent = None

        filtered_lines.append(line)

    while filtered_lines and not filtered_lines[-1].strip():
        filtered_lines.pop()

    return "\n".join(filtered_lines)


def type_to_string(
    t: Type,
    model_index: Dict[str, str],
    current_module_filename: Optional[str] = None,
) -> str:
    """Render a Python type annotation as a docs-flavored string.

    `model_index` maps a model class object (by id()) to its target filename so
    that references to model types resolve as cross-module anchor links.
    `current_module_filename` is the filename of the module the type appears
    in; same-module references emit a fragment-only link, cross-module
    references emit an absolute path to the canonical SDK page.

    This is a near-verbatim port of product-side _model_type_to_string +
    _type_container_to_string. We resolve model anchors here so the renderer
    only has to read pre-resolved strings.
    """
    # Lazy import: anyscale wheel must already be installed.
    from anyscale._private.models.model_base import (  # noqa: PLC0415
        ModelBaseType,
        ModelEnumType,
        ResultIterator,
    )

    if t is Any:
        return "Any"
    if t is str:
        return "str"
    if t is bool:
        return "bool"
    if t is int:
        return "int"
    if t is float:
        return "float"
    if t is bytes:
        return "bytes"
    if t is datetime:
        return "datetime"
    if t is None or t is type(None):
        return "None"

    origin = typing.get_origin(t)
    if origin is not None:
        args = typing.get_args(t)
        if origin is Union:
            return " | ".join(
                type_to_string(arg, model_index, current_module_filename)
                for arg in args
            )

        origin_name_map = {
            dict: "Dict",
            list: "List",
            tuple: "Tuple",
            ResultIterator: "ResultIterator",
        }
        if origin in origin_name_map:
            arg_str = ", ".join(
                type_to_string(arg, model_index, current_module_filename)
                for arg in args
            )
            if arg_str:
                return f"{origin_name_map[origin]}[{arg_str}]"
            return origin_name_map[origin]
        raise NotImplementedError(f"Unhandled type: {t}")

    if isinstance(t, (ModelBaseType, ModelEnumType)):
        filename = model_index.get(t.__name__)
        if filename is None:
            raise KeyError(
                f"Model {t.__name__} referenced from a type annotation but not "
                f"registered in any module's `models` list."
            )
        anchor = t.__name__.lower()
        if filename == current_module_filename:
            return f"[{t.__name__}](#{anchor})"
        return f"[{t.__name__}](/reference/sdk/{url_route(filename)}#{anchor})"

    raise NotImplementedError(
        f"Unhandled type: {t}. Either this type should not be in our public "
        f"APIs, or you must add handling for it to the doc generator."
    )
