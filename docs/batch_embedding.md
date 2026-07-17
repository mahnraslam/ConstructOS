Task: Refactor the embedding pipeline to use true batch embeddings instead of one API call per chunk.

Current Problem:
The current implementation loops through every document chunk and calls the embedding API individually. This results in N network requests for N chunks, which significantly increases latency and API overhead.

Current Workflow:
for chunk in chunks:
    embedding = embed(chunk.text)
    store_embedding(chunk, embedding)

Problems:
- One HTTP request per chunk.
- High network latency.
- Poor throughput for large documents.
- Unnecessary API overhead.
- Difficult to scale.

Required Solution:
Implement true batch embeddings.

Requirements:
1. Collect all chunk texts before generating embeddings.
2. Send multiple texts in a single embedding API request.
3. Support configurable batch sizes (e.g., EMBED_BATCH_SIZE=100).
4. If the document exceeds the batch size, split into multiple batches.
5. Preserve chunk ordering so each embedding maps back to the correct chunk.
6. Keep retry logic for failed API calls.
7. Log batch progress.
8. Do not change downstream vector storage logic except for receiving embeddings in batches.

Target Workflow:

Parse PDF
    ↓
Generate chunks
    ↓
Split into batches
    ↓
One embedding request per batch
    ↓
Receive embeddings
    ↓
Store all embeddings in ChromaDB

Expected Benefits:
- Reduce API calls from N to ceil(N / batch_size)
- Lower upload latency
- Better API utilization
- Easier future parallelization

Do not change application behavior except improving the embedding pipeline.