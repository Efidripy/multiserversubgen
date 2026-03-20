/**
 * Backend Async Optimization Guide & Utilities
 * Patterns for FastAPI async/await and connection pooling
 */

/**
 * Python FastAPI Backend Optimization Checklist:
 * 
 * 1. Use asyncio.gather() for parallel I/O operations:
 * ```python
 * async def get_clients_and_nodes(node_id):
 *     clients_task = fetch_clients_async(node_id)
 *     nodes_task = fetch_node_info_async(node_id)
 *     clients, node = await asyncio.gather(clients_task, nodes_task)
 *     return clients, node
 * ```
 * 
 * 2. Connection Pooling (PostgreSQL example):
 * ```python
 * from asyncpg import create_pool
 * pool = await create_pool("postgresql://...", min_size=10, max_size=20)
 * async with pool.acquire() as conn:
 *     result = await conn.fetch("SELECT ...")
 * ```
 * 
 * 3. Batch Database Queries (avoid N+1):
 * ```python
 * # Instead of:
 * for client_id in client_ids:
 *     client = await db.get_client(client_id)
 * 
 * # Do:
 * clients = await db.get_clients_batch(client_ids)
 * ```
 * 
 * 4. Cache frequently accessed data:
 * ```python
 * from functools import lru_cache
 * import aioredis
 * 
 * redis = await aioredis.create_redis_pool("redis://localhost")
 * 
 * async def get_nodes_cached():
 *     cached = await redis.get("nodes:all")
 *     if cached:
 *         return json.loads(cached)
 *     nodes = await fetch_nodes_from_db()
 *     await redis.setex("nodes:all", 300, json.dumps(nodes))
 *     return nodes
 * ```
 * 
 * 5. Use uvicorn workers (not single-threaded):
 * ```bash
 * # workers = number of CPU cores + 1
 * uvicorn main:app --workers 5 --worker-class uvicorn.workers.UvicornWorker
 * ```
 * 
 * 6. Stream large responses:
 * ```python
 * @app.get("/large-export")
 * async def export_data():
 *     async def generate():
 *         for chunk in data_chunks:
 *             yield json.dumps(chunk) + "\\n"
 *     return StreamingResponse(generate(), media_type="application/x-ndjson")
 * ```
 * 
 * 7. Profile bottlenecks:
 * ```python
 * import cProfile, pstats
 * profiler = cProfile.Profile()
 * profiler.enable()
 * # ... code to profile ...
 * profiler.disable()
 * stats = pstats.Stats(profiler)
 * stats.sort_stats('cumulative').print_stats(10)
 * ```
 */

export const ASYNC_BACKEND_OPTIMIZATIONS = {
  parallel_io: 'Use asyncio.gather() for concurrent I/O',
  connection_pooling: 'Maintain persistent DB connections',
  batch_queries: 'Fetch multiple records in single query',
  redis_caching: 'Cache hot data in Redis',
  streaming: 'Stream large responses instead of buffering',
  worker_scaling: 'Run multiple uvicorn workers',
  profiling: 'Profile endpoints to find bottlenecks',
};

/**
 * Frontend utilities for monitoring backend performance
 */
export function createAsyncBackendMetrics() {
  return {
    endpoints: {} as Record<string, {
      avgLatency: number;
      p95Latency: number;
      p99Latency: number;
      errorRate: number;
      requestCount: number;
    }>,
    
    recordEndpointCall(endpoint: string, latencyMs: number, success: boolean) {
      if (!this.endpoints[endpoint]) {
        this.endpoints[endpoint] = {
          avgLatency: 0,
          p95Latency: 0,
          p99Latency: 0,
          errorRate: 0,
          requestCount: 0,
        };
      }
      
      const stats = this.endpoints[endpoint];
      stats.requestCount++;
      stats.avgLatency = (stats.avgLatency * (stats.requestCount - 1) + latencyMs) / stats.requestCount;
      
      if (!success) {
        stats.errorRate = ((stats.errorRate * (stats.requestCount - 1)) + 1) / stats.requestCount;
      }
    },
    
    getMetrics() {
      return this.endpoints;
    }
  };
}

export const backendMetrics = createAsyncBackendMetrics();
