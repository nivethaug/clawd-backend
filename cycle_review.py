from services.dev_cycles import store

for cid in [2, 4]:
    c = store.get_cycle(cid)
    tasks = store.get_tasks(cid)
    st = c.get("status") or "?"
    pid = c.get("project_id") or "?"
    print(f"=== Cycle {cid} | status: {st} | project: {pid} ===")
    for t in tasks:
        r = t.get("result") or {}
        ts = t.get("status") or "?"
        tk = t.get("kind") or "?"
        rc = t.get("repair_count") or 0
        tt = (t.get("title") or "")[:45]
        print(f"  task {t['position']} [{ts}] {tk:8s} | repairs:{rc} | {tt}")
        vd = r.get("verdict")
        ev = str(r.get("evidence") or "")[:130]
        er = str(r.get("error") or "")[:130]
        if vd:
            print(f"    verdict: {vd} | evidence: {ev}")
        if er and er != "None":
            print(f"    error: {er}")
    print()

# also dump last 5 agent messages for each cycle to see what the user saw
for cid in [2, 4]:
    msgs = store.get_messages(cid)
    print(f"--- Cycle {cid} last messages ---")
    for m in msgs[-5:]:
        print(f"  [{m['role']}] {m['content'][:120]}")
    print()
