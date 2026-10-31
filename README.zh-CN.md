# clickpost-printer

[日本語 README](README.md) ・ **[在线 DEMO（示例站点）](https://clickpost.l-l.li/)**

从**日本邮政クリックポスト**的运单 PDF 里切出 A6 面单，直接打到家用的
**DeTong DP305P** 热敏标签机（76 × 130 mm）上。不经过官方 App，也不经过任何云服务 ——
直接按逆向出来的 BLE / USB 协议驱动打印头。

两个前端：

| | 命令行 (Python) | 浏览器版 |
|---|---|---|
| 能做什么 | PDF → 300dpi 位图 → 命令流 → BLE / USB 打印；まとめ申込 CSV 生成与校验 | 拖入 PDF → 自动识别面单 → **Web Bluetooth 直接打印** |
| 需要什么 | Python 3.10+ | Chrome / Edge（桌面版） |
| 数据去向 | 只在本机 | **PDF 不上传**，全程在浏览器内处理 |
| 适合 | 批量、自动化、和 CSV 对接 | 现场打一两张、给别人用 |

> ⚠️ **https://clickpost.l-l.li 是公开的 DEMO 站点**，只用来演示「上传 PDF → 切出 4 张面单」。
> 它没有后端、没有数据库、也没有日志；PDF 在浏览器里解析，**不会发到任何服务器**。
> 真要打印请在自己电脑上用 CLI 或本地跑浏览器版（Web Bluetooth 只连本机蓝牙）。

```
PDF (A4) ──按裁切线切网格──▶ A6 面单 ──300dpi──▶ 1-bit ──▶ 1f 2a/2b/2e 命令流 ──▶ BLE / USB
```

## 特点

- **自动找面单**：一张 A4 上有 1 张、或者まとめ申込 的 **2 × 2 共 4 张**，都能自动切；
  空白格子会被丢掉，按「从上到下、从左到右」编号。
- **贴着实线框裁**：A6 四周的留白和 `（切り取る）` 说明会被排掉，等比缩到 76 mm 宽，
  字能尽量大。
- **按矢量判断而不是按像素**：裁切线是 1.5 pt 的细线，在栅格里常被面单的白色填充盖住，
  但作为 PDF 路径线段一定拿得到。
- **命令流和 Python 实现逐字节一致**（测试用固定 fixture 对比 hex）。
- **不改版面**：面单本身是邮资凭证，只做无损裁切 + 等比缩放。

## 快速开始：命令行

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[ble]'          # 要用 USB 再加 '.[ble,usb]'

dzpost info   ~/Downloads/label.pdf              # 看看会怎么裁
dzpost render ~/Downloads/label.pdf -o out/p.png --bitmap
dzpost print  ~/Downloads/label.pdf --dry-run out/l.bin   # 不连打印机，只出命令流
dzpost print  ~/Downloads/label.pdf --labels all          # 4 张连打（BLE）
sudo .venv/bin/dzpost print ~/Downloads/label.pdf --transport usb
```

### まとめ申込 CSV

```bash
dzpost csv build batch/orders.json -o batch/clickpost-4.csv   # Shift-JIS / CRLF
dzpost csv validate batch/clickpost-4.csv                    # 校验位数、敬称、字宽、40 条上限
```

## 快速开始：浏览器版

线上 DEMO：**https://clickpost.l-l.li/**

```bash
cd web
npm install
npm run dev        # http://localhost:5173
```

拖入 PDF（或点「サンプルで試す」）→ 确认切出来的面单 → 「プリンタに接続」→「印刷する」。
必须用 **Chrome / Edge 桌面版**（Web Bluetooth 在 Safari / Firefox 上没有）。

打印完成后可以导出**打印日志**（CSV / JSON）：时间、文件、页、第几张、追跡番号、
尺寸、字节数、sha256、打印机状态 —— 方便对账。

> 追跡番号是从 ClickPost 下载的文件名里取的 12 位数字；4 面 PDF 四张共用同一个文件名，
> 所以日志里的「第几张」就是和まとめ申込 CSV 行序对应的顺序（同样是先上后下、先左后右）。

## 原理

1. **找裁切线** — 从 PDF 路径里挑出「跑到纸张边缘的长线段」，拿到 x / y 分割位置。
2. **组网格** — 相邻分割线之间成格，只保留符合 A6 比例（105 × 148 mm）的格子。
3. **丢掉空格** — 格子里的线段覆盖不到 40 % 就当地空白页处理。
4. **贴合外框** — 格子内「不贴边」的长线段的外接矩形就是面单外框，外扩 1 mm 作为裁剪框。
5. **渲染** — 2 倍渲染后 Lanczos 缩小，按 128 阈值二值化。
6. **命令流** — 编码成 `1b 40` / `1b 4a` / `1f 2a` / `1f 2b` / `1f 2e` / `0c` 发送。

打印机协议（USB HID 与 BLE 的差异、流控、浓度/速度）见 [docs/PROTOCOL.md](docs/PROTOCOL.md)。

## 已验证的环境

| | |
|---|---|
| 打印机 | DeTong DP305P（`3533:5C32`，300 dpi，960 点打印头，76 × 130 mm 标签） |
| 系统 | macOS（Apple Silicon）；Linux 加 udev 规则可用 USB |
| 纸张 | クリックポスト A6 面单（105 × 148 mm），等比缩到 76 mm 宽 |
| 实测 | 单张、4 张汇总结单都已真机打印（靠校验和 + 页计数器验证） |

## 开发

```bash
python -m unittest discover -s tests      # CLI：58 个用例
cd web && npm test                        # Web：15 个用例
npm run verify:pdf -- public/sample-4up.pdf
npm run build
```

CI（GitHub Actions）会跑两边的测试和构建。

## 注意

- **非官方**项目，与日本邮政、ClickPost、德佟印立方无关。
- 不改动面单内容，只从邮局生成的 PDF 里裁切。
- 运单 PDF 含姓名地址：除 `fixtures/local/` 和 `web/public/sample-*.pdf`（合成样例）外，
  不要把真实数据提交进仓库（`.gitignore` 已覆盖）。
- 浏览器版不发任何网络请求，只连本机 BLE。

## 许可

本项目整体为 **MIT**。但命令流编码器（`src/dzpost/protocol.py` / `web/src/protocol.ts`）
是 [dz-print](https://github.com/sb-child/dz-print)（**MPL-2.0**）的衍生作品，
这两个文件单独适用 **MPL-2.0**（文件级 copyleft）。

- `LICENSE` — MIT（上述两个文件之外）
- MPL-2.0 全文 — <https://mozilla.org/MPL/2.0/>
