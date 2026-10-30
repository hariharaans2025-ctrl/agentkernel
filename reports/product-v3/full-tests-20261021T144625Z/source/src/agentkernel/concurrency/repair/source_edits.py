"""Convert exact, untrusted edit blocks into a deterministic unified diff."""
import difflib
from pathlib import PurePosixPath, PureWindowsPath

from pydantic import BaseModel, ConfigDict, Field


class SourceEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    file: str = Field(min_length=1, max_length=256)
    search: str = Field(min_length=1, max_length=120000)
    replacement: str = Field(max_length=120000)


class EditError(ValueError):
    def __init__(self, code: str, index: int, hint: str):
        super().__init__(hint)
        self.code, self.index, self.hint = code, index, hint


def edits_to_diff(edits: list[SourceEdit], sources: dict[str, str]) -> str:
    """Match every block against ORIGINAL source; never guess or cascade edits."""
    changes: dict[str, list[tuple[int, int, str]]] = {}
    for index, edit in enumerate(edits):
        name = edit.file
        if (name not in sources or PurePosixPath(name).is_absolute() or PureWindowsPath(name).drive
                or "\\" in name or ":" in name or any(ord(c) < 32 for c in name)
                or any(part in {"", ".", ".."} for part in name.split("/"))
                or PurePosixPath(name).suffix.lower() not in {".c", ".h", ".cc", ".cpp", ".hpp"}):
            raise EditError("edit_path_not_allowed", index, "Use an exact allowlisted C/header filename from sources.")
        source = sources[name]
        start = source.find(edit.search)
        if start < 0:
            raise EditError("edit_search_not_found", index,
                            "Copy search text exactly from ORIGINAL source. Preserve whitespace and C escapes; encode JSON once.")
        if source.find(edit.search, start + 1) >= 0:
            raise EditError("edit_search_ambiguous", index, "Include more original surrounding lines so search matches exactly once.")
        if edit.search == edit.replacement:
            raise EditError("edit_no_change", index, "The replacement must differ from search.")
        end = start + len(edit.search)
        if any(start < old_end and old_start < end for old_start, old_end, _ in changes.get(name, [])):
            raise EditError("edit_overlap", index, "Combine overlapping changes into one search/replacement block.")
        changes.setdefault(name, []).append((start, end, edit.replacement))
    chunks = []
    for name, replacements in changes.items():
        old = sources[name]
        new = old
        for start, end, replacement in sorted(replacements, reverse=True):
            new = new[:start] + replacement + new[end:]
        if len(new.encode("utf-8")) > 2_000_000:
            raise EditError("edit_result_too_large", 0, "Keep edited source below the 2 MB workspace limit.")
        for line in difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                         fromfile="a/" + name, tofile="b/" + name):
            # difflib does not insert the required EOF marker for unterminated lines.
            chunks.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    patch = "".join(chunks)
    if not patch or len(patch.encode("utf-8")) > 262144:
        raise EditError("edit_diff_size", 0, "Return a nonempty change within the 256 KiB patch limit.")
    return patch
