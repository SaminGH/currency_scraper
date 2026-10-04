import json
import os
import uuid
from datetime import datetime


# ============================================================
# تنظیمات Logger
# ============================================================

LOG_DIR = "logs"

LOG_FILE = os.path.join(
    LOG_DIR,
    "pipeline.jsonl"
)


# ============================================================
# Run ID و Snapshot ID فعلی
# ============================================================

_current_run_id = None
_current_snapshot_id = None


# ============================================================
# ساخت پوشه Logs
# ============================================================

try:

    os.makedirs(
        LOG_DIR,
        exist_ok=True
    )

except Exception:
    # Logger نباید باعث Crash شدن Pipeline شود
    pass


# ============================================================
# ساخت Run ID
# ============================================================

def start_run():

    global _current_run_id
    global _current_snapshot_id

    try:

        timestamp = datetime.now().strftime(
            "%Y%m%d-%H%M%S"
        )

        random_id = uuid.uuid4().hex[:4]

        _current_run_id = (
            f"{timestamp}-{random_id}"
        )

        # هر Pipeline Run جدید
        # Snapshot قبلی نباید باقی بماند
        _current_snapshot_id = None

        return _current_run_id

    except Exception:

        # اگر ساخت Run ID هم شکست خورد
        # Pipeline نباید Crash شود

        _current_run_id = "unknown-run"
        _current_snapshot_id = None

        return _current_run_id


# ============================================================
# گرفتن Run ID فعلی
# ============================================================

def get_run_id():

    return _current_run_id


# ============================================================
#  تنظیم واسه چایلد Run ID فعلی
# ============================================================

def set_run_id(run_id):

    global _current_run_id

    try:

        _current_run_id = run_id

    except Exception:

        # Logger نباید باعث Crash شدن Pipeline شود
        pass

# ============================================================
# تنظیم Snapshot ID فعلی
# ============================================================

def set_snapshot_id(snapshot_id):

    global _current_snapshot_id

    try:

        _current_snapshot_id = snapshot_id

    except Exception:

        # Logger نباید باعث Crash شدن Pipeline شود
        pass


# ============================================================
# گرفتن Snapshot ID فعلی
# ============================================================

def get_snapshot_id():

    return _current_snapshot_id


# ============================================================
# ثبت Log Event
# ============================================================

def log_event(
    level,
    event,
    component,
    **kwargs
):

    try:

        # ----------------------------------------------------
        # اگر Run هنوز ساخته نشده باشد
        # ----------------------------------------------------

        run_id = _current_run_id

        if run_id is None:

            run_id = "unknown-run"


        # ----------------------------------------------------
        # Snapshot ID فعلی
        # ----------------------------------------------------

        snapshot_id = _current_snapshot_id


        # ----------------------------------------------------
        # ساخت Event
        # ----------------------------------------------------

        log_data = {

            "timestamp": datetime.now().isoformat(
                timespec="seconds"
            ),

            "run_id": run_id,

            "snapshot_id": snapshot_id,

            "level": level,

            "event": event,

            "component": component
        }


        # ----------------------------------------------------
        # اضافه کردن اطلاعات اضافی
        # ----------------------------------------------------

        log_data.update(
            kwargs
        )


        # ----------------------------------------------------
        # نوشتن JSONL
        # ----------------------------------------------------

        with open(
            LOG_FILE,
            "a",
            encoding="utf-8"
        ) as file:

            file.write(
                json.dumps(
                    log_data,
                    ensure_ascii=False
                )
                + "\n"
            )


    except Exception:
        # ----------------------------------------------------
        # Logger NEVER باید Pipeline را Crash کند
        # ----------------------------------------------------

        pass