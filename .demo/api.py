"""历史占位文件（v0.7.31.0 修正）。

原内容是一行非 Python 文本，疑似某次演示把 markdown 片段误存成了 .py：

    api.py: generate OpenAPI schema from dataclass

这类文件不会影响打包（pyproject.toml 显式列出包，不做自动发现），
也不影响 pytest（只收集 tests/），但会让**任何全仓语法检查 / 静态工具**
直接抛 SyntaxError —— 例如本轮新增的全仓 compile 自检就把它揪了出来。

处置：改写为合法的空模块，只保留占位说明，不删文件、不改路径。
"""
