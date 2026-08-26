"""biyu configuration and book directory utilities."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from biyu.llm import ModelRegistry


def get_project_root() -> Path:
    """Return the biyu project root directory."""
    return Path(__file__).resolve().parents[2]


def get_config_path() -> Path:
    """Return the private config, or the shipped key-free example on first run."""
    configured = get_project_root() / "config" / "models.yaml"
    return configured if configured.exists() else get_models_example_path()


def get_models_example_path() -> Path:
    """Locate the safe model catalog in a source checkout or installed wheel."""
    source_example = get_project_root() / "config" / "models.yaml.example"
    if source_example.exists():
        return source_example
    installed_example = Path(sys.prefix) / "config" / "models.yaml.example"
    return installed_example if installed_example.exists() else source_example


def get_data_root() -> Path:
    """Return the explicitly selected data root without a production fallback."""
    configured = os.environ.get("BIYU_DATA_ROOT", "").strip()
    if not configured:
        raise RuntimeError("Data root not found; refusing to start (找不到数据根，不启动)")
    resolved = Path(configured).expanduser().resolve()
    if "pytest" in sys.modules:
        production_roots = {Path.home().joinpath("BiyuData").resolve()}
        explicit_production = os.environ.get("BIYU_PRODUCTION_DATA_ROOT", "").strip()
        if explicit_production:
            production_roots.add(Path(explicit_production).expanduser().resolve())
        if resolved in production_roots:
            raise RuntimeError(f"测试进程禁止使用生产数据根：{resolved}")
    return resolved


def validate_runtime_binding(
    *,
    role: str | None = None,
    data_root: Path | None = None,
    project_root: Path | None = None,
) -> Path:
    """Require an explicit, existing data root whose location matches its role."""
    configured = data_root
    if configured is None:
        raw_root = os.environ.get("BIYU_DATA_ROOT", "").strip()
        if not raw_root:
            raise ValueError("Data root not found; refusing to start (找不到数据根，不启动；必须显式设置 BIYU_DATA_ROOT)")
        configured = Path(raw_root).expanduser()
    selected_role = (role if role is not None else os.environ.get("BIYU_RUNTIME_ROLE", "")).strip().lower()
    if selected_role not in {"production", "development", "test"}:
        raise ValueError("运行角色缺失或非法，必须是 production、development 或 test")
    resolved = Path(configured).resolve()
    if not resolved.is_dir():
        raise ValueError(f"数据根不存在或不是目录：{resolved}")

    project = (project_root or get_project_root()).resolve()
    test_expected = os.environ.get("BIYU_TEST_DATA_ROOT", "").strip()
    production_expected = os.environ.get("BIYU_PRODUCTION_DATA_ROOT", "").strip()
    if selected_role in {"development", "test"}:
        expected = Path(test_expected).expanduser().resolve() if test_expected else (project / "data")
        if resolved != expected:
            raise ValueError(f"运行角色与数据根不匹配：test 应使用 {expected}，实际为 {resolved}")
    else:
        if production_expected:
            expected = Path(production_expected).expanduser().resolve()
            if resolved != expected:
                raise ValueError(f"运行角色与数据根不匹配：production 应使用 {expected}，实际为 {resolved}")
        else:
            try:
                resolved.relative_to(project)
            except ValueError:
                pass
            else:
                raise ValueError(f"运行角色与数据根不匹配：production 数据根不得位于代码仓 {project}")
    return resolved


def get_data_root_2() -> Path | None:
    """Return the secondary (dev/legacy) data root, or None when unset (I-1)."""
    configured = os.environ.get("BIYU_DATA_ROOT_2", "").strip()
    return Path(configured).expanduser().resolve() if configured else None


def get_data_roots() -> list[Path]:
    """All visible data roots: primary first, secondary second (I-1 dual-root)."""
    roots = [get_data_root()]
    second = get_data_root_2()
    if second is not None:
        roots.append(second)
    return roots


def get_registry() -> ModelRegistry:
    """Create a ModelRegistry from the default config."""
    catalog_path = get_config_path()
    registry = ModelRegistry(catalog_path)
    if catalog_path.name == "models.yaml.example":
        # The registry's existing selected-model override is intentionally tied
        # to the private models.yaml location. Keep that behavior while loading
        # the key-free first-run catalog read-only.
        registry._config_path = catalog_path.with_name("models.yaml")
    return registry


def feature_enabled(name: str) -> bool:
    """Return one feature flag without exposing private model configuration."""
    return get_registry().get_feature(name)


class BookConfig:
    """Represents a single book's configuration and directory structure."""

    def __init__(self, book_dir: Path):
        self.book_dir = book_dir
        self._meta: dict[str, Any] | None = None

    @property
    def meta_path(self) -> Path:
        return self.book_dir / "book.json"

    @property
    def characters_path(self) -> Path:
        return self.book_dir / "characters.yaml"

    @property
    def outlines_dir(self) -> Path:
        return self.book_dir / "outlines"

    @property
    def chapters_dir(self) -> Path:
        return self.book_dir / "chapters"

    @property
    def logs_dir(self) -> Path:
        return self.book_dir / "logs"

    @property
    def cost_log_path(self) -> Path:
        return self.logs_dir / "cost_log.csv"

    def outline_path(self, chapter_num: int) -> Path:
        return self.outlines_dir / f"ch{chapter_num}.md"

    def chapter_path(self, chapter_num: int) -> Path:
        return self.chapters_dir / f"ch{chapter_num}.md"

    def chapter_log_dir(self, chapter_num: int) -> Path:
        d = self.logs_dir / f"ch{chapter_num}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def load_meta(self) -> dict[str, Any]:
        if self._meta is not None:
            return self._meta
        with open(self.meta_path, encoding="utf-8") as f:
            self._meta = json.load(f)
        return self._meta

    def save_meta(self, meta: dict[str, Any]) -> None:
        self._meta = meta
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    @property
    def title(self) -> str:
        return self.load_meta().get("title", "")

    @property
    def genre(self) -> str:
        return self.load_meta().get("genre", "")

    @property
    def id(self) -> str:
        """稳定 slug id(P8-M3R R1):优先 book.json 的 id 字段;无则回退目录名。

        回退保证旧数据迁移前不断;新数据应在 book.json 显式写 id。
        """
        meta_id = self.load_meta().get("id")
        if meta_id:
            return str(meta_id)
        return self.book_dir.name

    @property
    def chapter_target_words(self) -> int:
        return self.load_meta().get("chapter_target_words", 5000)

    @property
    def chapter_min_words(self) -> int:
        return self.load_meta().get("chapter_min_words", 4250)


