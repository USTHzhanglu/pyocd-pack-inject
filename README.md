# pyocd-pack-inject

把**本地** CMSIS-Pack（`.pack`）安装进 pyOCD 的全局 pack 缓存，让 pyOCD
无需 `--pack` 参数即可识别其中的设备型号。

针对官方 `pyocd pack install` 覆盖不到的场景：它只能从 Keil 公共 pack
索引下载安装，而厂商官网、自研、或打过补丁（例如修正 `RAMstart`/
`RAMsize` 布局）的本地 `.pack` 不在索引中，官方命令装不进去。

## 工作原理

pyOCD 的 *managed packs* 机制（`board.py` → `ManagedPacks.populate_target`）
在目标型号不在内置列表时，会扫描 `cmsis-pack-manager` 的缓存目录。
一个 pack 被 pyOCD 认定"已安装"需要同时满足：

1. `data_path/index.json` 中有该 pack 的设备记录 —— pyOCD 用 `cache.index`
   枚举已装 pack；
2. `data_path/<vendor>/<pack>/<version>.pack` 文件真实存在 ——
   `ManagedPacks.get_installed_packs` 用 `os.path.isfile` 判定。

`data_path` 即 `cmsis-pack-manager` 的用户数据目录：

| 平台 | 路径 |
|---|---|
| Windows | `%LOCALAPPDATA%\cmsis-pack-manager` |
| Linux   | `~/.local/share/cmsis-pack-manager` |
| macOS   | `~/Library/Application Support/cmsis-pack-manager` |

本工具对每个本地 `.pack` 手动完成注册（不依赖在线索引）：

1. 复制 `.pack` → `data_path/<vendor>/<pack>/<version>.pack`；
2. 在 `data_path/index.json` 中 merge 一条 `from_pack` 记录。

> 注: 最初尝试过 cmsis-pack-manager 的 `Cache.add_pack_from_path()`
> 官方接口, 但其 rust 解析器对部分厂商的 pack 会静默失败、不写索引。
> pyOCD 实际只用 index.json 枚举已装 pack 的文件名, 设备详情是它自己
> 用 `CmsisPack` 重新解析 `.pack` 得到的, 所以手动维护同样满足判定。

装完后 pyOCD 只需 `target_override=<型号>`（GUI 里直接选型号）即可使用，
无需再传 `--pack` 路径。

## 依赖

- Python ≥ 3.9
- `cmsis-pack-manager>=0.5.2,<1.0` —— **pyOCD 侧同样依赖它**：未安装时
  pyOCD 走空的 `ManagedPacksStub`，不会扫描任何全局目录。

## 安装

```bash
pip install -e .          # 从本仓库目录, 含 GUI 依赖: pip install -e ".[gui]"
# 或直接运行不安装:
python -m pyocd_pack_inject --help
```

## GUI

图形界面（安装 / 卸载 / 列表），复用 dap_download 的 pack manager 交互风格：

```bash
pip install "pyocd-pack-inject[gui]"   # GUI 需要 tksheet
ppi gui
```

窗口功能：
- **Add...**：选择本地 `.pack` 文件（可多选），注入全局缓存
- **Remove**：卸载选中的包（带确认）
- **双击某行**：打开该包支持的**芯片列表**（Device / Target / Flash），
  OK 或双击某行会把可用的 target 名（如 `_at32f425c8t7`）复制到剪贴板，
  可直接用于 `pyocd -t` / GUI
- **过滤框**：主窗口按 Vendor / Pack / Version；芯片窗口按
  Device / Target / Flash

## 用法

```bash
# 注册一个本地 pack（同厂商同系列旧版本会被替换）
ppi install HDSC.HC32F460.1.0.8.patched.pack
ppi install ArteryTek.AT32F425_DFP.2.1.5.pack GigaDevice.GD32F3x0_DFP.3.0.0.pack

# 查看全局已装的 pack
ppi list
ppi list --path          # 连带打印完整文件路径

# 卸载（REF 支持 Vendor.Pack 或 Vendor.Pack.Version）
ppi remove HDSC.HC32F460
ppi remove HDSC.HC32F460.1.0.8

# 打印全局数据目录
ppi path
```

## 验证是否被 pyOCD 识别

```bash
# 列表里出现目标型号即成功
pyocd list --targets | grep -i hc32f460

# 直接擦除/烧录（不传 --pack）
pyocd erase --chip -t hc32f460jeua
pyocd flash -t hc32f460jeua firmware.bin
```

## 关于 `pyocd pack find`

`pyocd pack find <device>` 是**在线索引搜索器**——它只在 Keil 公共索引的
设备 part number 里做 glob 匹配，与本地/已安装的包无关。查询已安装的
本地包请用 `pyocd pack show` 或本工具的 `ppi list`。

手动安装的包在 index.json 里是精简记录（只有 `from_pack`/`name`/
`vendor`），若 find 的 pattern 恰好命中该记录（例如 `at32f425` 命中
`ArteryTek.AT32F425_DFP.2.1.5`），会输出一行伪设备（Installed 列为
False），这属于预期行为，不影响 pyOCD 烧录时的自动发现。

## 项目结构

```
pyocd-pack-inject/
├── pyproject.toml
├── README.md
└── src/pyocd_pack_inject/
    ├── __init__.py
    ├── __main__.py      # python -m pyocd_pack_inject
    ├── cli.py           # ppi 命令入口
    └── manager.py       # PackManager: install/list/remove
```

## 备注

- 安装是**复制**语义：源 `.pack` 文件不会被改动；对打过补丁的包
  （如修正 flash 算法 RAM 布局的版本），直接安装补丁版即可。
- 卸载时会同时清理 `index.json` 中该 pack 的设备记录，避免 pyOCD
  枚举到"文件已删但索引残留"的包。
- 与 pyOCD 内置 target 的关系：pyOCD 优先用内置列表；仅当型号不在
  内置时才查 managed packs，两者不冲突。
