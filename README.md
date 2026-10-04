# Seven Kingdoms II HD 简体中文汉化

给 **GOG 版《七王国 2 HD》**（`7K2.exe`，32 位）做的简体中文补丁。

不改游戏逻辑，不替换 exe：把一个小插件（`sk2_zh.asi`）放进游戏的 `scripts\`，
把中文资源放进 `update\`，游戏自带的 modloader 就会自动加载。
卸载 = 删掉这两个目录。

- 加载方式：**不需要第三方 ASI Loader**。游戏自带的 `dsound.dll`（MILES 音频引擎）
  内置了 modloader，会扫描 `scripts\` / `plugins\` / `update\`，
  并且 `update\` 本身就是资源覆盖目录（`OverloadFromFolder`）。
- 文本渲染：插件挂钩引擎自己的文字排版链路，画简体中文字形，
  所以字号、换行、对齐都跟着原引擎走，不会错位。
- 数据层：`STD.SET` 等内嵌数据表（建筑 / 科技 / 兵种 / 神名 / 氏族名 / 怪物）直接改写字段。

> 想深挖引擎实现（为什么不能用 dinput8、Big5 字节为什么会被引擎当字形查表、
> hook 的 ABI 坑 ...），看 [docs/engine_notes.md](docs/engine_notes.md)（长文，逆向笔记）。

---

## 一、装好就能玩（三步）

1. **确认游戏目录结构**

   ```
   <游戏目录>\7K2.exe
   <游戏目录>\dsound.dll          ← 一定有，这是加载器的入口
   ```

2. **放插件**：把编译好的 `sk2_zh.asi` 复制到 `<游戏目录>\scripts\`（没有就建目录）

3. **放资源**（可选，如果想要中文界面文字）：把仓库里的
   [`update_res_staged\`](update_res_staged) 整个目录内容复制到 `<游戏目录>\update\`

启动游戏即可。运行日志在 `<游戏目录>\update\sk2_zh.log`。

**卸载**：删除 `<游戏目录>\scripts\` 和 `<游戏目录>\update\`。

> 只想先试插件、不换资源：只做第 2 步，游戏界面会是英文 + 中文字符渲染，
> 用来验证排版是否正常。

### 一键部署（Windows）

```bat
cd SavenKingdom_II_HD_CHINESE
build.cmd          :: 编译 sk2_zh.asi
deploy.cmd         :: 只装插件
deploy.cmd all     :: 插件 + 中文资源一起装
```

脚本里的游戏目录是硬编码的，改 `deploy.cmd` / `build.cmd` 顶部的 `set GAME=...` 即可。

---

## 二、编译插件

需要 **MSVC（Visual Studio）+ Windows SDK，x86 目标**。

```bat
:: 方式 A：命令行一键
cd SavenKingdom_II_HD_CHINESE
build.cmd

:: 方式 B：VS IDE 打开 SavenKingdom_II_HD_CHINESE.sln，编译 x86 Release
:: 产物名是 .asi（把 .dll 改名即可），由 hooks.cpp 导出的 DllMain 走 ASI 约定
```

或者用 Python 直接调 `cl.exe`（免 MSBuild）：

```bat
python tools\build.py
```

---

## 三、仓库里有什么

| 目录 | 作用 |
|---|---|
| `SavenKingdom_II_HD_CHINESE/` | 插件源码（C++，16 个 `cpp/h`）。`cjk.cpp` 中文渲染、`hooks.cpp` 挂钩、`diag.cpp` 诊断日志 |
| `scripts/sk2_zh.asi` | 编译好的插件（可直接丢进游戏 `scripts\`） |
| `tools/` | 汉化工具链：表解析（`db_table.py`）、字形查表（`fontlib.py`）、扫描未译（`scan_pending.py`）、批量修译（`fix_names.py` / `fix_unit.py`） |
| `tools_packer/` | `STD.SET` 这类 idx 容器的解包 / 打包 / 结构校验 |
| `unpack_data_chs/Resource/STD.SET.unpacked/` | **简体中文字段数据（唯一真源）**，改译文就改这里 |
| `update_res_staged/` | 打包好的中文资源，`deploy.cmd all` 直接从这里复制到游戏 `update\` |
| `update/` | 插件运行期的配置与日志落点（`render.ini`、`sk2_zh.log`） |
| `docs/engine_notes.md` | 逆向工程笔记（长） |
| `archives/` | 本地归档：编译中间物、探索截图、旧备份、一次性脚本。**不入库，删掉不影响使用** |

> `unpack_data_original/`（英文原版解包）和 `unpack_data_cht/`（繁体补丁解包）
> 是本地工作用的参考物，**没有进 git**，需要时自己解包或重新拿繁体补丁。

---

## 四、改译文的标准流程

改动必须**等长替换**（字段宽度固定，多一个字节就会把后面的记录顶歪），
所以每次改完都要做四项结构校验：文件长度 / 记录数 / 记录名 / 每条记录长度。

```bat
:: 1) 改 unpack_data_chs/Resource/STD.SET.unpacked/records/ 下的 .bin
::    （字段偏移和宽度见 manifest.json，用 tools/db_table.py 解析）

:: 2) 重新打包
cd tools_packer
python pack.py ..\unpack_data_chs\Resource\STD.SET.unpacked "STD.SET.new"
python verify.py STD.SET.new "..\unpack_data_original\Resource\STD.SET"

:: 3) 部署
copy STD.SET.new "<游戏目录>\update\Resource\STD.SET"
```

常用工具：

```bat
python tools\scan_pending.py        :: 盘点还有哪些没译 / 译坏了
python tools\fix_names.py           :: 修 RACENAME / TECH 里的半截翻译
python tools\fix_unit.py            :: UNIT 表兵种名、神名补译
python tools\check_struct.py        :: 结构校验
```

---

## 五、当前进度 / 已知问题

已汉化并完成结构校验：

- `STD.SET` 建筑名、科技描述、科技类别、氏族名、随机人名（诺尔斯语等）
- `UNIT` 表 74 条兵种名与神名（大天使 / 雷神 / 雅典娜 / 麒麟 / 天照 等）
- `MONSTER` / `RACE` / `GOD` 表
- 教程与战役文本（`Campaign\EAST.*`）

已知未做：

- `NAME1` / `NAME2` 里少量随机人名仍是英文（Robert、Lincoln 这类），
  只出现在指派英雄、记者等弹窗
- 游戏在**全屏独占 DirectDraw** 下与桌面合成器偶发冲突，可能卡输入；
  换成窗口模式通常正常（与插件无关，插件在卡死时 hook 计数为 0）

---

## 六、License

本仓库（插件源码、工具链、译文数据）采用 **GPL-3.0**，见 [LICENSE](LICENSE)。

第三方：

- `LICENSES/ASILoader.txt` —— Ultimate ASI Loader（ThirteenAG）的 MIT 许可副本
- 游戏本体 `7K2.exe` 与 `dsound.dll`（MILES 音频引擎）不属于本项目内容，
  装补丁时是从游戏目录原样引用，不做修改也不随本仓库分发

非官方补丁。如果觉得好玩，请支持正版。
