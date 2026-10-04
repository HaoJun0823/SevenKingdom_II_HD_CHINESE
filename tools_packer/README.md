# 7K2 资源 解包 / 打包 工具（tools_packer）

Python 3 工具，针对《七王国2：弗里坦战争》(Seven Kingdoms II: The Fryhtan War) HD 版
`update\` 下的资源容器做**字节级精确**的解包与打包，并以原版资源做 SHA-256 往返验证。

## 支持的容器格式（依据 7k2-master 源码）

| 类型 | 识别特征 | 产出 |
|------|----------|------|
| `residx`  | 命名索引包 `struct ResIndex{ char name[9]; uint32 pointer; } #pragma pack(1)`（oresx.cpp/h），共 `(rec_count+1)` 个索引项，末项为哨兵 | 每条记录一个 `.bin` + `manifest.json` |
| `resource`| 无名索引包 `int16 rec_count` + `(rec_count+1)` 个 `uint32` 偏移（ores.cpp） | 每条记录一个 `.bin` + `manifest.json` |
| `blob`    | 其余（纯文本 `.res` / `.sct` 等） | 整体作为 `blob.bin` 原样保存 |

本批 `update\` 文件实测分类：
- `residx`（14 个）：`Resource\` 下的 INTROTXT/CPG_INTR/TUT_TEXT/TUT_INTR/Hotkey(.res)/STD.SET；
  `Campaign\` 下的 `*.stg` `*.evt` `*.plt` `*.DLG` `*.TXR`。
- `blob`（24 个）：`Resource\` 下的 `t_*.res` `help.res` `tips.res` `tut_list.res`；`Scenario\Premade\*.sct`。

## 用法

### 解包
```bat
python unpack.py <输入文件> [输出目录]
python unpack.py --dir <输入目录> <输出根目录>   :: 递归解包整棵目录树
:: 可选 --text 额外导出 UTF-8 文本预览（仅供阅读，重打包仍以 .bin 原字节为准）
```
解包产物为 `输出目录/manifest.json` + `输出目录/records/NNN_<name>.bin`。
`residx` 的 `manifest.json` 记录每条记录的原始 9 字节 `name_raw`（含哨兵项），
保证重打包时逐字节一致（包括零长度记录、填充字节、记录顺序）。

### 打包
```bat
python pack.py <解包目录> [输出文件]
python pack.py --dir <解包根目录> <输出根目录>   :: 批量重建
```
严格依据 `manifest.json` 重建，不做任何文本/编码转换，故与原版逐字节相同。

### 验证
```bat
python verify.py [--src <update根目录>] [--tmp <临时目录>]
```
遍历 `Resource/`、`Campaign/`、`Scenario/`，对每个文件做 解包→重打包→SHA-256 比对，
输出 PASS/FAIL 与类型分布。

## 关键保证
- 原版资源往返 SHA-256 **完全一致**（已验证 38/38 通过）。
- 编辑流程：解包得到 `.bin`（对文本资源即为 Big5/cp950 字节流），修改后重打包即可。
  重新编码中文请使用 `..\tools\` 下既有的 zh 管线（本工具只做格式中立的 I/O，不重编码）。
