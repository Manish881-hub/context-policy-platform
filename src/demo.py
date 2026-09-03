"""Manual demo — the hiring brief scenario as runnable proof."""
from pathlib import Path
import tempfile
from src.provisioning.db import init_db
from src.tools.wifi_tool import get_wifi_credentials_tool

def main():
    # Use temp DB so demo doesn't pollute
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "demo.db"
        init_db(db)
        print("=== Technician on site (field_app, GPS+checkin, site match) ===")
        ok = get_wifi_credentials_tool(
            subscriber_id="S123",
            technician_id="T42",
            queue_origin="field_app",
            gps_verified_on_site=True,
            field_checkin_active=True,
            site_id="SITE_A",
            subscriber_site_id="SITE_A",
            db_path=db,
        )
        print(ok.model_dump_json(indent=2))
        print()

        print("=== Same request from unauthorized support queue ===")
        denied = get_wifi_credentials_tool(
            subscriber_id="S123",
            technician_id="T42",  # same tech, different queue!
            queue_origin="support_unauthorized",
            gps_verified_on_site=True,
            field_checkin_active=True,
            site_id="SITE_A",
            subscriber_site_id="SITE_A",
            db_path=db,
        )
        print(denied.model_dump_json(indent=2))
        print()
        print("✓ Proof: same identity, same subscriber, different context → different decision. Evaluated fresh per tool call, not prompt.")

if __name__ == "__main__":
    main()
