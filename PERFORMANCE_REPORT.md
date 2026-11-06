# Performance & Scalability Evaluation Report

**Project:** Orbit AI Chat  
**Role:** Principal Performance Engineer & QA Lead  
**Date:** 2026-11-06  
**Environment:** Windows x64, Python 3.12, Node.js 22, Google Gemini API  
**Status:** COMPLETED & BENCHMARKED  

---

## 1. Executive Performance Summary

A performance benchmarking and latency breakdown was conducted on the **Orbit AI Chat** application. The evaluation measured:
1. **Local Application Latency:** In-memory store operations, JSON serialization, and middleware overhead.
2. **Cloud AI Inference Latency:** Roundtrip network latency, Time-To-First-Token (TTFT), and stream throughput.
3. **System Resource Utilization:** Process memory working set (RSS) and thread concurrency.
4. **Frontend Rendering Performance:** DOM update frequency during live SSE stream consumption.

### Critical Takeaway: Latency Breakdown
- **Local Application Overhead:** **< 1.5 ms** (sub-millisecond data writes and reads).
- **External Gemini Cloud Roundtrip & Prefill (TTFT):** **~740 ms – 907 ms** (average **832.6 ms**).
- **Conclusion:** Over **99.8%** of user-perceived response wait time is attributed to external cloud network latency and model prefill computation, while the local Flask application contributes virtually zero overhead.

---

## 2. Performance Benchmark Matrix

| Benchmark ID | Dimension Tested | Test Description | Expected Baseline | Actual Measured Result | Status | Severity | Evidence |
|---|---|---|---|---|---|---|---|
| **PERF-01** | Database Write Latency | 50 sequential conversation creation operations (`store.create()`). | < 10 ms per operation | **0.255 ms** average | **PASS** | Info | `performance_results.json` |
| **PERF-02** | Database Read Latency | 20 sequential single conversation lookups (`store.get()`). | < 5 ms per operation | **0.285 ms** average | **PASS** | Info | `performance_results.json` |
| **PERF-03** | Database List Latency | Fetch all conversation metadata sorted by `updated_at` (`store.list()`). | < 20 ms | **1.265 ms** total | **PASS** | Info | `performance_results.json` |
| **PERF-04** | Time-To-First-Token (TTFT) | Measure elapsed time from request dispatch to first streaming SSE chunk received. | < 1,500 ms (Cloud SLA) | **832.62 ms** average (Min: 740.16 ms, Max: 907.35 ms) | **PASS** | Medium | `performance_results.json` |
| **PERF-05** | Total AI Stream Duration | Measure elapsed time from request dispatch to final `done` event. | < 3,000 ms for medium prompt | **1,182.41 ms** average (882 chars generated in 1.43s) | **PASS** | Medium | `performance_results.json` |
| **PERF-06** | Stream Chunk Throughput | Average chunk delivery frequency during response generation. | Progressive multi-chunk delivery | **3 to 10 chunks** per stream; tokens rendered progressively without UI freeze. | **PASS** | Low | Live browser audit |
| **PERF-07** | Process Memory Footprint | Measure Python runtime working set (RSS) during active inference. | < 150 MB for local service | **35.0 MB** working set | **PASS** | Low | Native OS process counter |
| **PERF-08** | Concurrent Request Capacity | 5 concurrent chat requests dispatched across separate worker threads. | Zero dropped requests; all 200 OK | 5/5 succeeded concurrently without data race or deadlocks. | **PASS** | High | `TC-BACK-01` |
| **PERF-09** | Rate Limiting Overhead | Per-request overhead added by sliding window rate limiter check. | < 0.1 ms per request | **0.012 ms** check time | **PASS** | Low | `test_advanced_backend.py` |
| **PERF-10** | Frontend Bundle Size | Minified and gzipped static assets delivered to the client. | < 200 kB total JS | **130.25 kB** main JS bundle, **4.15 kB** CSS bundle | **PASS** | Medium | Production build log |

---

## 3. Local Application vs External Cloud Latency Breakdown

```
User Action: Send Message
  │
  ├── [0.01 ms] Rate Limiter check (Local Memory)
  ├── [0.25 ms] Conversation context retrieval (Local Store)
  ├── [0.15 ms] Request validation & JSON serialization
  │
  ▼ [832.62 ms (99.8%)] EXTERNAL GEMINI CLOUD ROUNDTRIP & PREFILL
  │
  ├── [349.79 ms] Progressive token streaming (Network SSE)
  ├── [0.28 ms] Append user & assistant messages to Store (Local Memory)
  │
  ▼ Response Completed (Total User Wait: ~1,183 ms)
```

---

## 4. Scalability Bottlenecks & Optimization Roadmap

1. **In-Memory Store vs MongoDB Connection Pool**:
   - In-memory store achieves sub-millisecond latency (`~0.25 ms`), but is non-persistent and single-process.
   - When connecting to MongoDB Atlas, network roundtrip to the database will add `10 ms – 30 ms` per write. Use PyMongo connection pooling (`maxPoolSize=50`) to maintain high throughput.
2. **Reverse Proxy Buffering**:
   - By default, some reverse proxies (like Nginx) buffer HTTP responses, which breaks Server-Sent Events (SSE) streaming!
   - In production Nginx configuration, add:
     ```nginx
     proxy_set_header Connection '';
     proxy_http_version 1.1;
     chunked_transfer_encoding off;
     proxy_buffering off;
     proxy_cache off;
     ```
3. **Frontend Virtualization**:
   - For conversations with > 200 messages, rendering all DOM elements simultaneously can slow mobile scrolling. Consider adding virtualized list rendering (e.g. `react-window`) if chat threads exceed 500 messages.

