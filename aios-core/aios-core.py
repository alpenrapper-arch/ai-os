#!/usr/bin/env python3
"""
AIOS-CORE — Autonomes Selbstheilungs-System
Erkennt Probleme, analysiert, löst, lernt.
"""
import os, sys, json, time, subprocess, logging, psutil
from datetime import datetime
from pathlib import Path

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('/var/log/aios-core.log'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger('AIOS-CORE')

DB_PATH = Path('/etc/aios/problem-db.json')
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Problem-Datenbank laden/erstellen
def load_db():
    if DB_PATH.exists():
        return json.loads(DB_PATH.read_text())
    default = {
        "known_fixes": {
            "service_crashed":    "systemctl restart {service}",
            "disk_full":          "journalctl --vacuum-size=200M && apt-get clean -y",
            "network_down":       "systemctl restart NetworkManager",
            "dns_broken":         "echo 'nameserver 8.8.8.8' > /etc/resolv.conf",
            "apt_broken":         "dpkg --configure -a && apt-get install -f -y",
            "swap_full":          "swapoff -a && swapon -a",
        },
        "learned_fixes": {},
        "stats": {"problems_detected": 0, "problems_fixed": 0, "uptime_start": str(datetime.now())}
    }
    DB_PATH.write_text(json.dumps(default, indent=2))
    return default

def save_db(db):
    DB_PATH.write_text(json.dumps(db, indent=2))

def run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, r.stdout + r.stderr
    except Exception as e:
        return False, str(e)

def notify(msg):
    """Telegram-Benachrichtigung"""
    token = "8756861685:AAFmhDCwt3YVLQSVdZa5HJ7kyBbhwH-eGoo"
    chat_id = "-1003731736531"
    topic_id = "44"
    text = f"🤖 AIOS-CORE: {msg}"
    run(f'curl -s "https://api.telegram.org/bot{token}/sendMessage" '
        f'-d chat_id={chat_id} -d message_thread_id={topic_id} '
        f'-d text="{text}" > /dev/null 2>&1')

# ─── WATCHER: Probleme erkennen ───────────────────────────────────────────────

def check_services():
    """Abgestürzte systemd-Services erkennen"""
    # Timer-gesteuerte Oneshot-Services ignorieren (fallen nach Abschluss als "failed" auf)
    IGNORE_SERVICES = {
        "develop.service",        # Oneshot, läuft 1x täglich, scheitert bei API-Problemen
        "stammtisch.service",     # Oneshot, 8h-Research Session
        "aios-builder.service",   # Oneshot, läuft alle 2h
        "backup-auto.service",    # Oneshot, läuft alle 3h
    }
    issues = []
    ok, out = run("systemctl list-units --state=failed --no-legend --plain")
    if ok and out.strip():
        for line in out.strip().split('\n'):
            svc = line.split()[0] if line.split() else None
            if svc and svc not in IGNORE_SERVICES:
                issues.append({"type": "service_crashed", "service": svc, "detail": line})
    return issues

def check_disk():
    """Festplatte > 90% = Problem (Snap-Partitionen ignorieren)"""
    issues = []
    for part in psutil.disk_partitions():
        # Snap-Mounts sind immer 100% voll — normal, ignorieren
        if "/snap/" in part.mountpoint or part.fstype == "squashfs":
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
            if usage.percent > 90:
                issues.append({"type": "disk_full", "mount": part.mountpoint,
                                "percent": usage.percent})
        except:
            pass
    return issues

def check_memory():
    """RAM < 150MB frei = Problem"""
    issues = []
    mem = psutil.virtual_memory()
    if mem.available < 150 * 1024 * 1024:
        # Top Memory-Fresser finden
        procs = sorted(psutil.process_iter(['pid','name','memory_percent']),
                       key=lambda p: p.info['memory_percent'], reverse=True)[:3]
        issues.append({"type": "memory_low", "available_mb": mem.available//1024//1024,
                       "top_procs": [f"{p.info['name']}({p.info['pid']})" for p in procs]})
    return issues

def check_network():
    """Netzwerk-Verbindung testen"""
    issues = []
    ok, _ = run("ping -c 1 -W 3 8.8.8.8")
    if not ok:
        issues.append({"type": "network_down", "detail": "Ping zu 8.8.8.8 fehlgeschlagen"})
    return issues

def check_smart():
    """Festplatten S.M.A.R.T. Status"""
    issues = []
    ok, out = run("smartctl -H /dev/sda 2>/dev/null | grep -i 'SMART overall'")
    if ok and "PASSED" not in out and out.strip():
        issues.append({"type": "disk_smart_fail", "detail": out.strip()})
    return issues

# ─── ANALYST: Problem analysieren ─────────────────────────────────────────────

def analyze(issue, db):
    """Bekannte Lösung suchen oder KI fragen"""
    itype = issue["type"]

    # Bekannte Lösungen
    if itype in db["known_fixes"]:
        fix_cmd = db["known_fixes"][itype]
        if "{service}" in fix_cmd and "service" in issue:
            fix_cmd = fix_cmd.format(service=issue["service"])
        return fix_cmd

    if itype in db["learned_fixes"]:
        return db["learned_fixes"][itype]

    # KI fragen (Ollama lokal)
    prompt = f"Linux Problem: {json.dumps(issue)}. Gib NUR einen Shell-Befehl zurück der das löst. Keine Erklärung."
    ok, answer = run(f'ollama run llama3.1:8b "{prompt}" 2>/dev/null', timeout=60)
    if ok and answer.strip():
        cmd = answer.strip().split('\n')[0]
        if len(cmd) < 200 and not cmd.startswith('#'):
            return cmd

    return None

# ─── FIXER: Problem lösen ─────────────────────────────────────────────────────

def fix(issue, fix_cmd, db):
    """Fix ausführen, Ergebnis prüfen, in DB speichern"""
    log.info(f"FIX: {issue['type']} → {fix_cmd}")
    ok, out = run(fix_cmd, timeout=60)

    if ok:
        log.info(f"✅ GELÖST: {issue['type']}")
        notify(f"✅ Problem gelöst: {issue['type']}")
        # Lernen: neue Lösungen speichern
        if issue["type"] not in db["known_fixes"]:
            db["learned_fixes"][issue["type"]] = fix_cmd
        db["stats"]["problems_fixed"] += 1
    else:
        log.warning(f"❌ Fix fehlgeschlagen: {issue['type']} | {out[:200]}")
        notify(f"❌ Konnte nicht lösen: {issue['type']} - Manuelle Hilfe nötig")

    save_db(db)
    return ok

# ─── HAUPTSCHLEIFE ────────────────────────────────────────────────────────────

def main():
    log.info("🤖 AIOS-CORE gestartet")
    notify("🤖 AIOS-CORE gestartet — Autonomes Monitoring aktiv")
    db = load_db()
    cycle = 0

    while True:
        cycle += 1
        all_issues = []

        # Alle Checks
        all_issues += check_services()
        all_issues += check_disk()
        all_issues += check_memory()
        all_issues += check_network()

        # S.M.A.R.T. nur alle 10 Zyklen (langsam)
        if cycle % 10 == 0:
            all_issues += check_smart()

        db["stats"]["problems_detected"] += len(all_issues)

        for issue in all_issues:
            log.warning(f"⚠️  Problem: {issue}")
            fix_cmd = analyze(issue, db)
            if fix_cmd:
                fix(issue, fix_cmd, db)
            else:
                log.error(f"Keine Lösung gefunden für: {issue['type']}")
                notify(f"⚠️ Unbekanntes Problem: {issue['type']} — Analyse läuft")

        if not all_issues and cycle % 60 == 0:
            log.info(f"✅ System gesund | Gelöst bisher: {db['stats']['problems_fixed']}")

        time.sleep(60)

if __name__ == "__main__":
    main()
