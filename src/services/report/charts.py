"""画图。**只认 labels 和 values，不认业务。**

旧版有两个函数：`event_bar_chart`（写死"事件总览"）和
`owner_bar_chart`（写死"负责人"）。它们知道软著表长什么样，
换一张表就没有图可画。现在统一成一个 `bar_chart`——数据和标题
都由调用方给，这里只负责把数画成柱子。
"""

import io
import base64
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


PRIMARY = "#2563eb"


def _setup_font():
    # 三平台各给一个中文字体名 —— matplotlib 不会自己回落，找不到就是一排方框。
    # 这是全项目仅剩的一处平台绑定，补上它，换平台就不用再改代码
    plt.rcParams["font.sans-serif"] = [
        "Microsoft YaHei",   # Windows
        "PingFang SC",       # macOS
        "Noto Sans CJK SC",  # Linux
        "SimHei",
    ]
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


def bar_chart(labels: list, values: list, title: str = "") -> str:
    """画一张柱状图，返回 base64 PNG。

    标签超过 8 个就转横向——竖着排会挤成一团，横向才有地方写。
    值不是数字的按 0 处理：图是给人看趋势的，一张画不出来的图
    不如一张空图（调用方那边还有表可以看具体值）。
    """
    if not labels:
        return ""

    vals = [v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0
            for v in values]
    labels = [str(x) for x in labels]
    _setup_font()

    top = max(vals or [1]) or 1
    horizontal = len(labels) > 8

    if horizontal:
        fig, ax = plt.subplots(figsize=(7, max(2.4, len(labels) * 0.42 + 1)))
        y = np.arange(len(labels))
        bars = ax.barh(y, vals, color=PRIMARY, height=0.6, edgecolor="none", zorder=3)
        for bar, v in zip(bars, vals):
            ax.text(v + top * 0.02, bar.get_y() + bar.get_height() / 2,
                    str(v), va="center", ha="left",
                    fontsize=10, fontweight="bold", color="#1e293b")
        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=10, color="#334155")
        ax.invert_yaxis()
        ax.set_xlim(0, top * 1.15)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color("#e2e8f0")
        ax.spines["bottom"].set_color("#e2e8f0")
        ax.tick_params(colors="#64748b")
        ax.xaxis.grid(True, color="#f1f5f9", linewidth=1)
        ax.set_axisbelow(True)
    else:
        fig, ax = plt.subplots(figsize=(7, 3.2))
        bars = ax.bar(labels, vals, color=PRIMARY, width=0.55,
                      edgecolor="none", zorder=3)
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2, v + top * 0.03,
                    str(v), ha="center", va="bottom",
                    fontsize=12, fontweight="bold", color="#1e293b")
        ax.set_ylim(0, top * 1.2)
        _style_axes(ax)

    if title:
        ax.set_title(title, fontsize=13, fontweight="bold",
                     color="#0f172a", pad=14)

    result = _fig_to_base64(fig)
    plt.close(fig)
    return result
