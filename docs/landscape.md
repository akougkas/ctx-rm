# Context Management Landscape

A research summary and positioning for **ctx-rm** (context removal), an approach to managing LLM context windows through asynchronous eviction with recoverability.

---

## Taxonomy: Three Approaches

| Approach | Description | When Applied | Recoverability |
|----------|-------------|--------------|----------------|
| **Context curation** | Careful selection of what to load into context before inference | Pre-inference, gatekeeper | N/A (never loaded) |
| **Context compaction** | Summarize, compress, or distill content to fit within budget | Pre-inference or inline | Partial (lossy) |
| **Context removal** | Ingest freely; background process evicts content from active context | During/after inference | Yes (evicted to memory store) |

**ctx-rm** focuses on the third: allow the agent to "bombard" the context, then a background context manager silently removes low-value content while preserving evicted material in a retrievable store.

---

## Related Work

### Prompt Compression and Pruning

- **LLMLingua** (Microsoft Research, EMNLP'23, ACL'24)  
  Token-level iterative compression using a small LM to identify non-essential tokens. Achieves up to 20× compression with minimal performance loss.  
  - [GitHub](https://github.com/microsoft/LLMLingua) | [Paper](https://aclanthology.org/2023.emnlp-main.825/)

- **LongLLMLingua** (ACL'24)  
  Query-aware compression for long contexts; mitigates "lost in the middle" and improves RAG by ~21% at ¼ tokens.  
  - [Paper](https://aclanthology.org/2024.acl-long.91/)

- **LLMLingua-2** (ACL'24 Findings)  
  Data-distilled token classification for task-agnostic compression; 3–6× faster than LLMLingua.  
  - [Paper](https://aclanthology.org/2024.findings-acl.57/)

- **Selective Context** (Li et al., EMNLP'23)  
  Self-information-based pruning of redundant context. ~50% context reduction, ~36% memory and ~32% time savings.  
  - [GitHub](https://github.com/liyucheng09/Selective_Context) | [Paper](https://arxiv.org/abs/2310.06201)

**Relation to ctx-rm:** These methods operate *before* inference (curation/compaction). ctx-rm operates *during* a session, evicting content asynchronously and storing it for retrieval.

---

### Agent Memory Systems

- **MemGPT / Letta**  
  Two-tier memory: in-context (editable) vs out-of-context (archival, recall). Agent uses tools (`memory_insert`, `archival_memory_search`) to manage memory. MemGPT evolved into Letta ([letta-ai/letta](https://github.com/letta-ai/letta)).  
  - [Original MemGPT](https://github.com/deductive-ai/MemGPT) | [Paper](https://arxiv.org/abs/2310.08560) | [Letta Docs](https://docs.letta.com/concepts/memgpt)

- **Mem0**  
  Universal memory layer with user/session/agent tiers; hybrid vector + KV + graph storage.  
  - [GitHub](https://github.com/mem0ai/mem0)

- **Zep**  
  Long-term memory service with auto-summarization, vector search, and token counting for prompt assembly.  
  - [GitHub](https://github.com/getzep/zep)

**Relation to ctx-rm:** These systems manage *external* memory and retrieval. ctx-rm complements them by defining *what* gets evicted from the active context and *when*, feeding into such stores.

---

### RAG and Contextual Compression

- **ContextualCompressionRetriever** (LangChain)  
  Wraps a base retriever with a DocumentCompressor to filter/compress retrieved docs by query relevance.

- **LlamaIndex + LLMLingua**  
  LongLLMLingua integration for RAG document compression.

**Relation to ctx-rm:** RAG compression targets retrieval output. ctx-rm targets the *conversation/agent* context buffer.

---

### Evaluation Benchmarks

- **LongBench** (ACL'24)  
  Bilingual, multitask benchmark for long-context understanding (21 datasets, 6 task types).  
  - [GitHub](https://github.com/THUDM/LongBench) | [Paper](https://aclanthology.org/2024.acl-long.172/)

- **LongBench v2** (2024)  
  Harder tasks (8k–2M words); multiple-choice QA; human baseline ~53.7%.  
  - [Project Page](https://longbench2.github.io) | [Dataset](https://huggingface.co/datasets/THUDM/LongBench-v2)

- **Characterizing Prompt Compression** (arXiv:2407.08892)  
  Compares extractive, abstractive, and token-pruning methods; extractive often best at 10× compression.

---

## Positioning: Where ctx-rm Fits

```text
                    ┌─────────────────────────────────────────────────────────┐
                    │                    Context Management                     │
                    └─────────────────────────────────────────────────────────┘
                                              │
         ┌────────────────────────────────────┼────────────────────────────────────┐
         │                                    │                                    │
         ▼                                    ▼                                    ▼
   ┌──────────────┐                    ┌──────────────┐                    ┌──────────────┐
   │  Curation    │                    │  Compaction  │                    │   Removal    │
   │  (gatekeep)  │                    │  (summarize) │                    │  (evict)     │
   └──────────────┘                    └──────────────┘                    └──────────────┘
   LLMLingua,                          LongLLMLingua,                       ctx-rm
   Selective Context                   LLMLingua-2                           (this project)
```

**ctx-rm** is under-explored: most work focuses on pre-inference compression or external memory. The idea of *background eviction* with *recoverability*—letting the agent ingest freely while a manager removes low-salience content—is a distinct research direction.

---

## Bibliography

1. Jiang, H., Wu, Q., Lin, C.-Y., Yang, Y., Qiu, L. (2023). LLMLingua: Compressing Prompts for Accelerated Inference of Large Language Models. EMNLP.
2. Jiang, H., Wu, Q., Luo, X., Li, D., Lin, C.-Y., Yang, Y., Qiu, L. (2024). LongLLMLingua: Accelerating and Enhancing LLMs in Long Context Scenarios via Prompt Compression. ACL.
3. Pan, Z., et al. (2024). LLMLingua-2: Data Distillation for Efficient and Faithful Task-Agnostic Prompt Compression. ACL Findings.
4. Li, Y., Dong, B., Lin, C., Guerin, F. (2023). Compressing Context to Enhance Inference Efficiency of Large Language Models. EMNLP. arXiv:2310.06201.
5. Packer, C., et al. (2023). MemGPT: Towards LLMs as Operating Systems. [arXiv:2310.08560](https://arxiv.org/abs/2310.08560).
6. Bai, Y., et al. (2024). LongBench: A Bilingual, Multitask Benchmark for Long Context Understanding. ACL.
7. Bai, Y., et al. (2024). LongBench v2: Towards Deeper Understanding and Reasoning on Realistic Long-context Multitasks. arXiv:2412.15204.
