# Link-Time PDF Repair Design

## Background

PDFs uploaded directly to a knowledge base pass through
`read_potential_broken_pdf()` before they are stored. PDFs uploaded through
file management are stored unchanged, and `/file2document/convert` only links
the existing object to a knowledge base.

The reproduced `问答测试.pdf` contains malformed object boundaries such as
`endobj204 0 obj`. Poppler and PyPDF recover its 15 pages, but the
pdfplumber/pdfminer versions used by RAGFlow report zero pages. Task creation
then produces an empty task list and `bulk_insert_into_db()` raises an
`IndexError`.

## Goals

- Apply the existing PDF repair behavior when a file-management PDF is linked
  to a knowledge base.
- Replace the source storage object with repaired bytes so all later links and
  parses reuse the repaired PDF.
- Synchronize the file record's size before creating document links.
- Avoid storage writes for valid PDFs and all non-PDF files.
- Keep direct knowledge-base upload behavior unchanged.

## Non-Goals

- Implement a new PDF repair engine.
- Create a separate repaired copy for each knowledge base.
- Change parsing, chunking, or page-range semantics.
- Change the generic bulk-insert helper as part of this fix.

## Approach Comparison

### A. Repair the source object when linking

Read and repair each PDF once before creating knowledge-base document records.
If bytes change, overwrite the source object and update its recorded size.

This fixes existing file-management objects and makes future links reuse the
repaired content. It is the selected approach.

### B. Repair only during file-management upload

This prevents new malformed objects but does not fix files that are already in
file management. It also does not provide a defensive link-time check.

### C. Repair during parsing

This repeats repair work on every parse and occurs too late to prevent the
zero-page task-creation failure.

## Design

Add a focused `FileService` operation that accepts a file record and storage
implementation:

1. Return immediately unless the file type is PDF.
2. Read the object using the file's `parent_id` and `location`.
3. Pass the bytes to `read_potential_broken_pdf()`.
4. If the returned bytes are unchanged, return the original file record.
5. If the bytes changed, overwrite the same storage object.
6. Update the file row's `size` and the in-memory file record.
7. Return the file record for document creation.

`/file2document/convert` invokes this operation once per innermost file before
removing prior document links and before iterating over target knowledge bases.
This ordering preserves existing links if repair fails. All newly created
document rows receive the repaired file size.

## Failure Handling

- Storage read, repair, storage write, or database update errors propagate to
  the route's existing exception handler before existing links are removed or
  new links are created.
- Storage is written before the size field is updated because the database
  must not advertise repaired content that was not stored successfully.
- If storage succeeds and the size update fails, no new document link is
  created. A later retry can safely run repair again; the repaired object will
  then be detected as valid and linking can continue.
- Existing `read_potential_broken_pdf()` fallback behavior remains unchanged:
  an unrepairable PDF is returned unchanged.

## Tests

Add focused unit coverage for the service operation and link integration:

1. A malformed PDF whose repair changes bytes is written back and its file
   size is updated.
2. A valid PDF whose repair returns identical bytes causes no storage write or
   database update.
3. A non-PDF file causes no storage read or write.
4. Link conversion uses the repaired size when constructing document rows.
5. A storage write failure prevents document creation and is surfaced by the
   existing route error handling.

## Acceptance Criteria

- Linking the reproduced `问答测试.pdf` repairs the source object and allows
  RAGFlow to discover all 15 pages.
- The linked document size equals the repaired object size.
- Linking the valid contract PDF does not rewrite its storage object.
- Existing file-management and direct knowledge-base upload tests pass.
- Focused Python tests, Ruff checks, and Python compilation checks pass.
