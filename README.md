# dz-post-label

日本郵便 **クリックポスト** 的 PDF 运单 → DeTong 热敏标签机（DP305P，76 × 130 mm 不干胶）直打的自动化工具。

不经过官方 App、不依赖厂商 SDK：直接按逆向出来的蓝牙 / USB 协议把位图灌进打印头。

```
クリックポスト PDF (A4)  ──裁剪A6→标签框──▶  灰度位图  ──阈值──▶  1-bit  ──编码──▶  命令流
                                                                       ├─ BLE (ff02)，免 root
                                                                       └─ USB (HID int)，需 sudo
```

## 现状

| 能力 | 状态 |
|---|---|
| 自动定位 A4 页里的 A6 运单区域（识别裁切线 / 标签外框） | ✅ 已实现，样本实测 97.3 × 139.8 mm |
| 缩放到 76 × 130 mm @ 300 dpi，居中到 960 点打印头 | ✅ |
| 1-bit 阈值化 + 命令流编码（`1f 2a` / `1f 2b` / `1f 2e` / `0c`） | ✅ 含逐字节解码自校验 |
| BLE 打印（免 root，约 4.9 KB/s） | ✅ 传输层沿用已验真的实现 |
| USB 打印（快，macOS 需 sudo） | ✅ |
| 原生重绘（重新排版填满 130 mm） | ⛔ 未做，且**不建议**——见下文 |

> **为什么不"重绘"**：クリックポスト 的这张 A6 本身就是邮资凭证，官方明确
> "ラベルの複製または修正はできません"。所以本工具**只做无损裁剪 + 等比缩放**，
> 不改动任何版面元素。底部剩余空间可用来加自己的备注（后续可选功能），但不会
> 改动运单本体。

## 快速开始

```bash
cd ~/Library/CloudStorage/SynologyDrive-code/dz-post-label
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[ble]'          # macOS 蓝牙走 bleak；USB 再加 '.[usb]'

# 1) 只看它会怎么裁（不产生任何文件）
dzpost info ~/Downloads/628836654423.pdf

# 2) 生成预览图，肉眼确认版式
dzpost render ~/Downloads/628836654423.pdf -o out/preview.png --bitmap

# 3) 只生成命令流，不碰打印机（可离线校验）
dzpost print ~/Downloads/628836654423.pdf --dry-run out/label.bin
dzpost verify out/label.bin

# 4) 真机打印（BLE，免 root）
dzpost print ~/Downloads/628836654423.pdf --darkness 10 --speed 3

# 5) 走 USB（快，质量更好；macOS 必须 sudo）
sudo .venv/bin/dzpost print ~/Downloads/628836654423.pdf --transport usb
```

`dzpost scan` 可列出附近的 BLE 设备，确认打印机是否在线。

## 它是怎么裁的

1. **找裁切线**：OPRO 导出的 PDF 在 A4 上有一横一竖两条裁切线，标签区域就是
   `(0, 0) → (297, 418.5) pt` = 104.8 × 147.6 mm（A6 竖放）。
2. **找标签外框**：再用页面里长直线组成的外框，把 A6 边上的 `（切り取る）`
   标注、剪刀图标、边距都排除掉，得到 97.3 × 139.8 mm 的"净版面"。
   `--trim none` 可退回整块 A6。
3. **等比缩放到标签纸**：净版面宽 97.3 mm 缩到 76 mm（≈78%），高度 139.8 →
   109 mm，等比不变形。
4. **落到打印头**：76 mm 纸贴在 81.28 mm（960 点）打印头中央，左侧补 32 点
   （按整字节对齐，实测值）。
5. **二值化 + 编码**：300 dpi 直接渲染（2 倍超采样后 Lanczos 下采样，小字号更
   清楚），再按 128 阈值转 1-bit，编码成打印命令流。

缩放比例、留白和阈值都可以在命令行里调；遇到不认识的版式，用
`--crop x0,y0,x1,y1`（单位 mm，相对页面左上角）手工指定裁剪框即可。

## 常用参数

| 参数 | 说明 |
|---|---|
| `--width-mm` / `--height-mm` | 标签纸尺寸，默认 76 × 130 |
| `--dpi` / `--head-dots` | 打印头参数，默认 300 / 960（DP305P） |
| `--trim ink\|none` | `ink`（默认）裁到标签外框；`none` 保留整块 A6 |
| `--margin-mm` | `--trim ink` 时外框四周额外留白，默认 1.0 |
| `--crop x0,y0,x1,y1` | 手工裁剪框（mm），覆盖自动识别 |
| `--fit contain\|width\|height\|none` | 缩放策略，默认 `contain` |
| `--x-offset auto\|N` | 水平偏移，默认按 960 点居中 |
| `--v-align top\|center` | 垂直位置 |
| `--threshold` | 二值化阈值，默认 128；线上偏淡可降到 100 |
| `--darkness` / `--speed` | 1 基的人话参数，设备值 = N-1；推荐 10 / 3 |
| `--paper` | `adhesive`（默认）/ `ticket` / `card` / `transparent` |

## 画质与耗时

- 一个满版运单的命令流约 **90 KB**，BLE 有效吞吐约 4.9 KB/s → **约 18–20 秒一张**；
  USB 只要 1 秒左右。
- BLE 带宽是硬限制：打印头等数据，走纸走走停停，细竖线和大黑块会不匀。
  **要画质就用 USB**；BLE 时把速度调到最慢（`--speed 1`）会好一些。
- 浓度 10–11、速度 3（USB）是这台机器上实测最清晰的组合。

## 安全 / 隐私

运单 PDF 含真实姓名地址，**绝不入库**：`fixtures/local/` 已在 `.gitignore` 里，
放了真实样本也不会被 `git add`。仓库里只保留合成出来的测试用 PDF（测试时现场生成）。

## 测试

```bash
python -m unittest discover -s tests -v
```

35 个用例，覆盖：命令流编码/解码往返（逐个点比对）、重复行与前导空白压缩、
裁切线/外框识别、版式合成与偏移、CLI 全流程（`--dry-run` 不碰硬件）。

`dzpost verify` 用独立解码器把命令流还原成点阵统计，可以作为打印前的最后一道闸。

## 协议参考

见 [`docs/PROTOCOL.md`](docs/PROTOCOL.md)。数据来源是同一台 DP305P 的逆向结果：
USB 走 HID 中断接口（`1e` = Report ID），BLE 去掉 `1e` 走串口透传，命令体逐字节相同。

## 路线图

- [ ] 批量：一次吃多个 PDF / 目录，循环打印并报告每张状态
- [ ] 底部留白区域加可选页脚（订单号 / 备注），不改运单本体
- [ ] 条码区域按原生分辨率重绘（Code128），进一步保证扫描率
- [ ] Linux udev 规则与 udev 免 root 说明
- [ ] 打印后自动查询状态、失败重试
