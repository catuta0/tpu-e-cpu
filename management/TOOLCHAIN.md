# Toolchain (discovered 2026-11-04)

| Item | Value | How verified |
|---|---|---|
| OS | Ubuntu 24.04.5 LTS, kernel 6.18.44-fc-v233 | /etc/os-release, uname |
| CPU / RAM / disk | 4 cores / 15 GiB / ~31 GiB free | nproc, free, df |
| GPU | none | — |
| Claude Code | 2.1.318 (Claude Code) | claude --version |
| Python | Python 3.13.18 (venv .venv) | python --version |
| numpy / scikit-learn | 2.5.4 / 1.9.1 | import |
| Yosys | Yosys 0.70 (git sha1 28ba3cb92, Release, (YoWASP, pip) | yowasp-yosys -V |
| nextpnr | nextpnr-0.11.1 himbaechel-gowin (YoWASP, pip) | --version |
| Apicula (gowin_pack) | 0.32 (pip) | pip show |
| Icarus Verilog | 12.0 (stable) (apt) | iverilog -V |
| Verilator | 5.020 (apt) | verilator --version |
| LaTeX | pdfTeX 3.141592653-2.6-1.40.25 (TeX Live, latexmk, IEEEtran.cls (apt) | kpsewhich IEEEtran.cls |

## Installation log
- apt (system-wide in ephemeral container, approved by user 2026-11-04): iverilog verilator
  texlive-latex-recommended texlive-publishers texlive-latex-extra texlive-fonts-recommended latexmk
  → logs/apt_install.log (APT_EXIT=0)
- pip (project venv): yowasp-yosys yowasp-nextpnr-himbaechel-gowin apycula numpy scikit-learn
  matplotlib → logs/pip_install.log (PIP_EXIT=0)

## MCP / integrations
- No project `.mcp.json` servers needed: all EDA tools are local CLIs invoked through Bash.
  This is a shell-tool integration, NOT an MCP integration (labelled honestly).
- Session-level MCP servers (GitHub, Google, etc.) exist but are not used by the engineering flow.

## Smoke-test status
See management/SMOKE_TESTS.md.
