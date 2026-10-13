"""
Pipeline Scheduler Simulator (Windows / Local Dev)

In script baraye shabih-saziye ejraye har 1 daghigheye pipeline rooye Windows ast.
Viizhegi-ha:
- Har 60 saniye yekbar `main.run_pipeline()` ro seda mizane.
- Moddate zamane ejraye har dor ro mohasebe mikone.
- Agar yek dor masalan 15 saniye tool bekeshe, daghighan 45 saniye sabr mikone ta dore badi ras-e saniye 00 shoroo beshe.
- Agar yek dor bishtar az 60 saniye tool bekeshe, bedone vaghfe mire dore badi (PostgreSQL Advisory Lock dar main.py az overlap jologiri mikone).
- Ba zadan Ctrl+C be tore aramesh va tamiz khorooj mikone.
"""

import sys
import time
from datetime import datetime

import main


INTERVAL_SECONDS = 60


def run_scheduler():
    print("=" * 65)
    print("🚀 Currency Pipeline Local Scheduler (Windows Simulator)")
    print(f"⏰ Interval: Har {INTERVAL_SECONDS} saniye yekbar")
    print("🛑 Baraye tavaghofe barname, kelid-haye [Ctrl + C] ra feshar dahid.")
    print("=" * 65)

    iteration = 1

    try:
        while True:
            start_time = time.monotonic()
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            print(f"\n[Iteration #{iteration}] ─── Shorooe Run dar: {now_str}")

            try:
                result = main.run_pipeline()
                if result:
                    status = result.get("status", "unknown")
                    pub_count = result.get("published_rates", 0)
                    snap_id = result.get("snapshot_id")
                    print(f"  ✅ Run ba movafaghiat anjam shod! Snapshot: {snap_id} | Status: {status} | Published Rates: {pub_count}")
                else:
                    print("  ⚠️ Run skip shod (Advisory Lock fa'al bood ya ejraye ghabli dar jaryan ast).")
            except Exception as e:
                print(f"  ❌ Khata dar ejraye pipeline: {e}")

            elapsed = time.monotonic() - start_time
            print(f"  ⏱️ Zamane sefri shode in dor: {elapsed:.2f} saniye")

            # Mohasebeye zaman-e baqimande ta dore badi
            sleep_time = max(0.0, INTERVAL_SECONDS - elapsed)

            if sleep_time > 0:
                print(f"  💤 Sabr baraye {sleep_time:.2f} saniye ta dore ba'di...")
                time.sleep(sleep_time)
            else:
                print("  ⚡ Ejra bishtar az 60 saniye tool keshid; foran dore ba'di shoroo mishavad.")

            iteration += 1

    except KeyboardInterrupt:
        print("\n\n" + "=" * 65)
        print("🛑 Dastoor tavaghof (Ctrl + C) daryaft shod. Scheduler ba movafaghiat baste shod.")
        print("=" * 65)
        sys.exit(0)


if __name__ == "__main__":
    run_scheduler()
