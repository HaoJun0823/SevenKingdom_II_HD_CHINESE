# Seven Kingdoms II HD 简体中文汉化

> ⚠️ **使用前必读**
>
> 本补丁为个人非官方作品，**未获游戏官方授权**；安装会修改或注入游戏文件，
> 可能与该游戏的用户协议（EULA）冲突。请自行判断是否可用，风险自担，
> **安装前请备份存档与原始文件**。
>
> **禁止商业使用**；二次修改后分发，须公开源代码与改动记录，并保留原作者署名。
> 作者不对使用后果承担责任，也不拥有本游戏及其原始素材的版权。
> 完整条款见 [LICENSE](LICENSE)。


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

## 四、子模块（submodule）怎么用

这仓库挂了 **2 个子模块**，它们是**别处的独立仓库**，不是本仓库的文件。
git 对子模块只记一条「commit 指针」（叫 gitlink），**不存代码本身**。
所以子模块的改动要**在子模块里单独 commit 并 push**，父仓库只更新指针。

| 子模块 | 指向 | 内容 | 指针 |
|---|---|---|---|
| `7k2_src` | `github.com/7k2/7k2` | 游戏本身的自带源码（autotools 工程，926 文件） | `9663a21` |
| `SavenKingdom_II_HD_BUG_FIX` | `github.com/HaoJun0823/SavenKingdom_II_HD_BUG_FIX` | BugFix 补丁工程（`dllmain.cpp` 等 9 文件） | `827e9e3` |

> 注意它跟 `SavenKingdom_II_HD_CHINESE/`（主插件源码，**在主仓库里**）是
> **两套独立工程**，别混淆：`SavenKingdom_II_HD_BUG_FIX` 是子模块，`SavenKingdom_II_HD_CHINESE` 不是。

### 克隆时要带 `--recursive`

普通 `git clone` 下来，两个子模块目录是**空文件夹**（只有个 `.git` 占位），
因为父仓库里根本没它们的代码。补拉：

```bash
git clone --recursive <本仓库地址>        # 一步到位
git submodule update --init --recursive   # 已经 clone 过，补拉子模块
git submodule status                      # 检查是否就绪：行首没有 - 号就是 OK
```

### 改了子模块内容之后

父仓库只会显示「指针变了」，必须**两头都推**，否则别人 `pull` 会失败：

```bash
git -C 7k2_src push                        # 先推子模块自己的远程
git -C SavenKingdom_II_HD_BUG_FIX push
git push --recurse-submodules=on-demand    # 或者直接推父仓库，自动带推子模块
```

最省事的写法，推本仓库时自动把子模块一起推：

```bash
git config push.recurseSubmodules on-demand
```

---

## 五、改译文的标准流程

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

## 六、当前进度 / 已知问题

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

## 七、License

本仓库（插件源码、工具链、译文数据）采用 **HJNCSA-1.0 非商业源码可得许可**
（HaoJun0823 Non-Commercial Source-Available License 1.0，基座为 Apache 2.0）。
**它不是开源许可**——开源许可不得限制使用领域，而本许可禁止商业用途。

- 禁止商业使用（含任何以营利为目的的分发、售卖、打包或引流变现）
- 二次修改后再分发，须公开源代码与改动记录，并保留原作者署名
- 作者不对使用后果承担责任，亦不拥有本游戏及其原始素材的版权

根目录 [LICENSE](LICENSE) 是**项目级声明文件**（主许可、游戏著作权声明、
子模块归属、附加条款、免责声明都在里面）；
完整许可证全文按类型归档在 `LICENSES/`：

| 文件 | 内容 |
|---|---|
| `LICENSES/Apache-2.0.txt` | 基础许可 Apache License 2.0 官方全文 |
| `LICENSES/7k2.txt` | 子模块 `7k2_src` 游戏源码的 GPL v2 全文（Enlight / 7kfans） |
| `LICENSES/ASILoader.txt` | Ultimate ASI Loader（ThirteenAG）的 MIT 许可副本 |

游戏本体（版权与商标）：

- `7K2.exe`、`dsound.dll`（MILES 音频引擎）与所有游戏资源（`.idx` / `.set`
   / 音乐 / 视频 / 贴图 / 字体）**一个字节都不随本仓库分发**，
  著作权与商标归 Enlight Software Ltd.、7kfans、发行方各自所有
- 本仓库只给译文文本、译文数据和一个 `sk2_zh.asi`，使用者自己装到
  **合法取得**的游戏目录上；不得把补丁与游戏打包分发
- 详见 [LICENSE](LICENSE) 第二、三、四节

非官方补丁。如果觉得好玩，请支持正版。
