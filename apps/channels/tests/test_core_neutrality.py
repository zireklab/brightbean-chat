"""The core does not know what a platform's API looks like.

ROADMAP contract 4 promises that a platform costs "one module in
``channels/providers/`` and one registry entry". That holds only while
everything *outside* the adapters speaks this product's own vocabulary — blocks,
buttons, quick replies, postbacks — and never a platform's. A Telegram
``callback_data`` in the flow engine, or a comparison against ``"telegram"`` in
the inbox, is the first line of a second implementation of the platform, and it
shows up in review only when somebody happens to be looking at that file.

``test_instagram_policy.py::TestContractFour`` holds ``apps/messaging`` to this
for one platform's name. This holds the whole core to it for the platform with
the most words of its own: the Bot API's method names, its keyboard and update
vocabulary, and the adapters' package.

The scan is an AST walk, not a grep. A docstring may say what a platform does —
explaining a decision is the point of one — but no expression may use its words,
because an expression is behaviour.
"""

import ast
import os
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

#: Packages that decide what a message *is*, or what to do about one. None of
#: them has a reason to know how a platform spells a keyboard.
CORE_PACKAGES = (
    "flows",
    "messaging",
    "inbox",
    "broadcasts",
    "campaigns",
    "analytics",
    "api",
    "contacts",
    "queueing",
)

#: The modules of ``apps.channels`` that are shared vocabulary rather than an
#: adapter: the event and message dataclasses, the renderer every adapter
#: shares, the capability and policy tables, and the inbound seam.
CORE_CHANNEL_MODULES = ("events.py", "downgrade.py", "capabilities.py", "policy.py", "ingest.py")

#: Directories that are not production Python, or are not ours. Pruned while
#: walking rather than filtered afterwards, so a populated ``node_modules`` is
#: never traversed.
SKIPPED_DIRECTORIES = frozenset({"tests", "migrations", "frontend", "static", "node_modules", "__pycache__"})

#: Words that only mean something to the Telegram Bot API. A name here appearing
#: in the core means the core learned a detail it must not know.
BOT_API_VOCABULARY = frozenset(
    {
        "allowed_updates",
        "answerCallbackQuery",
        "callback_data",
        "callback_query",
        "callback_query_id",
        "chat_id",
        "getUpdates",
        "inline_keyboard",
        "message_thread_id",
        "one_time_keyboard",
        "parse_mode",
        "reply_markup",
        "resize_keyboard",
        "rich_message",
        "sendMessage",
        "sendPhoto",
        "sendRichMessage",
        "sendWidget",
        "setWebhook",
    }
)
_VOCABULARY_IN_TEXT = re.compile(r"\b(?:" + "|".join(sorted(BOT_API_VOCABULARY)) + r")\b")

#: What the core may import from the adapters' package. Both are leaf modules
#: that import no adapter: the provider error types a send can raise, and the
#: HTML sanitiser an email body goes through. Anything else is the core reaching
#: into one platform.
ALLOWED_PROVIDER_IMPORTS = frozenset({"apps.channels.providers.exceptions", "apps.channels.providers.email_html"})

PROVIDERS_PACKAGE = "apps.channels.providers"


def core_sources() -> list[Path]:
    paths = [ROOT / "apps" / "channels" / name for name in CORE_CHANNEL_MODULES]
    for package in CORE_PACKAGES:
        for directory, subdirectories, filenames in os.walk(ROOT / "apps" / package):
            subdirectories[:] = [name for name in subdirectories if name not in SKIPPED_DIRECTORIES]
            paths.extend(Path(directory) / name for name in filenames if name.endswith(".py"))
    return sorted(paths)


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """The string constants that are docstrings, by identity."""
    found: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        first = node.body[0] if node.body else None
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            found.add(id(first.value))
    return found


