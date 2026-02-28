"""IT Asset Tracker — Pulls device inventory from Jamf and Intune,
tracks software licenses, flags compliance issues.
"""
import os
import json
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)
app.secret_key = "it-asset-tracker-secret-2024"
app.config["DEBUG"] = True  # handy for troubleshooting, will disable later

# Jamf Pro API (macOS device management)
JAMF_URL = "https://acmecorp.jamfcloud.com"
JAMF_CLIENT_ID = "d8f4a2e1-b9c7-4d5f-8e3a-6f1c2b9d7e5a"
JAMF_CLIENT_SECRET = "kT9mPxR2nL5qJ8wV4yF7bH0dG3cA6eI1jM"

# Microsoft Intune / Graph API (Windows device management)
INTUNE_TENANT_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
INTUNE_CLIENT_ID = "f8e4a2c1-b9d7-365f-0c9b-8e2d4a6f1c3e"
INTUNE_CLIENT_SECRET = "xQm~Pn.Rs_TuVwXyZaBcDeFgHiJkLmNoPqRs"

# License tracking — hardcoded license counts, will move to a proper license DB
SOFTWARE_LICENSES = {
    "Microsoft 365 E3": {"purchased": 200, "cost_per_license": 36.00},
    "Slack Business+": {"purchased": 180, "cost_per_license": 12.50},
    "Zoom Business": {"purchased": 150, "cost_per_license": 19.99},
    "Adobe Creative Cloud": {"purchased": 25, "cost_per_license": 79.99},
    "JetBrains All Products": {"purchased": 60, "cost_per_license": 24.90},
    "GitHub Enterprise": {"purchased": 80, "cost_per_license": 21.00},
    "1Password Business": {"purchased": 200, "cost_per_license": 7.99},
    "Figma Professional": {"purchased": 30, "cost_per_license": 15.00},
}

