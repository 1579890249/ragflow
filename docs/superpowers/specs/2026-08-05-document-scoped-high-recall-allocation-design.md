# Document-Scoped High-Recall Candidate Allocation Design

## Context

The high-recall path currently discovers documents with a literal query term, searches those documents for answer terms, merges the results with global full-query and fallback channels, and reranks a bounded candidate set.

A production comparison exposed a candidate-allocation failure:

- With `rerank_top_n=64`, document discovery found both relevant `53-80` reports, but one report contributed only its identity/brand chunk. Its answer table did not enter the rerank set.
- The request had 82 candidate reports and only 64 rerank slots. The existing report-first selection consumed the entire budget before complementary chunks from the same report could be selected.
- With `rerank_top_n=128`, the missing answer table appeared, but latency increased from about 4.3 seconds to more than 7 seconds because both the per-channel pool and rerank batch doubled.
- The existing candidate preparation caps each logical report at six chunks, and final diversification caps it at three. A hard document-level cap is incorrect when more than three distinct chunks are strongly relevant.

The problem is general: an entity or identifier may occur in one chunk while the requested facts occur in other chunks of the same document. The solution must not contain tire brands, sizes, years, domain dictionaries, or other business-specific rules.

## Goals

1. Preserve at least one answer-bearing candidate from documents identified by literal document discovery or explicit `doc_ids`.
2. Allow any number of distinct chunks from the same document to compete when they are strongly relevant, subject only to global request budgets.
3. Allow the validated request profile to keep explicit `rerank_top_n=64`, its per-channel candidate pool of 256, and the existing datastore request count. This change does not alter the configured system default.
4. Preserve exact-content deduplication, multi-knowledge-base coverage, rerank fallback, stable pagination, and request compatibility.
5. Keep a warmed representative request below five seconds while returning the previously missing answer chunks.

## Non-Goals

- Guaranteeing every relevant chunk when more candidates exist than the global `rerank_top_n` budget.
- Adding domain aliases, brand lists, product-size parsing, or other business-specific query rules.
- Changing document parsing, index mappings, or stored chunk schemas.
- Adding datastore requests or increasing the default rerank budget.
- Tuning Elasticsearch, embedding, highlighting, or rerank model performance as part of this change.

## Terminology

- **Scoped document**: a document returned by literal document discovery, or explicitly supplied through `doc_ids`.
- **Scoped answer candidate**: a candidate from the `doc_answer` channel whose source document is scoped and whose content covers at least one current answer term.
- **Coverage selection**: a bounded first pass that protects one scoped answer candidate per logical report from being crowded out before reranking.
- **Global fill**: selection of all remaining candidates solely by the existing fused candidate score, without a per-document hard limit.

## Considered Approaches

### Increase `rerank_top_n` to 128

This is general and recovers more answer chunks, but it doubles the per-channel pool from 256 to 512 and doubles the rerank batch. The observed latency exceeded seven seconds, so this is useful as a diagnostic upper bound but not the production solution.

### Add a fixed score boost to `doc_answer`

This is a small change, but it is not deterministic under heavy candidate pressure. A boost that works for one corpus may be too weak or too strong for another, and it still cannot guarantee that a scoped document contributes an answer chunk.

### Use bounded scoped-answer coverage followed by unrestricted global fill

This approach provides a deterministic minimum guarantee, gives unused reserved capacity back to the global pool, permits multiple strong chunks from one document, and adds no expensive operations. This is the selected approach.

## Data Flow

```text
full / fallback / document_discovery / doc_answer
                         |
                         v
              content deduplication
                         |
                         v
                  RRF score fusion
                         |
                         v
        annotate scoped answer candidates
                         |
                         v
   KB coverage + bounded scoped-answer coverage
                         |
                         v
       unrestricted score-based global fill
                         |
                         v
                 rerank at top 64
                         |
                         v
       threshold + bounded output coverage
                         |
                         v
       unrestricted score-based pagination
```

## Candidate Annotation

`Dealer.retrieval()` will pass the discovered or explicitly scoped document IDs into candidate preparation. Candidate preparation will retain the existing channel membership collected during RRF fusion and annotate each prepared candidate with whether it is a scoped answer candidate.

A candidate is a scoped answer candidate only when all of the following are true:

1. It belongs to a scoped document, including any source represented by an exact-content duplicate.
2. It appeared in the `doc_answer` channel.
3. Its normalized display content contains at least one literal answer term from the current query plan.

Table structure remains a generic ranking bonus, not a requirement. Prose answers remain eligible. No domain term is introduced by the annotation logic.

Scoped answer candidates are ordered deterministically by:

1. Answer-term coverage ratio.
2. Structural evidence bonus.
3. Existing RRF candidate score.
4. Stable chunk identifier as a final tie-breaker.

## Rerank Candidate Allocation

The global rerank limit remains unchanged. For `rerank_top_n=64`, selection proceeds as follows:

1. Create one shared coverage budget for active-knowledge-base and scoped-answer guarantees. Its size is the larger of the active knowledge-base count and half of `rerank_top_n`, capped by `rerank_top_n`. With one active knowledge base and a rerank limit of 64, the shared coverage budget is 32.
2. Preserve existing active-knowledge-base coverage using the highest-scoring eligible candidates.
3. Within the remaining shared coverage budget, select at most one best scoped answer candidate per logical report. A candidate satisfying both knowledge-base and scoped-answer coverage consumes only one slot.
4. Return every unused shared coverage slot to the global pool.
5. Fill every remaining rerank slot by the existing fused score across all remaining candidates.
6. Do not apply a per-report or per-document hard cap during global fill.

