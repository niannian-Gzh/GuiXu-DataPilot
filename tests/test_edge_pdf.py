import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from services.report.render import html_to_pdf


def test_edge_pdf():
    html = """
    <html>
    <head>
    <meta charset="utf-8">
    <style>
        body { font-family: 'Microsoft YaHei', sans-serif; padding: 40px; }
        h1 { color: #333; }
        table { border-collapse: collapse; width: 100%; margin-top: 20px; }
        th, td { border: 1px solid #ccc; padding: 8px; text-align: left; }
        th { background: #f0f0f0; }
    </style>
    </head>
    <body>
        <h1>数据处理 Agent · 周报测试</h1>
        <p>这是一段中文测试。如果能看到，说明 PDF 中文没问题。</p>
        <table>
            <tr><th>项目</th><th>负责人</th></tr>
            <tr><td>智慧园区综合管理平台</td><td>张三</td></tr>
        </table>
    </body>
    </html>
    """

    out = Path("tests/_test_edge.pdf")
    html_to_pdf(html, out)
    print(f"✅ PDF 已生成：{out}")
    print("打开看：中文显示正常吗？表格样式对吗？")


if __name__ == "__main__":
    test_edge_pdf()