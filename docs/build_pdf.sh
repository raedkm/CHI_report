#!/bin/bash
# Build the epidemiological methodology PDF
# Prerequisites: tectonic is at ../tools/tectonic.exe (auto-downloaded on first run)
cd "$(dirname "$0")"
../tools/tectonic.exe epidemiological_methodology.tex
echo "Done: docs/epidemiological_methodology.pdf"
