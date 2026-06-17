#!/usr/bin/env python3
"""
VirtualRM Architecture Diagram
Style: Individual colored boxes per service, minimal labels, clean arrows.
Modelled after enterprise Azure architecture diagrams.
"""

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle

# --- palette by category ---
BLUE = "#B3D9FF"       # compute / application
ORANGE = "#FFD6A5"     # ingestion / pipeline
PURPLE = "#D1B3FF"     # AI services
PINK = "#FFB3C6"       # external sources / inputs
GRAY = "#E0E0E0"       # infra / DevOps
WHITE = "#FFFFFF"

fig, ax = plt.subplots(figsize=(14, 11), dpi=160)
ax.set_xlim(0, 14)
ax.set_ylim(0, 11)
ax.axis("off")
fig.patch.set_facecolor("#FFFFF0")
ax.set_facecolor("#FFFFF0")


def svc(x, y, w, h, label, color, fs=13, bold=False):
    """Draw a single service box."""
    patch = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.02,rounding_size=0.12",
        linewidth=1.5,
        edgecolor="#444",
        facecolor=color,
        zorder=2,
    )
    ax.add_patch(patch)
    ax.text(x + w / 2, y + h / 2, label, ha="center", va="center",
            fontsize=fs, fontweight="bold" if bold else "normal", color="#1a1a1a", zorder=3)


def container(x, y, w, h, label):
    """Draw a container boundary (solid black border)."""
    patch = Rectangle((x, y), w, h, linewidth=2.5, edgecolor="#111", facecolor=WHITE, zorder=1)
    ax.add_patch(patch)
    ax.text(x + 0.15, y + h - 0.25, label, fontsize=14, fontweight="bold", va="top", color="#222", zorder=3)


def dashed_container(x, y, w, h, label):
    """Draw a dashed container boundary (managed service)."""
    patch = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.02,rounding_size=0.15",
        linewidth=2.2,
        edgecolor="#333",
        facecolor=WHITE,
        linestyle=(0, (6, 4)),
        zorder=1,
    )
    ax.add_patch(patch)
    ax.text(x + w / 2, y + 0.3, label, fontsize=12, ha="center", color="#333", zorder=3)


def conn(x1, y1, x2, y2, label="", color="#333", lw=1.8, bidirectional=False):
    """Draw a connection arrow."""
    s = "<->" if bidirectional else "->"
    arr = FancyArrowPatch(
        (x1, y1), (x2, y2),
        arrowstyle=s, mutation_scale=16,
        linewidth=lw, color=color, zorder=4,
    )
    ax.add_patch(arr)
    if label:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        ax.text(mx, my + 0.2, label, fontsize=10, ha="center", color="#555", zorder=5)


# ========== LAYOUT ==========

# --- Top: Entry Points ---
ax.text(3.5, 10.4, "Web Client", fontsize=16, fontweight="bold", ha="center")
ax.text(10.5, 10.4, "Phone Call", fontsize=16, fontweight="bold", ha="center")

# Web client UI box
svc(2.0, 9.4, 3.0, 0.8, "Virtual RM UI", PINK, fs=13, bold=True)

# Phone
svc(9.5, 9.4, 2.0, 0.8, "Inbound Call", PINK, fs=12)

# --- Middle: Core Application ---
container(1.0, 6.2, 6.5, 2.6, "Inbound Call Center Voice Agent")
svc(1.5, 6.8, 2.8, 1.2, "Azure\nContainer App", BLUE, fs=13, bold=True)
# Agent info
ax.text(4.8, 8.2, "Anika - Triage", fontsize=9, color="#333", zorder=3)
ax.text(4.8, 7.8, "Meera - Credit Cards", fontsize=9, color="#333", zorder=3)
ax.text(4.8, 7.4, "Priya - Loans", fontsize=9, color="#333", zorder=3)
ax.text(4.8, 7.0, "Kavya - Savings", fontsize=9, color="#333", zorder=3)
ax.text(4.8, 6.6, "Riya - General Banking", fontsize=9, color="#333", zorder=3)

# --- Right: Azure Communication Path ---
svc(8.5, 6.8, 3.2, 0.9, "Azure Communication\nServices", BLUE, fs=11)

# --- Bottom Left: AI Services (dashed = managed) ---
dashed_container(1.5, 2.2, 4.5, 3.0, "")
svc(2.2, 3.6, 3.0, 1.0, "Voice Live API", PURPLE, fs=13, bold=True)
svc(2.5, 2.5, 2.5, 0.8, "Microsoft Foundry", PURPLE, fs=11)

# --- Bottom Right: DevOps Pipeline ---
svc(8.5, 4.2, 2.4, 0.9, "Container\nRegistry", GRAY, fs=11)
svc(11.5, 4.2, 2.0, 0.9, "Docker", GRAY, fs=12, bold=True)
svc(11.5, 2.8, 2.0, 0.9, "GitHub Repo", GRAY, fs=11)

# --- Auth label ---
ax.text(1.5, 1.4, "Auth: Managed Identity", fontsize=12, color="#555", style="italic")

# ========== CONNECTIONS ==========

# Web Client -> Container App
conn(3.5, 9.4, 3.5, 9.0)

# Phone -> ACS
conn(10.1, 9.4, 10.1, 7.7, "call")

# ACS -> Container App
conn(8.5, 7.25, 7.5, 7.25, "audio")

# Container App -> Voice Live API
conn(4.3, 6.2, 4.3, 5.2)

# Container Registry -> Container App
conn(8.5, 4.65, 7.5, 6.0)

# GitHub -> Docker -> Container Registry
conn(12.5, 3.7, 12.5, 4.2)
conn(11.5, 4.65, 10.9, 4.65)

plt.tight_layout()
plt.savefig(
    r"c:\Users\vguptha\OneDrive - Microsoft\Documents\work\Hands-on learning\VirtualRM\docs\architecture-professional.png",
    dpi=200,
    bbox_inches="tight",
    facecolor="#FFFFF0",
    edgecolor="none",
)
print("Generated docs/architecture-professional.png")
