# AI-OS — Self-Healing Linux Distribution

Ein KI-gesteuertes Linux-Betriebssystem mit Windows 11 Look & Feel.

## Features
- 🤖 AIOS-CORE: Self-Healing Daemon (repariert sich selbst)
- 🎨 Windows 11 Look (KDE Plasma)
- ⚡ Dual-Mode: LXQt (alte Hardware) + KDE (modern)
- 🔄 OTA Auto-Updates (täglich, automatisch)
- 🛡️ Security Hardening (UFW, AppArmor, Fail2ban)
- 🧠 Claude/Ollama AI-Integration

## Update-Server
Installierte Systeme pullen Updates automatisch von diesem Repo.

## Struktur
- `aios-core/` — Self-Healing Daemon
- `scripts/` — System-Skripte (updater, hardware-detect, status)
- `build/` — ISO Build-Konfiguration (live-build)
