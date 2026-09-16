import io
import base64
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


PRIMARY = "#2563eb"
SECONDARY = "#60a5fa"
ACCENT = "#f59e0b"


def _setup_font():
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
    plt.rcParams["axes.unicode_minus"] = False


def _style_axes(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#e2e8f0")
    ax.spines["bottom"].set_color("#e2e8f0")
    ax.tick_params(colors="#64748b", labelsize=10)
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color="#f1f5f9", linewidth=1)


def _fig_to_base64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def event_bar_chart(events: list) -> str:
    _setup_font()
    labels = [e["label"] for e in events]
    values = [e["count"] for e in events]

    fig, ax = plt.subplots(figsize=(7, 3.2))
    colors = [PRIMARY, SECONDARY, "#93c5fd", "#bfdbfe"][:len(labels)]
    bars = ax.bar(labels, values, color=colors, width=0.55,
                  edgecolor="none", zorder=3)

    for bar, v in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, v + max(values or [1]) * 0.03,
                str(v), ha="center", va="bottom",
                fontsize=12, fontweight="bold", color="#1e293b")

    ax.set_title("事件总览", fontsize=14, fontweight="bold",
                 color="#0f172a", pad=16)
    ax.set_ylabel("")
    ax.set_ylim(0, max(values or [1]) * 1.2)
    _style_axes(ax)

    result = _fig_to_base64(fig)
    plt.close(fig)
    return result


def owner_bar_chart(by_owner: list, title: str) -> str:
    if not by_owner:
        return ""
    _setup_font()

    owners = [o["owner"] for o in by_owner]
    values = [o["count"] for o in by_owner]

    # 横向柱状图
    fig, ax = plt.subplots(figsize=(7, max(2, len(owners) * 0.5 + 1)))
    y_pos = np.arange(len(owners))
    bars = ax.barh(y_pos, values, color=PRIMARY, height=0.6, edgecolor="none")

    for bar, v in zip(bars, values):
        ax.text(v + max(values or [1]) * 0.02, bar.get_y() + bar.get_height() / 2,
                str(v), va="center", ha="left",
                fontsize=11, fontweight="bold", color="#1e293b")

    ax.set_yticks(y_pos)
    ax.set_yticklabels(owners, fontsize=10, color="#334155")
    ax.invert_yaxis()
    ax.set_title(title, fontsize=13, fontweight="bold",
                 color="#0f172a", pad=12)
    ax.set_xlim(0, max(values or [1]) * 1.15)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#e2e8f0")
    ax.spines["bottom"].set_color("#e2e8f0")
    ax.tick_params(colors="#64748b")
    ax.xaxis.grid(True, color="#f1f5f9", linewidth=1)
    ax.set_axisbelow(True)

    result = _fig_to_base64(fig)
    plt.close(fig)
    return result