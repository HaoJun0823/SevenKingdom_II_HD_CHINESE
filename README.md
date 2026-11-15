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

给 **《七王国 2 HD》**（`7K2.exe`，32 位）做的简体中文补丁，**STEAM 2.10F 与
GOG 2.10E 通用**：两套 exe 都已适配，同一份包解压即用。

不改游戏逻辑，不替换 exe：把汉化插件（`sk2_zh.asi`）放进 `scripts\`，中文资源
放进 `update\`，再由包内的 `dsound.dll`（ASI 加载器）把插件挂上去。

- 加载方式：**不需要另装 ASI Loader**。包内 `dsound.dll` 就是加载器，
  它会扫描 `scripts\` / `plugins\`，而 `update\` 本身就是游戏原生的资源覆盖目录。
- 文本渲染：插件挂钩引擎自己的文字排版链路，画中文字形，
  所以字号、换行、对齐都跟着原引擎走，不会错位。
- 数据层：`STD.SET` 等内嵌数据表（建筑 / 科技 / 兵种 / 神名 / 氏族名 / 怪物）直接改写字段。
- 简繁切换：改 `update\render.ini` 里的一行 `lang=`，重启游戏即可（详见第二节）。

> 想深挖引擎实现（为什么不能用 dinput8、Big5 字节为什么会被引擎当字形查表、
> hook 的 ABI 坑 ...），看 [docs/engine_notes.md](docs/engine_notes.md)（长文，逆向笔记）。

---

## 一、安装（Steam / GOG 通用，解压即装）

### 1. 先备份

| 要备份的东西 | 怎么备份 |
|---|---|
| 游戏根目录的 `dsound.dll`（如果有） | 改名成 `dsound.dll.bak` |
| `scripts\`、`update\` 两个目录（如果已存在） | 整目录复制到别处 |

### 2. 解压覆盖

把发布包 `7K2-CHS-Common-<日期>.zip` 里的**全部内容**解到游戏根目录，
让它和 `7K2.exe` 处于同一层。解完应该是：

```
<游戏目录>\7K2.exe
<游戏目录>\dsound.dll              ← 包内提供（ASI 加载器）
<游戏目录>\scripts\sk2_zh.asi      ← 包内提供（插件本体）
<游戏目录>\update\render.ini       ← 包内提供（简繁切换 / 配色 / 诊断开关）
<游戏目录>\update\Resource\STD.SET ← 包内提供（中文数据表）
<游戏目录>\update\Campaign\east.evt
```

### 3. 启动，等满 30 秒

加载器是**延迟加载**的：插件大约在游戏启动 **25~30 秒**后才挂上。
别在这之前就断定「没生效」。

### 4. 确认装好了

看 `<游戏目录>\update\sk2_zh.log`，出现这两行就是成功：

```
[i] render.ini: lang=... -> 简体
[i] 字形语言: 简体（13/16/24px 三档 + 补充表双池已就绪）
```

### 5. 两个平台各自要注意的

| 平台 | 注意事项 |
|---|---|
| **STEAM 2.10F** | Steam 的「验证游戏文件完整性」会把 `dsound.dll` 换回官方版本，中文随即消失。校验过后把包里的 `dsound.dll` 覆盖回去即可；也可以把该文件设为只读。 |
| **GOG 2.10E** | GOG Galaxy 的「修复 / 验证」同样会覆盖 `dsound.dll`，处理方式相同。GOG 版无 DRM，装好即玩。 |

### 6. 卸载 / 回滚

- **回滚插件**：把安装前备份的 `scripts\sk2_zh.asi` 放回去（或删掉 `scripts\`）。
- **彻底卸载**：删 `scripts\` 和 `update\`，再把 `dsound.dll.bak` 改回 `dsound.dll`
  （当初没有这个文件就删掉 `dsound.dll`）。存档在 `Profile\`，不受影响。

### 一键部署（本机开发用，Windows）

```bat
cd SavenKingdom_II_HD_CHINESE
python tools\build.py                 :: 编译 build\sk2_zh.asi
python tools\stage_resources.py       :: 由解包源重装配 update_res_staged\
python tools\pack_release.py          :: 打成 release\7K2-CHS-Common-<日期>.zip
```

---

## 二、简繁切换

改 `update\render.ini` 里的一行，存盘，**重启游戏**：

```ini
lang=simp    ; 简体（发布包默认）
lang=trad    ; 繁体
```

- 也接受 `lang=chs` / `lang=cht` / `lang=hans` / `lang=hant` /
  `lang=simplified` / `lang=traditional` / `lang=1` / `lang=0`。
- 旧写法 `chslang=1`（简）/ `chslang=0`（繁）仍然兼容；两者同时存在时 `lang=` 优先。
- 两个都不写 → **默认繁体**（历史行为，发布包已显式写成 `lang=simp`）。
- 切换**只换字形池，不动任何资源文件**，所以不用重装、不用换包。
- 13 / 16 / 24 三档字号 + 补充表各有一整套简、繁字形池，1121 个简繁异形字全部覆盖，
  不会再出现旧版那种「一部分字是繁体、一部分是简体」的混合画面。
- 注意简繁切换切的是**显示字形**：译文用词是简体中文，繁体模式只是按繁体字形显示。

改完不想等出问题的话，`update\sk2_zh.log` 里会多一行 `[i] render.ini: lang=... -> 简体/繁体`。

---

## 三、编译插件

需要 **MSVC（VS 2017 及以上）+ Windows SDK，x86 目标**。三种方式等价：

```bat
:: 方式 A：Python 直调 cl（推荐，CI 走的就是这条）
python tools\build.py