def load_characters_yaml(book_dir: Path) -> list[dict[str, Any]]:
    """Load characters from characters.yaml.

    Returns:
        List of character dicts with all fields from yaml.
    """
    yaml_path = book_dir / "characters.yaml"
    if not yaml_path.exists():
        return []
    from biyu.setup_asset_versions import load_setup_yaml

    data = load_setup_yaml(yaml_path, label="角色设定")
    return data.get("characters", [])


def _visible_book_dirs(roots: list[Path] | None = None) -> list[Path]:
    """Return valid book directories from every visible author data root."""
    visible: list[Path] = []
    for root in roots or get_data_roots():
        resolved_root = Path(root).expanduser().resolve()
        if not resolved_root.exists():
            continue
        visible.extend(
            path for path in sorted(resolved_root.iterdir())
            if path.is_dir() and (path / "book.json").exists()
        )
    return visible


def find_book_dir(book: str | None = None, *, roots: list[Path] | None = None) -> Path:
    """Pure lookup shared by Web and Claude Code; never initializes Git.

    A supplied id wins globally, then a directory-name match is accepted.  The
    global id pass keeps both clients deterministic even when roots overlap.
    """
    books = _visible_book_dirs(roots)
    if book:
        for path in books:
            try:
                meta = json.loads((path / "book.json").read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if meta.get("id") == book:
                return path
        for path in books:
            if path.name == book:
                return path
        choices = "、".join(path.name for path in books) or "（没有可用书）"
        raise FileNotFoundError(f"找不到书目录『{book}』；可选书目录：{choices}")
    if len(books) == 1:
        return books[0]
    if not books:
        raise FileNotFoundError("没有找到书；请先在作者界面新建一本书")
    raise ValueError(f"找到多本书：{[path.name for path in books]}；请指定书目录名")


def resolve_book_dir(book: str | None = None) -> Path:
    """Resolve a book name OR book_id to its directory path.

    P8-M3R R1 slug ID:lookup order:
    1. Match by `id` field in book.json across all books (slug lookup)
    2. Fall back to directory name (legacy contract)

    If book is None, auto-detect the only book in data/.
    """
    return find_book_dir(book)