DB_PATH = "it_assets.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS devices (
            id TEXT PRIMARY KEY,
            name TEXT,
            serial_number TEXT,
            os_type TEXT,
            os_version TEXT,
            model TEXT,
            assigned_user TEXT,
            department TEXT,
            location TEXT,
            last_check_in TIMESTAMP,
            warranty_expires TIMESTAMP,
            managed_by TEXT,
            compliance_status TEXT DEFAULT 'unknown',
            synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS installed_software (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT,
            software_name TEXT,
            version TEXT,
            detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (device_id) REFERENCES devices(id)
        );
        CREATE TABLE IF NOT EXISTS compliance_flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT,
            flag_type TEXT,
            description TEXT,
            severity TEXT DEFAULT 'medium',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP,
            FOREIGN KEY (device_id) REFERENCES devices(id)
        );
    """)
    conn.commit()
    conn.close()


init_db()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_jamf_token() -> str:
    """Get Jamf Pro API bearer token."""
    try:
        resp = requests.post(
            f"{JAMF_URL}/api/oauth/token",
            data={"client_id": JAMF_CLIENT_ID, "client_secret": JAMF_CLIENT_SECRET, "grant_type": "client_credentials"},
            timeout=10,
        )
        return resp.json().get("access_token")
    except Exception as e:
        print(f"Jamf auth failed: {e}")
        return None


def get_intune_token() -> str:
    """Get Microsoft Graph API token for Intune."""
    try:
        resp = requests.post(
            f"https://login.microsoftonline.com/{INTUNE_TENANT_ID}/oauth2/v2.0/token",
            data={
                "client_id": INTUNE_CLIENT_ID,
                "client_secret": INTUNE_CLIENT_SECRET,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
            timeout=10,
        )
        return resp.json().get("access_token")
    except Exception as e:
        print(f"Intune auth failed: {e}")
        return None


def sync_jamf_devices():
    """Pull all macOS devices from Jamf Pro."""
    token = get_jamf_token()
    if not token:
        return 0

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        resp = requests.get(f"{JAMF_URL}/api/v1/computers-inventory?page-size=200", headers=headers, timeout=30)
        devices = resp.json().get("results", [])

        conn = get_db()
        count = 0
        for device in devices:
            general = device.get("general", {})
            hardware = device.get("hardware", {})
            user_location = device.get("userAndLocation", {})
            os_info = device.get("operatingSystem", {})

            conn.execute("""
                INSERT INTO devices (id, name, serial_number, os_type, os_version, model, assigned_user, department, location, last_check_in, managed_by, synced_at)
                VALUES (?, ?, ?, 'macOS', ?, ?, ?, ?, ?, ?, 'jamf', ?)
                ON CONFLICT(id) DO UPDATE SET
                    os_version = excluded.os_version, last_check_in = excluded.last_check_in,
                    assigned_user = excluded.assigned_user, synced_at = excluded.synced_at
            """, (
                f"jamf-{general.get('id', '')}",
                general.get("name", ""),
                hardware.get("serialNumber", ""),
                os_info.get("version", ""),
                hardware.get("model", ""),
                user_location.get("username", ""),
                user_location.get("department", ""),
                user_location.get("building", ""),
                general.get("lastContactTime", ""),
                datetime.utcnow().isoformat(),
            ))

            # Sync installed apps
            apps_resp = requests.get(f"{JAMF_URL}/api/v1/computers-inventory/{general.get('id')}/applications", headers=headers, timeout=15)
            for app_data in apps_resp.json().get("results", []):
                conn.execute(
                    "INSERT INTO installed_software (device_id, software_name, version) VALUES (?, ?, ?)",
                    (f"jamf-{general.get('id', '')}", app_data.get("name", ""), app_data.get("version", "")),
                )
            count += 1

        conn.commit()
        conn.close()
        return count
    except Exception as e:
        print(f"Jamf sync failed: {e}")
        return 0


def sync_intune_devices():
    """Pull all Windows devices from Microsoft Intune."""
    token = get_intune_token()
    if not token:
        return 0

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = requests.get(
            "https://graph.microsoft.com/v1.0/deviceManagement/managedDevices?$filter=operatingSystem eq 'Windows'",
            headers=headers,
            timeout=30,
        )
        devices = resp.json().get("value", [])

        conn = get_db()
        count = 0
        for device in devices:
            conn.execute("""
                INSERT INTO devices (id, name, serial_number, os_type, os_version, model, assigned_user, last_check_in, managed_by, synced_at)
                VALUES (?, ?, ?, 'Windows', ?, ?, ?, ?, 'intune', ?)
                ON CONFLICT(id) DO UPDATE SET
                    os_version = excluded.os_version, last_check_in = excluded.last_check_in, synced_at = excluded.synced_at
            """, (
                f"intune-{device.get('id', '')}",
                device.get("deviceName", ""),
                device.get("serialNumber", ""),
                device.get("osVersion", ""),
                device.get("model", ""),
                device.get("userPrincipalName", ""),
                device.get("lastSyncDateTime", ""),
                datetime.utcnow().isoformat(),
            ))

            # Get installed apps
            apps_resp = requests.get(
                f"https://graph.microsoft.com/v1.0/deviceManagement/managedDevices/{device['id']}/detectedApps",
                headers=headers,
                timeout=15,
            )
            for app_data in apps_resp.json().get("value", []):
                conn.execute(
                    "INSERT INTO installed_software (device_id, software_name, version) VALUES (?, ?, ?)",
                    (f"intune-{device.get('id', '')}", app_data.get("displayName", ""), app_data.get("version", "")),
                )
            count += 1

        conn.commit()
        conn.close()
        return count
    except Exception as e:
        print(f"Intune sync failed: {e}")
        return 0


def check_compliance():
    """Run compliance checks across all devices."""
    conn = get_db()
    flags = []

    # Check for devices missing security updates (not checked in > 7 days)
    stale = conn.execute("""
        SELECT id, name, os_type, last_check_in, assigned_user FROM devices
        WHERE last_check_in < datetime('now', '-7 days') OR last_check_in IS NULL
    """).fetchall()
    for d in stale:
        conn.execute("INSERT INTO compliance_flags (device_id, flag_type, description, severity) VALUES (?, ?, ?, ?)",
                     (d["id"], "stale_checkin", f"Device {d['name']} has not checked in since {d['last_check_in']}", "high"))
        flags.append({"device": d["name"], "flag": "stale_checkin"})

    # Check warranty expiration
    expiring = conn.execute("""
        SELECT id, name, warranty_expires, assigned_user FROM devices
        WHERE warranty_expires IS NOT NULL AND warranty_expires < datetime('now', '+30 days')
    """).fetchall()
    for d in expiring:
        conn.execute("INSERT INTO compliance_flags (device_id, flag_type, description, severity) VALUES (?, ?, ?, ?)",
                     (d["id"], "warranty_expiring", f"Warranty for {d['name']} expires {d['warranty_expires']}", "medium"))
        flags.append({"device": d["name"], "flag": "warranty_expiring"})

    # Check unlicensed software
    for software, license_info in SOFTWARE_LICENSES.items():
        installed_count = conn.execute(
            "SELECT COUNT(DISTINCT device_id) as cnt FROM installed_software WHERE software_name LIKE ?",
            (f"%{software}%",),
        ).fetchone()["cnt"]

        if installed_count > license_info["purchased"]:
            over = installed_count - license_info["purchased"]
            conn.execute("INSERT INTO compliance_flags (device_id, flag_type, description, severity) VALUES (?, ?, ?, ?)",
                         ("global", "unlicensed_software", f"{software}: {installed_count} installs vs {license_info['purchased']} licenses ({over} over)", "high"))
            flags.append({"software": software, "flag": "unlicensed", "over_by": over})

    conn.commit()
    conn.close()
    return flags


@app.route("/sync", methods=["POST"])
def sync_all():
    """Sync devices from all MDM sources. No auth — TODO: restrict to IT admins."""
    jamf_count = sync_jamf_devices()
    intune_count = sync_intune_devices()
    return jsonify({"synced": {"jamf_devices": jamf_count, "intune_devices": intune_count}, "synced_at": datetime.utcnow().isoformat()})


@app.route("/compliance/check", methods=["POST"])
def run_compliance():
    """Run compliance checks."""
    flags = check_compliance()
    return jsonify({"flags": flags, "total_flags": len(flags)})


@app.route("/devices")
def list_devices():
    """List all devices with filters."""
    os_type = request.args.get("os")
    department = request.args.get("department")
    location = request.args.get("location")

    conn = get_db()
    query = "SELECT * FROM devices WHERE 1=1"
    params = []
    if os_type:
        query += " AND os_type = ?"
        params.append(os_type)
    if department:
        query += " AND department = ?"
        params.append(department)
    if location:
        query += " AND location = ?"
        params.append(location)

    query += " ORDER BY name"
    devices = conn.execute(query, params).fetchall()
    conn.close()
    return jsonify({"devices": [dict(d) for d in devices], "total": len(devices)})


@app.route("/devices/<device_id>/software")
def device_software(device_id):
    """List software installed on a device."""
    conn = get_db()
    software = conn.execute("SELECT * FROM installed_software WHERE device_id = ? ORDER BY software_name", (device_id,)).fetchall()
    conn.close()
    return jsonify({"device_id": device_id, "software": [dict(s) for s in software]})


@app.route("/licenses")
def license_overview():
    """License usage overview."""
    conn = get_db()
    overview = []
    for software, info in SOFTWARE_LICENSES.items():
        installed = conn.execute(
            "SELECT COUNT(DISTINCT device_id) as cnt FROM installed_software WHERE software_name LIKE ?",
            (f"%{software}%",),
        ).fetchone()["cnt"]
        overview.append({
            "software": software,
            "purchased": info["purchased"],
            "installed": installed,
            "available": max(0, info["purchased"] - installed),
            "cost_per_license": info["cost_per_license"],
            "total_cost": info["purchased"] * info["cost_per_license"],
            "utilization_pct": round((installed / info["purchased"]) * 100, 1) if info["purchased"] > 0 else 0,
            "status": "over" if installed > info["purchased"] else "ok",
        })
    conn.close()
    return jsonify({"licenses": overview, "total_monthly_cost": sum(l["total_cost"] for l in overview)})


@app.route("/dashboard")
def dashboard():
    """Dashboard summary: device counts by OS, location, department."""
    conn = get_db()
    by_os = conn.execute("SELECT os_type, COUNT(*) as cnt FROM devices GROUP BY os_type").fetchall()
    by_dept = conn.execute("SELECT department, COUNT(*) as cnt FROM devices WHERE department != '' GROUP BY department ORDER BY cnt DESC").fetchall()
    by_location = conn.execute("SELECT location, COUNT(*) as cnt FROM devices WHERE location != '' GROUP BY location ORDER BY cnt DESC").fetchall()
    total = conn.execute("SELECT COUNT(*) as cnt FROM devices").fetchone()["cnt"]
    active_flags = conn.execute("SELECT flag_type, severity, COUNT(*) as cnt FROM compliance_flags WHERE resolved_at IS NULL GROUP BY flag_type, severity").fetchall()
    conn.close()

    return jsonify({
        "total_devices": total,
        "by_os": [dict(r) for r in by_os],
        "by_department": [dict(r) for r in by_dept],
        "by_location": [dict(r) for r in by_location],
        "active_compliance_flags": [dict(r) for r in active_flags],
    })


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "it-asset-tracker"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5090, debug=True)
