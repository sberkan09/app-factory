"""Çalışan bir App Factory sunucusuna birden çok fikir gönderir ve her run
onay kapısına (release aşaması) gelene ya da durana kadar bekler.

Kullanım:
    uvicorn app_factory.main:app --port 8000 &
    python scripts/batch_run.py --base http://localhost:8000 --out runs_report.json

Onay verilmez: run'lar `awaiting_approval`'da bırakılır (deploy yok).
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import httpx

DEFAULT_IDEAS = [
    ("Günlük içilen su bardaklarını tek dokunuşla sayan uygulama", "flutter"),
    ("Pomodoro tekniğiyle 25 dakikalık odak seansı başlatan zamanlayıcı", "flutter"),
    ("Arkadaşlarla hesabı kişi başına bölen bahşiş hesaplayıcı", "flutter"),
    ("Bitkileri ne zaman sulayacağını hatırlatan tek ekranlı takip uygulaması", "react-native"),
    ("Her gün tek bir şükran notu yazdıran minimal günlük", "react-native"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--out", default="runs_report.json")
    ap.add_argument("--timeout", type=int, default=3600, help="run başına saniye")
    ap.add_argument("--retries", type=int, default=1, help="hata alan run için otomatik retry sayısı")
    ap.add_argument("--platform", choices=["flutter", "react-native"],
                    help="yalnızca bu platformdaki fikirleri çalıştır")
    args = ap.parse_args()

    http = httpx.Client(base_url=args.base, timeout=60)
    runs = []
    ideas = [(i, p) for i, p in DEFAULT_IDEAS if args.platform in (None, p)]
    for idea, platform in ideas:
        r = http.post("/runs", json={"idea": idea, "platform": platform})
        r.raise_for_status()
        runs.append({"run_id": r.json()["run_id"], "idea": idea, "platform": platform, "retries": 0})
        print(f"başlatıldı {runs[-1]['run_id']}: {idea}", flush=True)

    deadline = time.time() + args.timeout
    pending = {r["run_id"]: r for r in runs}
    while pending and time.time() < deadline:
        time.sleep(10)
        for run_id, meta in list(pending.items()):
            d = http.get(f"/runs/{run_id}").json()
            if d.get("can_retry") and meta["retries"] < args.retries:
                meta["retries"] += 1
                print(f"[{run_id}] hata: {d.get('error')!r} -> retry", flush=True)
                http.post(f"/runs/{run_id}/retry")
                continue
            if d["awaiting_approval"] or d.get("can_retry") or d["phase"] in ("done", "failed"):
                meta["final"] = d
                del pending[run_id]
                print(f"[{run_id}] bitti: phase={d['phase']} awaiting={d['awaiting_approval']} "
                      f"qa={d['qa_iteration']} maliyet=${d['usage']['cost_usd']}", flush=True)

    for run_id, meta in pending.items():
        meta["final"] = http.get(f"/runs/{run_id}").json()
        meta["timed_out"] = True

    with open(args.out, "w") as f:
        json.dump(runs, f, ensure_ascii=False, indent=2)
    ok = sum(1 for r in runs if r["final"]["awaiting_approval"] and r["final"].get("release_candidate"))
    total = sum(r["final"]["usage"]["cost_usd"] for r in runs)
    print(f"\n{ok}/{len(runs)} run release aşamasına ulaştı · toplam tahmini maliyet ${total:.2f}")
    return 0 if ok == len(runs) else 1


if __name__ == "__main__":
    sys.exit(main())
