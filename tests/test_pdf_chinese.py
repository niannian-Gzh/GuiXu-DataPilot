import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path


def test_matplotlib_chinese():
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(["下发", "下证", "打回", "重提"], [5, 3, 2, 1])
    ax.set_title("本周项目事件")

    out = Path("tests/_test_chart.png")
    fig.savefig(out, dpi=100, bbox_inches="tight")
    plt.close(fig)

    assert out.exists()
    print(f"✅ matplotlib 中文图表已生成：{out}")


if __name__ == "__main__":
    test_matplotlib_chinese()
    print("\n打开 tests/_test_chart.png 确认中文显示正常。")