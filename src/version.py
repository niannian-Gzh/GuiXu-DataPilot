"""运行时版本号。

打包后 `pyproject.toml` 不会随包，界面也不能各自写死 `v1.1.0`——
这里是一处来源：后端 `/update/check`、首页注入、关于页、开机页都从这里读。

安装包/EXE 的文件属性版本仍在 `packaging/version_info.txt` 和
`packaging/installer.iss` 里（构建元数据），发版时和这里一起改。
"""

__version__ = "1.1.0"
