import concurrent.futures, time, statistics, requests

URL = "https://match-alerts-api-private.onrender.com/health"
N = 50

def hit(i):
    t0 = time.perf_counter()
    try:
        r = requests.get(URL, timeout=30)
        return (r.status_code, time.perf_counter()-t0, None)
    except Exception as e:
        return (0, time.perf_counter()-t0, type(e).__name__)

# warm-up
try:
    requests.get(URL, timeout=30)
except Exception:
    pass

start = time.perf_counter()
with concurrent.futures.ThreadPoolExecutor(max_workers=N) as ex:
    results = list(ex.map(hit, range(N)))
elapsed = time.perf_counter()-start
times = [x[1] for x in results]
ok = sum(1 for x in results if x[0] == 200)
errors = [x for x in results if x[0] != 200]
print(f"TOTAL={N}")
print(f"OK={ok}")
print(f"ERRORS={len(errors)}")
print(f"WALL={elapsed:.3f}s")
print(f"AVG={statistics.mean(times):.3f}s")
print(f"MEDIAN={statistics.median(times):.3f}s")
print(f"P95={sorted(times)[max(0,int(0.95*len(times))-1)]:.3f}s")
print(f"MAX={max(times):.3f}s")
if errors:
    print("ERROR_DETAILS=", errors[:10])
