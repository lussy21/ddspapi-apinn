import concurrent.futures, time, statistics, requests, json

APP_URL = "https://match-alerts-private.onrender.com/"
API_URL = "https://match-alerts-api-private.onrender.com/api"
N = 50

def load_page(i):
    t0 = time.perf_counter()
    try:
        r = requests.get(APP_URL, timeout=30)
        return ("page", r.status_code, time.perf_counter()-t0, None)
    except Exception as e:
        return ("page", 0, time.perf_counter()-t0, type(e).__name__)

def load_alerts(i):
    t0 = time.perf_counter()
    try:
        r = requests.post(API_URL, data={"action":"alerts","token":"LOADTEST_INVALID_SESSION"}, timeout=45)
        try:
            body = r.json()
            err = body.get("error")
        except Exception:
            err = "BAD_JSON"
        return ("alerts", r.status_code, time.perf_counter()-t0, err)
    except Exception as e:
        return ("alerts", 0, time.perf_counter()-t0, type(e).__name__)

# warm the free service first so startup time does not distort concurrency
try:
    requests.get("https://match-alerts-api-private.onrender.com/health", timeout=30)
except Exception:
    pass

start = time.perf_counter()
with concurrent.futures.ThreadPoolExecutor(max_workers=N*2) as ex:
    futures = []
    for i in range(N):
        futures.append(ex.submit(load_page, i))
        futures.append(ex.submit(load_alerts, i))
    results = [f.result() for f in futures]
elapsed = time.perf_counter()-start

for kind in ("page","alerts"):
    subset=[x for x in results if x[0]==kind]
    times=[x[2] for x in subset]
    ok=sum(1 for x in subset if x[1]==200)
    errors=[x for x in subset if x[1]!=200]
    print(f"{kind.upper()} TOTAL={len(subset)} OK_HTTP={ok} HTTP_ERRORS={len(errors)}")
    print(f"{kind.upper()} AVG={statistics.mean(times):.3f}s MEDIAN={statistics.median(times):.3f}s P95={sorted(times)[max(0,int(0.95*len(times))-1)]:.3f}s MAX={max(times):.3f}s")
    if kind=="alerts":
        outcomes={}
        for x in subset:
            outcomes[x[3]]=outcomes.get(x[3],0)+1
        print("ALERTS_OUTCOMES="+json.dumps(outcomes,sort_keys=True))
print(f"WALL={elapsed:.3f}s")