For the observed request, 15 scoped reports consume 15 protected answer slots and leave 49 slots for unrestricted global competition. If a single document contains eight distinct high-scoring answer chunks, all eight may enter the rerank batch when their scores justify it.

Exact-content duplicates continue to use one rerank slot while preserving all source metadata. The global `rerank_top_n` remains the only hard candidate limit.

## Final Ranking And Pagination

Rerank scoring and threshold application remain unchanged. Final result ordering changes only in how coverage and document diversity are applied:

1. Consider only candidates that passed the existing relevance threshold.
2. Create a shared first-page coverage budget equal to the larger of the active knowledge-base count and half of `size`, capped by `size`.
3. Preserve active-knowledge-base coverage, then use the remaining shared coverage budget for the highest-reranked scoped answer candidates, with at most one guaranteed candidate per logical report. A candidate satisfying both guarantees consumes only one slot.
4. Return unused coverage capacity to the global result pool.
5. Fill all remaining positions by rerank score without a per-document maximum.
6. Build one deterministic ordered result list before slicing it by `page` and `size`, so subsequent pages contain the remaining eligible chunks without duplicates.

The coverage pass is a minimum guarantee, not a maximum. After coverage, additional chunks from any document compete normally. A document can therefore contribute more than three results when those chunks are strongly relevant.

## Degraded Behavior

- When document discovery returns no IDs, scoped coverage is disabled and all candidates use global score fill.
- When explicit `doc_ids` are supplied, those IDs define the document scope without running document discovery.
- When `doc_answer` fails, `full` and `fallback` continue through the existing channel-isolation behavior.
- When a scoped document has no candidate with literal answer-term evidence, it does not consume a protected slot.
- When the number of scoped reports exceeds the coverage budget, reports are ordered by their best scoped answer evidence; remaining candidates can still enter through global fill.
- When reranking fails, the existing normalized fusion-score fallback is preserved and the same allocation metadata is used.

## Observability

The structured `High-recall retrieval` record will add:

- `scoped_documents`
- `scoped_answer_candidates`
- `reserved_scoped_candidates`
- `global_fill_candidates`
- `returned_scoped_reports`
- `candidate_selection_ms`

The log continues to store only the query hash, not the raw question. Existing channel, candidate, rerank, report, knowledge-base, truncation, and total timing fields remain unchanged.

## Compatibility

- No API request or response field is removed or renamed.
- `rerank_top_n`, `top_k`, `page`, and `size` retain their existing meanings.
- No new configuration is required.
- The configured default for `rerank_top_n` is not changed; the performance acceptance profile passes 64 explicitly.
- Existing callers that omit `rerank_top_n` retain the configured default.
- The behavior remains bounded by `top_k`, `rerank_top_n`, and page size.

## Testing

### Candidate Selection

1. Reproduce more candidate reports than rerank slots. Give a scoped report a high-ranked identity chunk and a lower-ranked answer table. Verify that the answer table enters a 64-item rerank set.
2. Give one scoped report more than three distinct strong answer chunks. Verify that more than three can enter the rerank set and final result when global capacity permits.
3. Verify that a scoped chunk without any answer-term evidence does not consume a protected slot.
4. Verify that unused scoped coverage is returned to global fill.
5. Verify that exact duplicate content still consumes one rerank slot and retains every source.
6. Verify active knowledge bases remain represented.

### Orchestration And Fallback

1. Verify the datastore channel set and request count remain unchanged.
2. Verify `rerank_top_n=64` still produces a per-channel pool of 256 and sends at most 64 documents to the reranker.
3. Verify no-discovery, explicit-document, failed-discovery, failed-`doc_answer`, and rerank-failure paths retain useful global results.
4. Verify the implementation contains no test- or production-time dependency on tire brands, sizes, years, or domain vocabulary.

### Final Results And Pagination

1. Verify knowledge-base and scoped-answer guarantees share one bounded first-page coverage budget.
2. Verify unused output coverage is returned to global ranking.
3. Verify one document can return more than three distinct strong chunks.
4. Verify pagination is stable, contains no duplicate chunk IDs, and exposes remaining globally eligible chunks on later pages.
5. Verify `total` matches the number of globally pageable eligible chunks.

### Performance Acceptance

Run the same representative query at least ten times after warm-up with:

```text
top_k=1024
rerank_top_n=64
size=30
```

Acceptance criteria:

- Both previously observed `53-80` answer tables are returned.
- No datastore request is added.
- `selected_candidates` remains at most 64.
- Candidate selection takes no more than 100 ms.
- Warmed end-to-end retrieval completes within five seconds in the validation environment.
- The focused backend test suite and lint checks pass.

## Rollout And Rollback

Deploy this as a backend-only incremental change. Compare the new coverage metrics, target answer results, and warmed latency against the existing `rerank_top_n=64` baseline before changing any global defaults.

Rollback requires only reverting the candidate-allocation change and restarting the backend. No data, parsing, mapping, or index rollback is needed.
