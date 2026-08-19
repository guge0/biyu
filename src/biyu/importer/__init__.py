"""P8-M2 · 手写书导入模块。

为作者工作台提供"把手写书纯文本切成结构化章节"的能力。
当前仅含 splitter(分章器);后续如需"wordguard/lint 预热"等可加。
"""

from .workbench import ImportConflict, import_manuscripts, preview_import, preview_memory
