import hashlib
import re
from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel, Field

from ..sandbox.local import safe_path


class PatchApplicationResult(BaseModel):
    success: bool
    files_changed: list[str] = Field(default_factory=list)
    rejected_paths: list[str] = Field(default_factory=list)
    error: str | None = None
    error_code: str | None = None
    repair_hint: str | None = None
    source_line: int | None = None
    patch_hash: str


class PatchApplier(ABC):
    @abstractmethod
    def apply(self, workspace: Path, patch: str, allowed_files: list[str]) -> PatchApplicationResult: ...


class UnifiedDiffApplier(PatchApplier):
    """Strict existing-file text diffs; no shell, renames, deletes, or fuzzy matching."""
    def apply(self, workspace: Path, patch: str, allowed_files: list[str]) -> PatchApplicationResult:
        result = PatchApplicationResult(success=False, patch_hash=hashlib.sha256(patch.encode()).hexdigest())
        originals: dict[Path, str] = {}
        replacements: dict[Path, str] = {}
        names: list[str] = []
        try:
            if not patch or len(patch.encode()) > 262144:
                raise ValueError("Empty patch or patch exceeds 256 KiB")
            lines = patch.splitlines(keepends=True)
            i = 0
            while i < len(lines):
                if lines[i].startswith(("diff --git ", "index ")):
                    i += 1
                    continue
                if not lines[i].startswith("--- ") or i + 1 >= len(lines) or not lines[i + 1].startswith("+++ "):
                    raise ValueError("Expected unified diff file headers")
                old = lines[i][4:].rstrip("\r\n").split("\t")[0]
                new = lines[i + 1][4:].rstrip("\r\n").split("\t")[0]
                old = old[2:] if old.startswith("a/") else old
                new = new[2:] if new.startswith("b/") else new
                try:
                    target = safe_path(workspace, new)
                    safe_path(workspace, old)
                    if old != new or new not in allowed_files or target.suffix.lower() not in {".c", ".h"}:
                        raise ValueError("Only allowlisted existing C/header files may be changed")
                except ValueError:
                    result.rejected_paths.append(new)
                    raise
                if not target.is_file() or target.stat().st_size > 2_000_000 or new.casefold() in {n.casefold() for n in names}:
                    raise ValueError("Missing, oversized, or duplicate patch target")
                originals[target] = target.read_text(encoding="utf-8")
                source = originals[target].splitlines(keepends=True)
                output: list[str] = []
                cursor = 0
                i += 2
                hunks = 0
                while i < len(lines) and lines[i].startswith("@@ "):
                    header = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", lines[i])
                    if not header:
                        raise ValueError("Malformed hunk header")
                    old_start, old_count = int(header[1]), int(header[2] or "1")
                    new_start, new_count = int(header[3]), int(header[4] or "1")
                    start = old_start - 1 if old_count else old_start
                    if start < cursor or start > len(source):
                        raise ValueError("Overlapping or out-of-range hunk")
                    output.extend(source[cursor:start])
                    cursor = start
                    if (new_start - 1 if new_count else new_start) != len(output):
                        raise ValueError("Inconsistent new hunk position")
                    i += 1
                    consumed = produced = 0
                    while i < len(lines) and (consumed < old_count or produced < new_count):
                        line = lines[i]
                        if line[:1] not in {" ", "+", "-"}:
                            raise ValueError("Malformed hunk body")
                        marker, payload = line[0], line[1:]
                        i += 1
                        if i < len(lines) and lines[i].startswith("\\ No newline at end of file"):
                            payload = payload.rstrip("\r\n")
                            i += 1
                        if marker in {" ", "-"}:
                            if cursor >= len(source) or source[cursor] != payload:
                                result.source_line = cursor + 1
                                raise ValueError("Patch context does not match original source")
                            consumed += 1
                            cursor += 1
                        if marker in {" ", "+"}:
                            output.append(payload)
                            produced += 1
                    if consumed != old_count or produced != new_count:
                        raise ValueError("Hunk line counts do not match")
                    hunks += 1
                if not hunks:
                    raise ValueError("File has no hunks")
                output.extend(source[cursor:])
                replacements[target] = "".join(output)
                names.append(new)
                if len(names) > 32:
                    raise ValueError("Too many files in patch")
            if not replacements or all(originals[path] == text for path, text in replacements.items()):
                raise ValueError("Patch makes no changes")
            # Validate every hunk/path before any writes; roll back if a write fails.
            try:
                for target, text in replacements.items():
                    target.write_text(text, encoding="utf-8", newline="")
            except OSError:
                for target, text in originals.items():
                    target.write_text(text, encoding="utf-8", newline="")
                raise
            result.success, result.files_changed = True, names
        except (ValueError, OSError, UnicodeError) as exc:
            result.error = str(exc)
            result.error_code, result.repair_hint = {
                "File has no hunks": ("missing_hunks", "Return exact source edits; the application will generate numbered unified diff hunks."),
                "Malformed hunk header": ("malformed_hunk", "Return exact source edits instead of calculating diff line numbers."),
                "Patch context does not match original source": ("context_mismatch", "Copy search blocks from ORIGINAL source, preserving whitespace, line endings and C escapes. Do not base edits on a rejected candidate."),
                "Hunk line counts do not match": ("hunk_count_mismatch", "Return exact source edits; do not calculate hunk counts yourself."),
                "Patch makes no changes": ("no_change", "Propose a source change that addresses the observed failure."),
            }.get(str(exc), ("patch_rejected", "Use allowlisted original C/header paths and exact, non-overlapping source edits."))
        return result
