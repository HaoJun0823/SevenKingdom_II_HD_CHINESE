# 7K2 HD 原版资产解包（unpack_data_original）

本目录是《七王国2：弗里坦战争》HD 版**原版（未汉化）资产**的字节级解包结果，
作为汉化编辑与重建的**基线**。

| 项 | 值 |
|---|---|
| 来源 | `I:\LocalGames\Seven Kingdoms II HD` 下的 `Resource` / `Campaign` / `Scenario` / `Tutorial` |
| 工具 | `..\tools_packer`（`unpack.py` / `pack.py` / `packlib.py` / `verify.py`） |
| 规模 | 223 个源文件 → 223 个 `.unpacked` 目录、1661 条记录、94 MB |

---

## 一、目录结构

```
unpack_data_original/
├─ Resource/     资源容器与数据文件（138 个源文件 → 22 容器 + 116 非容器）
├─ Campaign/     战役（39 → 8 容器 + 31 非容器）
├─ Scenario/     场景（29 → 全部非容器）
└─ Tutorial/     教程（17 → 全部非容器）
```

每个源文件对应**一个同名 + `.unpacked` 后缀的目录**，规则只有两条：

```
<原名>.unpacked/          ← 容器类（可展开成多条记录）
├─ manifest.json          重建的唯一依据
└─ records/
   ├─ 000_HEADER.bin
   ├─ 001_TECHCLAS.bin
   └─ ...
```

```
<原名>.unpacked/          ← 非容器类（整体保存，不展开）
├─ manifest.json
└─ blob.bin
```

> `records/` 下的文件名 = `序号_记录名`，记录名直接取自容器内的 9 字节 name 字段，
> 所以像 `STD.SET.unpacked/records/001_TECHCLAS.bin`、`002_GOD.bin`、`003_SPRITE.bin`
> 这样一眼能看出是哪张表 —— 这是查找文本时最有用的入口。

## 二、三种容器类型

依据 `7k2-master` 源码（`oresx.cpp` / `ores.cpp`）：

| type | 结构 | 本批命中 | 主要用途 |
|---|---|---|---|
| `residx` | `int16 cnt` + `(cnt+1)`×`{char name[9]; uint32 ptr}` | **30 个** | `STD.SET`、`CPG_INTR.RES`、`*.stg`/`*.evt`/`*.plt`/`*.DLG`/`*.TXR` |
| `resource` | `int16 cnt` + `(cnt+1)`×`uint32` | 0 | （本批未命中，工具仍支持） |
| `blob` | 其余 | **193 个** | `t_*.res`、`help.res`、`tips.res`、`*.sct`、`*.tut`、`*.wav`、图形 `.RES` |

## 三、统计

| 目录 | 容器 | 非容器 | 记录数 |
|---|---:|---:|---:|
| Campaign | 8 | 31 | 300 |
| Resource | 22 | 116 | 1361 |
| Scenario | 0 | 29 | 0 |
| Tutorial | 0 | 17 | 0 |
| **合计** | **30** | **193** | **1661** |

## 四、重建（构建时使用）

```bat
cd ..\tools_packer
python pack.py --dir ..\unpack_data_original <输出根目录>
```

输出根目录下会得到与游戏目录**同构**的文件树（自动去掉 `.unpacked` 后缀），
可直接用于投放 / 打包 / 覆盖。

单文件重建：

```bat
python pack.py <某个 .unpacked 目录> [输出文件]
```

## 五、已验证（两重）

1. **工具自检**：`python verify.py --src "I:\LocalGames\Seven Kingdoms II HD"`
   → 原版 206 个文件（30 容器 + 176 非容器）**全部 PASS，失败 0**。
2. **本目录实测**：把本目录 223 个 `.unpacked` 全部重建后与原版做 SHA-256 比对
   → **223 个文件全部逐字节一致，不一致 0 个**。

即：**解包 → 重建 是无损的**，构建流程可以放心以本目录为输入。

## 六、修改流程（汉化用）

1. 编辑 `records/` 下对应记录的 `.bin`（文本资源对容器而言即 Big5/cp950 字节流）；
2. 重编码中文请用 `..\tools` 下既有 zh 管线 —— **本套工具只做格式中立 I/O，不重编码**；
3. `pack.py` 重建 → 部署到游戏的 `update\`。

**注意**：不要手工修改 `manifest.json` 中的 `name_raw`、记录顺序、`file` 字段 ——
它们决定重建结果的字节级一致性。

## 七、几点说明

- **`blob` 类的 `blob.bin` 就是该文件的原始副本**（如 `*.wav`、图形 `.RES`）。
  工具为保证「往返逐字节一致」统一采用此约定；这类文件本身没有容器结构，
  内容与游戏目录中的同名文件完全相同。
- **`Scenario` / `Tutorial` 没有容器**：它们的 `.sct` / `.tut` 本身就是
  可直接阅读的纯文本（cp950），不需要解包。
- 如需**汉化版**的对照解包，把同一命令指向 `I:\LocalGames\Seven Kingdoms II HD\update`
  即可（该目录为 14 容器 + 26 非容器）。
