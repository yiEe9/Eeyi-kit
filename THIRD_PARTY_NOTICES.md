# 第三方许可与来源

## wechat/wxmem.py

`wechat/wxmem.py` 的长期记忆存储方式移植自：

- 项目：`dsh-plugin-memory`
- 仓库：https://github.com/LittleBlackTong/dsh-plugin-memory
- 许可：MIT

原项目是 JS/Cordis 插件；本仓库按微信 bot 的结构改写为 Python，并按联系人分目录。检索设计还参考了 `dsh-memory-plugin`（https://github.com/ttweip/dsh-memory-plugin）的 PROTOCOL，该仓库未声明许可证，未复制其代码。

下面是上游项目的 MIT 许可全文。

```
MIT License

Copyright (c) dsh-plugin-memory contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

其余 Python 依赖（`rapidocr-onnxruntime`、`opencv-python-headless`、`numpy`）、微信 Linux 客户端与系统包按各自的许可分发，本仓库不包含它们的源码。
