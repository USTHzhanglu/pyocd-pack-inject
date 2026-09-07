# pyocd-pack-inject

把本地 CMSIS-Pack（`.pack`）注入 pyOCD 的全局缓存，装完后 pyOCD
无需 `--pack` 参数即可识别其中的芯片型号。

覆盖官方 `pyocd pack install` 管不到的场景：官方只能从 Keil 公共索引
下载，而厂商官网、自研或打过补丁（如修正 flash 算法 `RAMstart`/`RAMsize`
布局）的本地 `.pack` 不在索引里。

## 安装

```bash
pip install -e .                # 源码方式
pip install -e ".[gui]"         # 含 GUI 依赖(tksheet/windnd)
pip install -r packaging/requirements-build.txt   # 打包 exe 用
```

也可直接运行不安装：`python -m pyocd_pack_inject --help`

## GUI

```bash
ppi gui        # 或 python -m pyocd_pack_inject gui
```

- **Add... / 拖入 .pack**：注入全局缓存（自动刷新）
- **双击某行**：查看该包支持的芯片（Device / Target / Flash 三列，
  可过滤）；OK 或双击芯片行把可用的 target 名复制到剪贴板，
  如 `_at32f425c8t7`（可直接用于 `pyocd -t`）
- **Remove**：卸载选中的包（带确认）
- 过滤框：主窗口按 Vendor/Pack/Version，芯片窗口按 Device/Target/Flash
- Help / About：打开项目文档、查看版本与缓存路径

## CLI

```bash
# 注册本地 pack（同厂商旧版本自动替换）
ppi install HDSC.HC32F460.1.0.8.patched.pack
ppi install AT32F425_DFP.pack GD32F3x0_DFP.pack

# 查看 / 卸载 / 数据目录
ppi list
ppi list --path
ppi remove HDSC.HC32F460
ppi remove HDSC.HC32F460.1.0.8
ppi path
```

## 工作原理

pyOCD 判定一个 pack "已安装"需同时满足：

1. `index.json` 里有该 pack 的记录（用于枚举）；
2. `data_path/<vendor>/<pack>/<version>.pack` 文件存在。

`data_path` 是 `cmsis-pack-manager` 的用户数据目录：

| 平台 | 路径 |
|---|---|
| Windows | `%LOCALAPPDATA%\cmsis-pack-manager` |
| Linux | `~/.local/share/cmsis-pack-manager` |
| macOS | `~/Library/Application Support/cmsis-pack-manager` |

本工具对每个 `.pack` 手动完成两步注册（不依赖在线索引）：
复制文件到上述目录 + 在 `index.json` merge 一条 `from_pack` 记录。
安装是复制语义，源文件不会被改动；卸载会同时清理文件和索引记录。

## 验证

```bash
# 列表里出现目标型号即成功
pyocd list --targets | grep -i at32f425

# 直接擦除/烧录（不传 --pack）
pyocd erase --chip -t _at32f425c8t7
```

## 打包 exe

PyInstaller 打包为 windowed GUI 单文件 exe（无外部配置/资源）：

```bash
python -m PyInstaller packaging/pyocd_pack_inject.spec --noconfirm
# 产物: dist/pyocd-pack-inject.exe (约 12MB 单文件)
```

spec 从 `version.py` 读取版本并写入 exe 文件属性；已处理
cmsis-pack-manager 的 rust 扩展收集，并排除无用的 ssl/网络等标准库
模块。**不打包 pyOCD**——工具只维护 cmsis-pack-manager 缓存文件，
pyOCD 由使用方自行安装。

## 项目结构

```
pyocd-pack-inject/
├── pyproject.toml
├── packaging/
│   ├── pyocd_pack_inject.spec   # PyInstaller 配置
│   ├── gui_main.py              # 打包入口
│   └── requirements-build.txt
└── src/pyocd_pack_inject/
    ├── __init__.py
    ├── __main__.py
    ├── version.py       # 应用身份/版本信息
    ├── cli.py           # ppi 命令入口
    ├── manager.py       # 注入/卸载/列表
    ├── gui.py           # 主窗口
    └── devices_dialog.py# 芯片列表窗口
```