:: 方式 B：VS IDE 打开 SavenKingdom_II_HD_CHINESE.sln，编译 x86 Release
:: 方式 C：build.cmd（固定 vcvars32 路径，本机环境变了就得改）
```

`tools/build.py` 的工具链解析顺序：

1. `SK2_CL` —— 显式指定 cl.exe 路径；
2. `MSVC_WINE_PREFIX` —— Linux/CI 上 msvc-wine 的 `<prefix>/bin/x86/cl` 包装脚本
   （INCLUDE/LIB 由包装脚本设置，脚本不再插手）；
3. `SK2_MSVC` / `SK2_SDK` / `SK2_SDKV` —— 本机指定具体版本；
4. 都没有就自动探测：`vswhere` 找到 VS 安装 → 取版本号最大的那套工具集。

产物固定是 `build\sk2_zh.asi`（PE32 x86 DLL，`/MT` 静态 CRT，玩家机器不需要 VC 运行库）。

---

## 四、CI 与发布（推上去就出包）

`.github/workflows/build-release.yml`：

| 触发 | 行为 |
|---|---|
| push 到 `master` / `main` | 构建 → 校验 → 上传 Artifact → **同一个 run 内**按「日期-时间」打 tag 并发 Release |
| Pull Request | 只构建 + 校验（门禁，不发布） |
| 手动 `workflow_dispatch` | 同上，只出 Artifact |

构建跑在 `ubuntu-latest` + [msvc-wine](https://github.com/mstorsjo/msvc-wine) 上：
用与 VS 安装器同一份官方 manifest 从微软 CDN 拉 MSVC 与 Windows SDK，
再用 wine 跑真 `cl.exe` 编出 32 位 `.asi`。选它而不是 windows runner，
是因为 windows 镜像不带老工具集、CI 里加装老工具集反复翻车（参考仓库实测）。

流水线三道闸，任何一道不过都不会产出半成品包：

1. **资源树闸** —— `tools/stage_resources.py --check`：`update_res_staged\` 必须与
   `unpack_data_chs\` 现场重打包的结果逐字节一致。改了解包源忘了重装配，CI 直接拦下。
2. **打包闸** —— `tools/pack_release.py`：`tools/release_manifest.txt` 里的文件必须齐全，
   zip 内路径集合必须与清单**完全相同**（多一个少一个都失败）。
3. **产物体检** —— `.asi` 必须是 PE32 x86 DLL、子系统 WINDOWS、入口点非 0、
   含插件标记串、体积在 1.8~4.2MB 区间。防止链成 x64、链成控制台程序、
   或字形池没生成就发版。

想本地复现 CI 的产物：

```bash
python tools/build.py
python tools/stage_resources.py
python tools/pack_release.py --stamp 2026-11-15
python tools/pack_release.py --verify release/7K2-CHS-Common-2026-11-15.zip
```

---

## 五、仓库里有什么

| 目录 | 作用 |
|---|---|
| `SavenKingdom_II_HD_CHINESE/` | 插件源码（C++）。`cjk.cpp` 中文渲染、`hooks.cpp` 挂钩、`diag.cpp` 诊断日志 |
| `scripts/sk2_zh.asi` | **不入库**（`.gitignore`），编译产物在 `build/` |
| `tools/` | 汉化工具链 + 构建/装配/打包脚本（`build.py` / `stage_resources.py` / `pack_release.py`） |
| `tools_packer/` | `STD.SET` 这类 idx 容器的解包 / 打包 / 结构校验 |
| `unpack_data_chs/` | **译文数据唯一真源**，改译文就改这里 |
| `update_res_staged/` | 资源装配结果（由 `stage_resources.py` 生成），发布包的 `update\` 就是它 |
| `packaging/` | 与译文无关的发布资产：`dsound.dll`、`update\render.ini`、`*.bak`、玩家说明 txt |
| `tools/release_manifest.txt` | 发布包内容清单（唯一真源，CI 拿它对照） |
| `update/` | 插件运行期的配置与日志落点（`render.ini`、`sk2_zh.log`） |
| `docs/engine_notes.md` | 逆向工程笔记（长） |
| `archives/` | 本地归档：编译中间物、探索截图、旧备份、一次性脚本。**不入库，删掉不影响使用** |

> `unpack_data_original/`（英文原版解包）和 `unpack_data_cht/`（繁体补丁解包）
> 是本地工作用的参考物，**没有进 git**，需要时自己解包或重新拿繁体补丁。

---

## 六、子模块（submodule）怎么用

这仓库挂了 **2 个子模块**，它们是**别处的独立仓库**，不是本仓库的文件。
git 对子模块只记一条「commit 指针」（叫 gitlink），**不存代码本身**。
所以子模块的改动要**在子模块里单独 commit 并 push**，父仓库只更新指针。

| 子模块 | 指向 | 内容 | 指针 |
|---|---|---|---|
| `7k2_src` | `github.com/7k2/7k2` | 游戏本身的自带源码（autotools 工程，926 文件） | 见 `git submodule status` |
| `SavenKingdom_II_HD_BUG_FIX` | `github.com/HaoJun0823/SavenKingdom_II_HD_BUG_FIX` | BugFix 补丁工程（`dllmain.cpp` 等 9 文件） | 见 `git submodule status` |

> 注意它跟 `SavenKingdom_II_HD_CHINESE/`（主插件源码，**在主仓库里**）是
> **两套独立工程**，别混淆：`SavenKingdom_II_HD_BUG_FIX` 是子模块，`SavenKingdom_II_HD_CHINESE` 不是。
>
> **CI 不拉子模块**（`submodules: false`）：编译插件、装配资源、打包都只依赖主仓库内容，
> 拉子模块纯属浪费 runner 时间。

### 克隆时要带 `--recursive`

```bash
git clone --recursive <本仓库地址>        # 一步到位
git submodule update --init --recursive   # 已经 clone 过，补拉子模块
git submodule status                      # 检查是否就绪：行首没有 - 号就是 OK
```

### 改了子模块内容之后

父仓库只会显示「指针变了」，必须**两头都推**：

```bash
git -C 7k2_src push
git -C SavenKingdom_II_HD_BUG_FIX push
git push --recurse-submodules=on-demand    # 或者直接推父仓库，自动带推子模块
```

最省事：`git config push.recurseSubmodules on-demand`

---

## 七、改译文的标准流程

改动必须**等长替换**（字段宽度固定，多一个字节就会把后面的记录顶歪），
所以每次改完都要做四项结构校验：文件长度 / 记录数 / 记录名 / 每条记录长度。

```bat
:: 1) 改 unpack_data_chs/Resource/STD.SET.unpacked/records/ 下的 .bin
::    （字段偏移和宽度见 manifest.json，用 tools/db_table.py 解析）