def vocabulary_in(source: str) -> list[tuple[int, str]]:
    """``(line, word)`` for every Bot API word an expression uses."""
    tree = ast.parse(source)
    docstrings = _docstring_nodes(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            found.extend((node.lineno, match.group(0)) for match in _VOCABULARY_IN_TEXT.finditer(node.value))
        elif isinstance(node, ast.Name) and node.id in BOT_API_VOCABULARY:
            found.append((node.lineno, node.id))
        elif isinstance(node, ast.Attribute) and node.attr in BOT_API_VOCABULARY:
            found.append((node.lineno, node.attr))
        elif isinstance(node, ast.arg | ast.keyword) and node.arg in BOT_API_VOCABULARY:
            found.append((node.lineno, str(node.arg)))
    return found


def _names_telegram(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return node.value == "telegram"
    if isinstance(node, ast.Attribute):
        return node.attr == "TELEGRAM"
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        return any(_names_telegram(item) for item in node.elts)
    return False


def telegram_comparisons_in(source: str) -> list[int]:
    """Lines where an expression is *compared* to Telegram's name.

    A table keyed by platform (``{Platform.TELEGRAM: ...}``) is data and is how
    contract 4 wants a platform described, so only comparisons count: those are
    where a decision is made by name.
    """
    return [
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Compare) and any(_names_telegram(side) for side in (node.left, *node.comparators))
    ]


def provider_imports_in(source: str) -> list[tuple[int, str]]:
    """``(line, module)`` for every import of an adapter module."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == PROVIDERS_PACKAGE:
                found.extend((node.lineno, f"{PROVIDERS_PACKAGE}.{alias.name}") for alias in node.names)
            elif node.module.startswith(PROVIDERS_PACKAGE + "."):
                found.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            found.extend(
                (node.lineno, alias.name)
                for alias in node.names
                if alias.name == PROVIDERS_PACKAGE or alias.name.startswith(PROVIDERS_PACKAGE + ".")
            )
    return found


def _scan(check: object) -> Iterator[str]:
    for path in core_sources():
        for hit in check(path.read_text()):  # type: ignore[operator]
            yield f"{path.relative_to(ROOT)}:{hit}"


class TestTheCoreSpeaksItsOwnVocabulary:
    def test_the_sweep_covers_the_core(self) -> None:
        """An empty sweep passes anything, so the sweep has to find what it should."""
        names = {path.relative_to(ROOT).as_posix() for path in core_sources()}
        assert {
            "apps/flows/engine/waits.py",
            "apps/messaging/ingest.py",
            "apps/inbox/rendering.py",
            "apps/channels/downgrade.py",
            "apps/channels/events.py",
        } <= names
        assert len(names) > 150
        assert not any("/tests/" in name or "/migrations/" in name for name in names)

    def test_no_expression_in_the_core_uses_a_bot_api_word(self) -> None:
        offenders = list(_scan(vocabulary_in))
        assert offenders == [], (
            "The core uses a Telegram Bot API word. That detail belongs in "
            f"apps/channels/providers/telegram.py: {offenders}"
        )

    def test_no_decision_in_the_core_is_made_by_comparing_to_telegram(self) -> None:
        offenders = list(_scan(telegram_comparisons_in))
        assert offenders == [], f"The core branches on Telegram by name. Read a capability or policy field: {offenders}"

    def test_the_core_imports_no_adapter(self) -> None:
        offenders = [
            f"{path.relative_to(ROOT)}:{line} {module}"
            for path in core_sources()
            for line, module in provider_imports_in(path.read_text())
            if module not in ALLOWED_PROVIDER_IMPORTS
        ]
        assert offenders == [], f"The core imports an adapter module: {offenders}"


class TestTheGuardsActuallyCatch:
    """Each rule is run against source that breaks it, so none can pass by finding nothing."""

    @pytest.mark.parametrize(
        "source",
        [
            'x = {"reply_markup": 1}',
            "send(chat_id=1)",
            "button.callback_data",
            "def f(parse_mode): pass",
            'y = f"{inline_keyboard}"',
            'log("sendMessage failed")',
            "answerCallbackQuery = 1",
        ],
    )
    def test_vocabulary(self, source: str) -> None:
        assert vocabulary_in(source)

    @pytest.mark.parametrize(
        "source",
        [
            '"""The adapter sends reply_markup and callback_data."""\nx = 1',
            "def f():\n    '''Builds an inline_keyboard.'''\n    return 1",
            "x = 'chat_identifier'",
            "# reply_markup in a comment\nx = 1",
        ],
    )
    def test_vocabulary_in_prose_is_allowed(self, source: str) -> None:
        assert vocabulary_in(source) == []

    @pytest.mark.parametrize(
        "source",
        [
            'a == "telegram"',
            "a != Platform.TELEGRAM",
            'a in ("sms", "telegram")',
            "Platform.TELEGRAM == a",
            "a in {Platform.EMAIL, Platform.TELEGRAM}",
        ],
    )
    def test_comparisons(self, source: str) -> None:
        assert telegram_comparisons_in(source)

    def test_a_table_keyed_by_platform_is_data_not_a_decision(self) -> None:
        assert telegram_comparisons_in("table = {Platform.TELEGRAM: 1}\nx = Platform.TELEGRAM") == []

    @pytest.mark.parametrize(
        "source",
        [
            "from apps.channels.providers.telegram import call",
            "from apps.channels.providers import telegram",
            "import apps.channels.providers.whatsapp",
            "import apps.channels.providers.base as base",
        ],
    )
    def test_imports(self, source: str) -> None:
        assert provider_imports_in(source)

    def test_the_two_permitted_modules_are_recognised_as_such(self) -> None:
        found = provider_imports_in(
            "from apps.channels.providers.exceptions import APIError\n"
            "from apps.channels.providers.email_html import sanitize\n"
        )
        assert {module for _line, module in found} == ALLOWED_PROVIDER_IMPORTS
