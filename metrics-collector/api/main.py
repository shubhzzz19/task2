from fastapi import FastAPI, HTTPException, Query
from datetime import datetime, timedelta
from typing import List, Dict
from collections import deque
import os
import psutil
import requests
from redis import Redis

app = FastAPI()

# Environment variables & configuration
STARROCKS_FE = os.getenv("STARROCKS_FE", "http://localhost:8030")
STARROCKS_BE_NODES = [
    os.getenv("BE1", "be1:8040"),
    os.getenv("BE2", "be2:8040"),
    os.getenv("BE3", "be3:8040")
]

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# In-memory storage for demo purposes
metrics_store = {
    "documentdb": {
        "inserts": deque(maxlen=10000),
        "latencies": deque(maxlen=10000)
    },
    "starrocks": {
        "queries": deque(maxlen=10000)
    },
    "redis": {
        "commands": deque(maxlen=10000),
        "latencies": deque(maxlen=10000)
    }
}


@app.get("/")
async def read_root():
    return {"Hello": "World"}


@app.post("/track/redis/command")
async def track_redis_command(command: str = Query(...), latency_ms: float = Query(...)):
    """Track Redis command latency"""
    metrics_store["redis"]["latencies"].append(latency_ms)
    metrics_store["redis"]["commands"].append({
        "timestamp": datetime.utcnow(),
        "command": command,
        "latency": latency_ms
    })
    return {"status": "success"}


@app.get("/metrics/redis/status")
async def get_redis_metrics():
    """Get Redis server metrics via INFO command"""
    try:
        redis = Redis(host=REDIS_HOST, port=REDIS_PORT)
        info = redis.info()
        return {
            "memory_used": info.get('used_memory', 0),
            "ops_per_sec": info.get('instantaneous_ops_per_sec', 0),
            "connected_clients": info.get('connected_clients', 0),
            "command_stats": info.get('commandstats', {})
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Redis connection failed: {str(e)}")


@app.get("/metrics/redis/summary")
async def get_redis_summary():
    """Get Redis latency percentiles"""
    latencies = list(metrics_store["redis"]["latencies"])
    if not latencies:
        return {"p50": 0, "p75": 0, "p90": 0, "p99": 0}
    
    latencies_sorted = sorted(latencies)
    n = len(latencies_sorted)
    def percentile(p):
        idx = min(n - 1, max(0, int(p * n)))
        return latencies_sorted[idx]
    
    return {
        "p50": percentile(0.5),
        "p75": percentile(0.75),
        "p90": percentile(0.9),
        "p99": percentile(0.99)
    }


@app.get("/metrics/starrocks/nodes")
async def get_node_metrics():
    """Get CPU/Memory for all StarRocks nodes (FE + BEs)"""
    nodes = []

    # FE metrics (local machine)
    try:
        fe_cpu = psutil.cpu_percent(interval=1)
        fe_mem = psutil.virtual_memory().percent
        nodes.append({"node": "fe", "cpu": fe_cpu, "memory": fe_mem})
    except Exception as e:
        nodes.append({"node": "fe", "error": str(e)})

    # BE metrics (remote)
    for i, be in enumerate(STARROCKS_BE_NODES, 1):
        try:
            response = requests.get(f"http://{be}/metrics", timeout=2)
            response.raise_for_status()
            be_data = response.json()
            nodes.append({
                "node": f"be{i}",
                "cpu": be_data.get("cpu", 0),
                "memory": be_data.get("memory", 0)
            })
        except Exception as e:
            nodes.append({"node": f"be{i}", "error": str(e)})

    return {"nodes": nodes}


@app.get("/metrics/starrocks/queries/slowest")
async def get_slow_queries(limit: int = 100):
    """Get slowest queries from FE"""
    try:
        response = requests.get(f"{STARROCKS_FE}/api/slow_queries?limit={limit}")
        response.raise_for_status()
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get slow queries: {str(e)}")


@app.post("/track/documentdb/insert")
async def track_insert(latency_ms: float = Query(...)):
    """Track DocumentDB insert latency"""
    metrics_store["documentdb"]["latencies"].append(latency_ms)
    metrics_store["documentdb"]["inserts"].append({
        "timestamp": datetime.utcnow(),
        "latency": latency_ms
    })
    return {"status": "success"}


@app.get("/metrics/documentdb/summary")
async def get_documentdb_summary():
    """Get DocumentDB insert metrics and latency percentiles"""
    latencies = list(metrics_store["documentdb"]["latencies"])
    if not latencies:
        return {
            "inserts_last_min": 0,
            "inserts_last_sec": 0,
            "p50": 0,
            "p75": 0,
            "p90": 0,
            "p99": 0
        }
    
    latencies_sorted = sorted(latencies)
    n = len(latencies_sorted)
    def percentile(p):
        idx = min(n - 1, max(0, int(p * n)))
        return latencies_sorted[idx]
    
    now = datetime.utcnow()
    inserts = list(metrics_store["documentdb"]["inserts"])
    inserts_last_min = sum(1 for i in inserts if i["timestamp"] > now - timedelta(minutes=1))
    inserts_last_sec = sum(1 for i in inserts if i["timestamp"] > now - timedelta(seconds=1))

    return {
        "inserts_last_min": inserts_last_min,
        "inserts_last_sec": inserts_last_sec,
        "p50": percentile(0.5),
        "p75": percentile(0.75),
        "p90": percentile(0.9),
        "p99": percentile(0.99)
    }


@app.get("/metrics/starrocks/queries/percentiles")
async def get_query_percentiles():
    """Calculate query duration percentiles"""
    queries = list(metrics_store["starrocks"]["queries"])
    if not queries:
        return {"p50": 0, "p75": 0, "p90": 0, "p99": 0}
    
    durations = [q["duration"] for q in queries]
    durations_sorted = sorted(durations)
    n = len(durations_sorted)
    def percentile(p):
        idx = min(n - 1, max(0, int(p * n)))
        return durations_sorted[idx]

    return {
        "p50": percentile(0.5),
        "p75": percentile(0.75),
        "p90": percentile(0.9),
        "p99": percentile(0.99)
    }
