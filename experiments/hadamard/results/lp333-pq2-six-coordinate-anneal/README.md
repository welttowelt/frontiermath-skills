# LP333 pq2 six-coordinate escape anneal

This frozen arm preserves the exact prescribed \(pq^2\) compression and the
integer full-length PAF objective. Seven proposals out of eight are the
baseline one-swap move; every eighth atomically composes three margin-
preserving swaps, so it can change up to six coordinates without accepting
either intermediate state.

Promotion requires objective zero plus the independent bit-rotation audit.
Any nonzero endpoint is workload evidence only.
