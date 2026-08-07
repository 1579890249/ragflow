# MinerU Long Filename Handling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent MinerU's derived temporary, upload, ZIP, directory, and result filenames from exceeding filesystem component limits while preserving the original user-facing filename.

**Architecture:** Add one module-level UTF-8-aware working-stem function with a 180-byte budget and stable SHA-256 suffix. Generate the working stem once at the `parse_pdf` input boundary, use a temporary copy whenever a local source needs renaming, and let the existing API/output readers consistently consume the shortened PDF stem.

**Tech Stack:** Python 3.11, `pathlib`, `hashlib`, `tempfile`, `shutil`, pytest, Ruff

---

### Task 1: Add the bounded working-stem primitive

**Files:**
- Modify: `deepdoc/parser/mineru_parser.py:16-42`
- Test: `test/unit_test/deepdoc/test_mineru_parser.py`

- [ ] **Step 1: Write the failing working-stem test**

```python
def test_mineru_working_stem_is_utf8_bounded_and_collision_resistant(monkeypatch):
    module = load_mineru_parser(monkeypatch)
    shared_prefix = "超长中文文件名" * 30

    first = module._mineru_working_stem(shared_prefix + "甲")
    second = module._mineru_working_stem(shared_prefix + "乙")

    assert len(first.encode("utf-8")) <= module.MAX_MINERU_WORKING_STEM_BYTES
    assert len(second.encode("utf-8")) <= module.MAX_MINERU_WORKING_STEM_BYTES
    assert first != second
    assert first.rsplit("_", 1)[1].isalnum()
    assert len(first.rsplit("_", 1)[1]) == 12
    assert module._mineru_working_stem("short中文") == "short中文"
```

- [ ] **Step 2: Run the test to verify RED**

Run: `./venv/Scripts/python.exe -m pytest test/unit_test/deepdoc/test_mineru_parser.py::test_mineru_working_stem_is_utf8_bounded_and_collision_resistant -q`

Expected: FAIL because `_mineru_working_stem` does not exist.

- [ ] **Step 3: Implement the minimal working-stem function**

Add `hashlib` to the module imports and add:

```python
MAX_MINERU_WORKING_STEM_BYTES = 180
MINERU_WORKING_STEM_HASH_LENGTH = 12


def _mineru_working_stem(file_stem: str) -> str:
    normalized = file_stem.replace(" ", "") or "document"
    encoded = normalized.encode("utf-8")
    if len(encoded) <= MAX_MINERU_WORKING_STEM_BYTES:
        return normalized

    digest = hashlib.sha256(encoded).hexdigest()[:MINERU_WORKING_STEM_HASH_LENGTH]
    suffix = f"_{digest}"
    prefix_budget = MAX_MINERU_WORKING_STEM_BYTES - len(suffix.encode("ascii"))
    prefix = encoded[:prefix_budget].decode("utf-8", errors="ignore").rstrip(". ")
    return f"{prefix or 'document'}{suffix}"
```

- [ ] **Step 4: Run the working-stem test to verify GREEN**

Run the command from Step 2.

Expected: PASS.

### Task 2: Use the working stem throughout `parse_pdf`

**Files:**
- Modify: `deepdoc/parser/mineru_parser.py:633-724`
- Test: `test/unit_test/deepdoc/test_mineru_parser.py`

- [ ] **Step 1: Write failing binary and local-file lifecycle tests**