:: 2) 重新装配资源树（这一步会按 manifest 重新打包所有容器）
python tools\stage_resources.py

:: 3) 校验结构（拿装配出来的容器和英文原版对比）
cd tools_packer
python verify.py ..\update_res_staged\Resource\STD.SET "..\unpack_data_original\Resource\STD.SET"

:: 4) 打包 / 部署
python tools\pack_release.py            :: 出 zip
:: 或直接把 update_res_staged\ 覆盖到 <游戏目录>\update\
```

`EAST.EVT` / `EAST.PLT` 的**索引顺序**要按 `tools/residx_order.json` 对齐原版
（记录内容不变，只是排列顺序；引擎按名查找，不影响取数，但会影响逐记录 diff）。
`stage_resources.py` 会自动套用，新增容器需要对齐时把顺序补进那个 json。

常用工具：

```bat
python tools\scan_pending.py        :: 盘点还有哪些没译 / 译坏了
python tools\fix_names.py           :: 修 RACENAME / TECH 里的半截翻译
python tools\fix_unit.py            :: UNIT 表兵种名、神名补译
python tools\check_struct.py        :: 结构校验
python tools\gen_dual_pools.py      :: 重新生成简繁双字形池（改译文加新字之后跑）
```

---

## 八、当前进度 / 已知问题

已汉化并完成结构校验：

- `STD.SET` 建筑名、科技描述、科技类别、氏族名、随机人名（诺尔斯语等）
- `UNIT` 表 74 条兵种名与神名（大天使 / 雷神 / 雅典娜 / 麒麟 / 天照 等）
- `MONSTER` / `RACE` / `GOD` 表
- 教程与战役文本（`Campaign\EAST.*`）
- 简体 / 繁体双字形池（`lang=` 一键切换，1121 个简繁异形字全覆盖）

已知未做 / 已知问题：

- `NAME1` / `NAME2` 里少量随机人名仍是英文（Robert、Lincoln 这类），
  只出现在指派英雄、记者等弹窗
- 游戏在**全屏独占 DirectDraw** 下与桌面合成器偶发冲突，可能卡输入；
  换成窗口模式通常正常（与插件无关，插件在卡死时 hook 计数为 0）
- 「游戏持续时间：分钟」不显示时间、部分英文人名被吞末字 —— 游戏自身问题，英文原版同样

---

## 九、License

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
| `LICENSES/ASILoader.txt` | ASI Loader（ThirteenAG）的 MIT 许可副本 |

游戏本体（版权与商标）：

- `7K2.exe` 与所有游戏资源（`.idx` / `.set` / 音乐 / 视频 / 贴图 / 字体）
  **一个字节都不随本仓库分发**，著作权与商标归 Enlight Software Ltd.、
  7kfans、发行方各自所有
- 本仓库只给译文文本、译文数据、一个 `sk2_zh.asi`，以及一个 ASI 加载器
  `dsound.dll`（游戏目录本来就有同名文件，包内附上是为了被平台校验覆盖后能就地修复；
  其许可声明见 `LICENSES/ASILoader.txt`）；使用者自己装到**合法取得**的游戏目录上，
  不得把补丁与游戏打包分发
- 详见 [LICENSE](LICENSE) 第六节

非官方补丁。如果觉得好玩，请支持正版。