```python
def _stub_mineru_parse(parser, monkeypatch, captured):
    monkeypatch.setattr(parser, "__images__", lambda *args, **kwargs: None)

    def fake_run(input_path, output_dir, options, callback=None):
        captured["input_path"] = input_path
        captured["working_stem"] = input_path.stem
        assert input_path.is_file()
        return output_dir

    def fake_read(output_dir, file_stem, method="auto", backend="pipeline"):
        captured["read_stem"] = file_stem
        return []

    monkeypatch.setattr(parser, "_run_mineru", fake_run)
    monkeypatch.setattr(parser, "_read_output", fake_read)


def test_parse_pdf_uses_bounded_working_name_for_binary(monkeypatch):
    module = load_mineru_parser(monkeypatch)
    parser = module.MinerUParser()
    captured = {}
    _stub_mineru_parse(parser, monkeypatch, captured)

    parser.parse_pdf(f"{'超长名称' * 30}.pdf", b"%PDF-1.7")

    assert len(captured["working_stem"].encode("utf-8")) <= module.MAX_MINERU_WORKING_STEM_BYTES
    assert captured["read_stem"] == captured["working_stem"]


def test_parse_pdf_copies_renamed_local_input_without_modifying_source(tmp_path, monkeypatch):
    module = load_mineru_parser(monkeypatch)
    parser = module.MinerUParser()
    captured = {}
    _stub_mineru_parse(parser, monkeypatch, captured)
    source = tmp_path / f"{'本地超长名称' * 20}.pdf"
    source.write_bytes(b"%PDF-1.7")

    parser.parse_pdf(source, None)

    assert source.read_bytes() == b"%PDF-1.7"
    assert captured["input_path"] != source
    assert not captured["input_path"].exists()
    assert captured["read_stem"] == captured["working_stem"]
```

- [ ] **Step 2: Run both lifecycle tests to verify RED**

Run: `./venv/Scripts/python.exe -m pytest test/unit_test/deepdoc/test_mineru_parser.py -k "bounded_working_name or copies_renamed_local_input" -q`

Expected: FAIL because `parse_pdf` still uses or moves the original filename.

- [ ] **Step 3: Replace direct naming and source moves with the working-name lifecycle**

Replace the input setup in `parse_pdf` with:

```python
file_path = Path(filepath)
working_stem = _mineru_working_stem(file_path.stem)
pdf_file_name = f"{working_stem}.pdf"
if working_stem != file_path.stem:
    self.logger.info("[MinerU] Map original stem to working stem: %s -> %s", file_path.stem, working_stem)

if binary:
    temp_dir = Path(tempfile.mkdtemp(prefix="mineru_bin_pdf_"))
    temp_pdf = temp_dir / pdf_file_name
    temp_pdf.write_bytes(binary)
    pdf = temp_pdf
    self.logger.info(f"[MinerU] Received binary PDF -> {temp_pdf}")
    if callback:
        callback(0.15, f"[MinerU] Received binary PDF -> {temp_pdf}")
else:
    source_pdf = file_path
    if not source_pdf.exists():
        if callback:
            callback(-1, f"[MinerU] PDF not found: {source_pdf}")
        raise FileNotFoundError(f"[MinerU] PDF not found: {source_pdf}")
    if source_pdf.name != pdf_file_name:
        temp_dir = Path(tempfile.mkdtemp(prefix="mineru_input_pdf_"))
        temp_pdf = temp_dir / pdf_file_name
        shutil.copy2(source_pdf, temp_pdf)
        pdf = temp_pdf
    else:
        pdf = source_pdf
```

Keep the existing `finally` cleanup so both binary inputs and local temporary copies are removed.

- [ ] **Step 4: Run lifecycle tests to verify GREEN**

Run the command from Step 2.

Expected: both tests PASS.

### Task 3: Verify the complete MinerU change

**Files:**
- Verify: `deepdoc/parser/mineru_parser.py`
- Verify: `test/unit_test/deepdoc/test_mineru_parser.py`

- [ ] **Step 1: Run all MinerU parser unit tests**

Run: `./venv/Scripts/python.exe -m pytest test/unit_test/deepdoc/test_mineru_parser.py -q`

Expected: all tests PASS.

- [ ] **Step 2: Run syntax and focused lint checks**

Run: `./venv/Scripts/python.exe -m py_compile deepdoc/parser/mineru_parser.py test/unit_test/deepdoc/test_mineru_parser.py`

Expected: exit code 0.

Run: `./venv/Scripts/python.exe -m ruff check --select F,I deepdoc/parser/mineru_parser.py test/unit_test/deepdoc/test_mineru_parser.py`

Expected: `All checks passed!`

- [ ] **Step 3: Inspect the final diff**

Run: `git diff --check -- deepdoc/parser/mineru_parser.py test/unit_test/deepdoc/test_mineru_parser.py`

Expected: exit code 0 with no whitespace errors. Confirm that only MinerU naming, input copying, output discovery, and their tests changed.
