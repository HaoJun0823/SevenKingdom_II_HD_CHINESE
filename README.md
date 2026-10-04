# Seven Kingdoms II HD 简体中文 — 工程说明

> 目标游戏：GOG 版 `7K2.exe`（x86，**运行时基址 0x00AB0000，ASLR 开启**）
> 注入方式：**游戏自带 MILES modloader**（dsound.dll）+ update 资源覆盖
> 逆向依据：IDA Pro (Hex-Rays)，IDB 见 `docs/` 下的核查报告

---

## 零、加载链：为什么不用 dinput8.dll

最初以为需要 `dinput8.dll`（通用 ASI Loader）。**实测对本游戏无效**，原因：

`7K2.exe` 的导入表是：

```
DDRAW.dll   DINPUT.dll   DSOUND.dll   WINMM.dll
KERNEL32    USER32       GDI32        SHELL32     ole32
```

它导入的是 **`DINPUT.dll`（非 DINPUT8.dll）**。dinput8 代理只对
「导入 dinput8.dll」的游戏有效 —— 名字不匹配，系统根本不去加载它，所以毫无作用。

**而游戏自带的 `dsound.dll` 本身就是最好的加载器。** 实测该文件 5.4 MB，
是 MILES 音频引擎（内含 `Copyright 1983,97 Borland`），其 modloader 模块导出了完整的
ASI 加载能力：

```
modloader\modloader.asi     <- MILESCENT 内置加载器
loadextraplugins
loadfromscriptsonly
loadrecursively
scripts                     <- 扫描目录 1
plugins                     <- 扫描目录 2
update                      <- 扫描目录 3（同时是资源 OverloadFromFolder）
overloadfromfolder          <- 目录覆盖原文件
Global\UltimateASILoader-FolderSelectD
```

**结论：不需要任何第三方 loader。** `.asi` 放 `scripts\`，资源放 `update\`，
两个需求一个 modloader 全满足。

| 方案 | 结果 |
|---|---|
| `dinput8.dll`（原先方案） | 无效，EXE 不导入 dinput8 |
| `dsound.dll` 内置 modloader（游戏自带） | **当前方案，零外部依赖** |

---

## 零.五、资源投放时机：为什么 Stage 3 前不能投中文资源

**实测教训**：Stage 1 只定位不挂钩时投了中文资源，结果满屏乱码。

原因在字节层面。`update/Resource/t_basic.res` 里 `[BOX1]確定` 的字节是：

```
5B 42 4F 58 31 5D  BD 54  A9 77  0D 0A
[  B  O  X  1  ]   確     定     \r\n
```

引擎逐字节处理（IDA `sub_4C0AE0`）：

| 字节 | 引擎的解释 |
|---|---|
| `BD` | 不是国家色码(0x80-0x8F)，当普通字符 → 查 FontInfo 表 |
| `54` | 继续当下一个字符 → 查 FontInfo 表 |

引擎是**单字节字体**，会把「確」「定」当成两个独立 glyph 去 ASCII 字体里找，
自然找不到 → 显示乱码或空白。

**结论**：中文资源和 CJK 渲染器必须**配套投放**。
渲染器没就绪时投资源 = 满屏乱码。

因此 `deploy.cmd` 分两档：

| 命令 | 行为 |
|---|---|
| `deploy.cmd` | 只投插件，**并清理**游戏目录里已有的中文资源 → 显示英文原版 |
| `deploy.cmd all` | 插件 + 中文资源一起投（**仅当 Stage 3 已完成**） |

资源暂存目录：`update_res_staged/`（待 Stage 3 通过后再投放）。

---

## 一、为什么不用 ddraw 代理

原汉化方案用 `ddraw.dll` 代理 + `cnc-ddraw` 窗口化，有三个问题：

1. **依赖外部 DLL**（cnc-ddraw.dll + ddraw.ini），缺失就黑屏
2. **必须等 `DirectDrawCreate` 时机**打补丁（为规避 Steam DRM 自校验）——但本项目是 GOG 版，**根本没有 DRM**
3. 代理 `DirectDrawCreate` 会**抢占游戏主渲染路径**，任何失误都影响画面

本方案的优势：

| 维度 | ddraw 代理 | **MILES modloader** |
|---|---|---|
| 外部依赖 | ddraw.dll + cnc-ddraw.dll + ddraw.ini | **无**（用游戏自带的） |
| 加载时机 | 须等 DirectDrawCreate | 进程启动即加载，可从容定位 |
| DRM 顾虑 | 需延迟打补丁规避自校验 | GOG 版无此问题 |
| 失败影响面 | 影响整个渲染链 | 只影响我们的 hook |
| 资源覆盖 | 需手动 xcopy 覆盖原文件 | **update\ 目录，不动原文件** |
| 卸载 | 需还原多个文件 | 删 2 个目录 |

---

## 二、当前进度

```
[OK] Stage 1  地址自定位      —— 4 个签名已在真实 EXE 上验证唯一命中
[OK] 编译链                   —— MSVC 14.51 x86，产出 sk2_zh.asi
[OK] 资源迁移                 —— 18 Resource + 3 Campaign + 9 Scenario
[--] Stage 2  text_width 挂钩 —— 代码已就绪，待实机验证
[--] Stage 3  FontInfo 注入   —— 待实现
```

### 分阶段策略

每阶段独立验证，出问题立刻能定位：

| 阶段 | 做什么 | 验证方式 |
|---|---|---|
| **1** | 只定位 + 打印地址与字节，**不打任何补丁** | 日志里 4 个 `[O]` |
| **2** | 挂钩 `text_width`，实现双字节宽度 | 日志出现「已挂钩」；游戏不崩 |
| **3** | 注入等效 FontInfo，真正画出汉字 | 主菜单显示中文 |

切换方式（优先级从高到低）：
- 环境变量 `SK2_STAGE`（对 `start` 启动的子进程不可靠）
- 文件：**`scripts\stage.txt`** ← 推荐（`play.cmd 2` 写这里）
- 兼容旧位置 `update\stage.txt`

> ⚠️ **阶段标记绝不能放在 `update\` 里**：一旦把 `update\` 改名去临时停用资源，
> `stage.txt` 会被一起藏起来，插件随即退回 stage 1（一个补丁都不装），
> 那次运行变成「伪原版」。详见附录「RLE 精灵崩溃取证」。
>
> 缺省值现在是 **3（完整汉化）**：加载了插件却什么都不做是最强的误导源。

---

## 三、目录结构

```
SavenKingdom_II_HD_CHINESE/
|-- SavenKingdom_II_HD_CHINESE.sln
|-- SavenKingdom_II_HD_CHINESE/          源码
|   |-- core.h / core.cpp                签名搜索、跳板、日志
|   |-- fontwidth.h                      双字节判定与宽度语义
|   |-- hooks.h / hooks.cpp              各阶段挂钩实现
|   |-- fontdata_stub.cpp                字库查询（Stage 3 替换为真字库）
|   |-- dllmain.cpp                      入口与阶段调度
|   |-- build.cmd                        一键编译
|   `-- deploy.cmd                       一键部署
|-- scripts/                             插件投放（modloader 扫描）
|   `-- sk2_zh.asi
`-- update/                              资源覆盖 + 日志输出
    |-- Resource/   18 个中文资源
    |-- Campaign/    3 个（东方战役剧情）
    |-- Scenario/Premade/  9 个剧本简报
    `-- sk2_zh.log                        运行日志
```

---

## 四、使用方法

### 编译
```cmd
cd SavenKingdom_II_HD_CHINESE
build.cmd              :: 或 build.cmd Debug
```

### 部署
```cmd
deploy.cmd
```
会把 `dinput8.dll` + `sk2_zh.asi` 放进 `I:\LocalGames\Seven Kingdoms II HD\`，
并把 `update\` 拷进游戏目录（先改 `deploy.cmd` 里的 `GAME` 变量）。

### 运行与验证
```cmd
play.cmd        :: Stage 1 只定位自检（默认）
play.cmd 2      :: Stage 2 挂钩 text_width
```
日志：`I:\LocalGames\Seven Kingdoms II HD\update\sk2_zh.log`

也可手动设环境变量 `SK2_STAGE=2` 后直接启动游戏。

**Stage 1 实测日志（2026-10-03 已验证通过）：**
```
[i] stage  = 1
[i] main module base = 00AB0000  (delta = 0x6B0000)
--- 签名搜索结果 ---
[~] Font::text_width       VA=00B70780  (IDA记录 004C0780, 差 +7012352)
      bytes: 55 8B EC 83 EC 20 89 4D F0 C7 45 F8 00 00 00 00
[~] Font::put              VA=00B70AE0  (差 +7012352)
[~] Font::put_paragraph    VA=00B71480  (差 +7012352)
[~] Font::center_put       VA=00B71140  (差 +7012352)
--- 全局变量 (实际地址) ---
[i] screen_w  rva=002862A4 (IDA VA 006862A4) -> 实际 00D362A4 = 1280 (0x500)
[i] screen_h  rva=002862A8 (IDA VA 006862A8) -> 实际 00D362A8 = 960  (0x3C0)
[i] win_flag  rva=002864B3 (IDA VA 006864B3) -> 实际 00D364B3 = 1
[i] base = 00AB0000  delta = 0x6B0000  映像范围 00AB0000-01770000
--- center_put 内的 call 指令 ---
[i] +0x20: call 00B70780   <= text_width (验证锚点)
```

`[~]` 表示「地址与 IDA 记录不同但差值恒定」—— 这正是 ASLR 的表现，
4 个差值全都是 `+0x6B0000` = delta，说明定位完全正确。

**注意**：`win_flag = 1` 表示游戏运行在**窗口模式**，此时引擎会给所有 Font 函数
加屏幕居中偏移。原汉化方案的地址错位根源正在于此（详见 `docs/`）。

### 卸载
删除游戏目录里的 `scripts\` 与 `update\` 两个目录即可，无需还原任何原文件。

---

## 五、核心设计：最小侵入注入

### 引擎的文本机制（IDA 实证）

`Font::text_width`（`0x4C0780`）逐字算宽度：

```c
v14 = *(uint8*)Stra;                                    // 单字节取字符
if (v14 == 32)          w = space_width;               // 空格
else if (v14 < first || v14 > last) w = max_width;     // 表外
else w = font_info[7*(v14 - first) + 1];               // ★ FontInfo 查表，7 字节/项
// 国家色码 0x80-0x8F → 固定宽 13
v12 = 累加 + inter_space;
```

`Font::put`（`0x4C0AE0`）用**完全相同**的查表逻辑画字形，只是把
`v12[1]`（width）从「排版进位」变成「blt 宽度」。

### 关键洞察

`7*ch + font_info - 7*first_char` 是**索引即地址**的映射。
只要码位落在 `[first_char, last_char]` 且 FontInfo 项非零，引擎就会 blit 它。

这意味着：**我们不需要重写渲染器**，只需要
构造一份「等效 FontInfo 池」，让 Big5 码位在表里查到指向宋体点阵的条目，
引擎自己的 `blt`（`sub_4C2A60`）就会把汉字画出来。

相比原方案重写整个 put + blt，这条路：
- 保留引擎的底框、下划线、超链接、国家色条
- 代码量小一个数量级
- 回归风险低

### 三个改造点

| # | 位置 | 改动 |
|---|---|---|
| 1 | `text_width` | 单字节取字符 → 双字节识别，全角计宽 |
| 2 | `Font` 对象 | 注入等效 FontInfo，`first/last_char` 扩到覆盖 lead 字节 |
| 3 | 翻译表 `sub_5B8F00` | 给尾字节 = `0x7E` 的汉字注册替换（否则被当超链接截断） |

---

## 六、已解决的疑难问题

### 段落被 0x7E 截断

IDA 确认 `sub_4C1480` 里 `else if (*v16 == 126)` **无条件**把 `~`(0x7E) 当超链接标记。
Big5 里有 164 个汉字尾字节恰为 `0x7E`（`}` `|` `~` 等），会导致句子被截断。
对策：用自定义 lead 区间 `0x90-0xA0` 重映射这 164 字，避开 `0x7E`。

### Font 对象偏移

原 DLL 用 `pack 1` 推算 `font_info@0x19` / `font_bitmap@0x1D`，
IDA 实证引擎实际访问 `this+25` / `this+29`，**差 12 字节**。
本工程以 IDA 为准（见 `core.h` 的 `font_off` 命名空间）。

### 原 DLL 的地址错位

原方案 16 个 hook 地址中 15 个落在函数体中段（详见 `docs/`）。
本工程全部改用**字节签名搜索**，不依赖绝对地址。

---

## 七、MSVC 编译备忘

本机环境：
- Visual Studio 18 (v145)，MSVC 14.51.36231
- `vcvars32.bat` 路径见 `build.cmd`
- **源码必须带 UTF-8 BOM**（项目里有中文注释，MSVC 默认代码页 936 会报 C4819 并导致语法错乱）

命令行手动编译参考：
```cmd
cl /nologo /c /EHsc /std:c++17 /W3 /utf-8 /O2 ^
   /I"<msvc>\include" /I"<winsdk>\um" /I"<winsdk>\shared" /I"<winsdk>\ucrt" ^
   /Foobj_test\ core.cpp hooks.cpp fontdata_stub.cpp dllmain.cpp

link /nologo /DLL /OUT:sk2_zh.asi /SUBSYSTEM:WINDOWS /MACHINE:X86 ^
   obj_test\core.obj obj_test\hooks.obj obj_test\fontdata_stub.obj obj_test\dllmain.obj
```

---

## 八、下一步

1. **跑 Stage 1**，确认 4 个 `[O]`
2. 确认后切 `SK2_STAGE=2` 验证 text_width 挂钩不崩
3. 实现 Stage 3：生成真字库（迁移 `gen_fontdata.py`）+ FontInfo 注入
4. 补齐 4 个未汉化的 Campaign 文件（`tutorial.stg` / `tutorial.evt` / `EAST.TXR` / `INTROTXT.RES`）

---

## 附录 A：Stage 2 的离线自测

Stage 2 阶段资源仍是英文，**游戏里跑不到双字节分支**，光看画面无法判断钩子是否正确。
因此挂钩前会先跑一组离线自测（`SelfTest()`），用构造的假 Font 对象直接调
`Hook_text_width`，验证宽度算法：

```
--- 离线自测 (假 Font 对象) ---
[O] ASCII  "AB"                  期望  18  实得  18
[O] DBCS   "BD 54"(確)           期望  17  实得  17
[O] MIX    "BD 54 41"            期望  26  实得  26
[O] DBCS2  "A4 A4"(中)           期望  17  实得  17
[i] 自测结果: 4 通过, 0 失败
[O] 双字节宽度逻辑正确，可以进入 Stage 3
```

**全部 `[O]` 才说明宽度算法正确**，此时才值得投中文资源。
这组用例同时作为 Stage 3 的回归基准。

若游戏里出现含高位字节的串，会打印探针行便于核对：

```
[dbg] tw#1 w=34 dbcs=3/0 "BD 54 A4 A4 A9 77 ..."
```

---

## 附录 B：踩过的坑（均已修复）

| # | 现象 | 根因 | 修法 |
|---|---|---|---|
| 1 | dinput8.dll 无效 | EXE 导入 `DINPUT.dll` 而非 `DINPUT8.dll` | 改用游戏自带 MILES modloader |
| 2 | 满屏乱码 | 渲染器未实现时投了中文资源，Big5 字节被当单字节 glyph 查表 | 资源暂存 `update_res_staged/`，Stage 3 后再投 |
| 3 | 全局变量读到 0 | `Rva()` 误写成 `Base()+Delta()+rva`，多加一个 delta | 改回 `Base()+rva`（RVA 本就含基址相对量） |
| 4 | line_count 越界 | `dword_8D7F24` 的 RVA 写成 `0x48D7F24`，正确是 `0x4D7F24` | 修正常量 + 加 `InImage()` 越界保护 |
| 5 | MSVC 74 个语法错误 | 注释里的 Unicode 制表符在代码页 936 下截断语法 | 换 ASCII + 加 UTF-8 BOM + `/utf-8` |

**共同教训**：地址类常量必须用「VA − ImageBase」换算，并**验证是否落在 PE 段表范围内**。
现在 `core.h` 里每个 RVA 都标了所属段，`SafeSetInt` / `SafeAddInt` 会在越界时告警而非静默写坏内存。

---

## 附录 C：★ hook 的 ABI 必须精确匹配（崩溃教训）

### 崩溃现场

Stage 2 挂钩后游戏立即崩溃，dump 分析结果：

```
ExceptionCode    = 0xC0000005  (ACCESS_VIOLATION，读)
ExceptionAddress = 0x6E4F1653
内存读地址        = 0x00000357   ← 近 NULL 读取
```

用模块列表对照，异常地址落在 `scripts\sk2_zh.asi` 内部
（`0x6E4F0000-0x6E512000`，偏移 `+0x1653`）→ **崩溃在我们自己的 hook 代码里**。

### 根因：调用约定不匹配

从 EXE 尾部字节确认，`text_width` 的收尾是 `C2 10 00` = **`ret 0x10`**，
即 `__thiscall`：`ECX=this`，栈上 4 个参数。

我最初写成 5 参数 `__fastcall`：

| | 引擎实际给的 | 5 参数 fastcall 以为的 |
|---|---|---|
| ECX | this | font ✓ |
| EDX | 未定义 | **str（垃圾指针）** ✗ |
| 栈 | Str,a3,a4,a5（16B） | a3,a4,a5（12B）✗ |
| 收尾 | `ret 0x10` | `ret 0x0C` ✗ |

两个后果同时发生：
1. `str` 读到 EDX 的垃圾值 → 解引用 → ACCESS_VIOLATION
2. 栈少清 4 字节 → 返回地址错乱

### 修法：6 参数 __fastcall 模拟 __thiscall

MSVC 不允许在自由函数上用 `__thiscall`（实测 `error C3865: 只能用在本机成员函数上`），
因此加一个占位参数吸收 EDX：

```c
// 入口：精确匹配引擎 ABI（ECX=this, 栈=Str,a3,a4,a5, ret 0x10）
static int __fastcall Hook_text_width(int* font, void* edx_sink,
                                      const char* str, int a3, int a4, int a5) {
    (void)edx_sink;
    return TextWidthImpl(font, str, a3, a4, a5);   // 实现体用普通 cdecl
}

// 真实实现：普通函数，便于直接调用与自测
static int TextWidthImpl(int* font, const char* str, int a3, int a4, int a5);
```

`dumpbin` 验证生成代码，与引擎完全一致：

```asm
push dword ptr [esp+10h]   ; a5
push dword ptr [esp+10h]   ; a4
push dword ptr [esp+10h]   ; a3
push dword ptr [esp+10h]   ; str
push ecx                   ; this
call TextWidthImpl
add  esp,14h
ret  10h                   ; ← 与引擎的 C2 10 00 一致
```

### 其余三个 hook 的 ABI（后续实现时照此办理）

| 函数 | 栈参数个数 | `ret` 立即数 | 入口写法（参数个数） |
|---|---|---|---|
| `Font::text_width` @4C0780 | 4 | `ret 0x10` | 6 参数 |
| `Font::put` @4C0AE0 | 6 | `ret 0x18` | 8 参数 |
| `Font::put_paragraph` @4C1480 | 9 | `ret 0x24` | 11 参数 |
| `Font::center_put` @4C1140 | 5 | `ret 0x14` | 7 参数 |

**通用规则：`__fastcall` 参数个数 = 2（ECX/EDX）+ 引擎的栈参数个数。**

### 新增的两道防线

1. **自测门禁**：`SelfTest()` 未通过时**拒绝安装挂钩**（上次自测 0/4 仍装了钩子 → 崩）
2. **ABI 校验**：安装前在函数体内扫描 `ret 0x10`，找不到就不挂钩
3. **单例互斥**：modloader 会同时扫描 `scripts\` 与 `update\`，
   同名 asi 若存在两份会被加载两次 → 双份 Worker 并发打补丁 + 日志交错。
   现在用命名 mutex 保证只有一个实例干活。

### 附带发现：ASI 曾被加载两次

dump 的模块列表显示：

```
6E4C0000-6E4E2000  I:/.../update/sk2_zh.asi    ← 早期遗留的副本
6E4F0000-6E512000  I:/.../scripts/sk2_zh.asi
```

`update\sk2_zh.asi` 是早前误拷的重复文件，已删除。
**插件只放 `scripts\`，`update\` 只放资源与日志。**

---

## 附录 D：自测抓出的 bug —— signed char 陷阱

Stage 2 第一次跑，自测 `4 通过 / 1 失败`：

```
[O] DBCS   "BD 54"(確)   期望  17  实得  17
[X] DBCS2  "A4 A4"(中)   期望  17  实得  18     ← dbcs=0/2，没识别成双字节
```

两个都是合法 Big5 对（`BD54`=確，`A4A4`=中），差异只在**尾字节**：

| 尾字节 | 作为 `signed char` | `IsTrailValid` 结果 |
|---|---|---|
| `0x54` = 84 | `84`（正数） | ✅ 合法 → 识别为双字节 |
| `0xA4` = 164 | **`-92`** | ❌ 非法 → 当成两个单字节 |

根因：`p` 是 `const char*`（signed），所以 `p[1]` 在 ≥ `0x80` 时变成**负数**，
`IsTrailValid(-92)` 两个区间都不匹配 → 判定非法。

后果很严重：**Big5 里绝大多数汉字的尾字节都 ≥ 0xA1**，
即「中」「文」这类常用字全都会漏判成两个单字节 —— 宽度算错一倍。

修法：读取时强制转 `unsigned char`。

```c
const int trailU = (unsigned char)p[1];   // ← 必须转无符号
if ((lead >= B5_LEAD_MIN && lead <= B5_LEAD_MAX && IsTrailValid(trailU)) || ...)
```

**这是自测机制第一次真正发挥作用**：不需要投资源、不需要看画面，
就在日志里把「宽度算法错了」直接暴露出来。若照原计划直接投中文资源，
现象会是「中文只占半个字宽、互相重叠」——很难定位到是这个原因。

### 回归用例已扩充到 11 条

专门覆盖易错边界：

| 用例 | 覆盖点 |
|---|---|
| `A4 A4` / `A1 A1` / `C1 FE` | 高位尾字节（signed char 坑） |
| `90 40` | 自定义 lead 区间（0x90-0xA0） |
| `A1 7E` | 尾字节 = `0x7E`（撞超链接标记的字） |
| `A  B` | 空格推进逻辑 |
| `A4A4 41 A4A4` | 双字节与 ASCII 混排 |
| `""` | 空串 |

已在 Python 侧独立复现算法并验证 11 条全部通过。

---

## 附录 E：Font 字段偏移错位（排版变得不正常的原因）

Stage 2 自测 11/11 通过、钩子装上、不崩溃，**但英文排版明显错乱**。
说明 hook 虽然安全接上了，但**读错了 Font 对象的字段**。

逐个函数核对 IDA 反编译后发现，引擎实际访问的偏移是：

| 字段 | 引擎用的偏移 | 我早期写的 | 结果 |
|---|---|---|---|
| `font_height` | +9 | 9 | OK |
| `space_width`（也是越界字回退宽） | **+17** | ~~11~~ | ✗ |
| `inter_space` | +19 | 19 | OK |
| `first_char` | **+21** | ~~15~~ | ✗ |
| `last_char` | **+23** | ~~17~~ | ✗ |
| `font_info` | +25 | 25 | OK |
| `font_bitmap` | +29 | 29 | OK |

**8 个字段里错了 3 个**，整体错位一格：我读的「first_char」其实是引擎的
宽度估算字段，读的「space_width」落在未明字段上 → 每个字的推进量都算错 → 排版错乱。

关键证据（`text_width` / `put` / `put_paragraph` 三个函数交叉一致）：

```c
// text_width
v13 = v12 + *(__int16 *)(this + 17);                        // 空格宽
if (v14 < *(u16*)(this+21) || v14 > *(u16*)(this+23)) ...   // first / last
  7 * (v14 - *(u16*)(this + 21)) + *(_DWORD *)(this + 25)   // FontInfo 查表
v12 = v13 + *(__int16 *)(this + 19);                        // inter_space
```

**教训**：字段偏移必须逐个函数核对，三处一致才敢用；
不能凭「结构体看起来应该是这样」推断。本次正是靠三函数交叉验证才发现。

### 新增：运行期 Font 对象转储

`DumpFontOnce()` 在第一次真实调用时打印整个 Font 对象，
用于**实证**偏移是否正确（自测用的是假对象，验证不了真实布局）：

```
[i] --- 真实 Font 对象转储 @ 00D12345 ---
      +00: 01 00 00 00 00 0C 00 00 0F 00 08 00 10 00 08 00
      +10: 08 00 01 00 20 00 FF 00 ...
[i] 解释: space=8 inter=1 first=32 last=255 info=0x...
[O] 字段偏移合理性: first=32 last=255
```

期望值：`first≈32`（ASCII 起始）、`last≈255`、`info` 非空、`inter_space` 很小。
若这些值明显异常，说明偏移仍不对 —— 这是字段层面的最后一道校验。

---

## 附录 F：日志被自己关掉 + 跳板权限（两个把结论带偏的 bug）

### bug 1：`CloseLog()` 让所有运行期日志凭空消失

`Worker()` 结尾原本调用了 `CloseLog()`，把日志句柄关了。之后 hook 里的
**所有输出（Font 转储 / 调用追踪 / 探针）都写进已关闭的句柄，被静默丢弃**。

后果：日志里「安装部分完整、运行期一片安静」，看起来像「hook 没生效」，
实际上 hook 正常，只是没地方写日志。**我被这个现象骗了两轮。**

修法：日志保持打开到进程退出，只在 `DLL_PROCESS_DETACH` 时关闭。
同时把「编译时间」和「运行时间」分开打印（原先 `__DATE__`/`__TIME__`
是**编译期**宏，看起来像运行时刻，误导判断）。

### bug 2：跳板内存被恢复成不可执行 → 执行即崩溃

`BuildTrampoline` 把跳板放在 DLL 的静态数组里（`.data` 段，保护 `PAGE_READWRITE`），
写完代码后**又把保护恢复成 `old`**，于是跳板变回不可执行：

```
ExceptionCode = 0xC0000005
Address       = 0x6E50EA60     ← 正是日志里「已建原函数跳板 @ 6E50EA60」
param[0]      = 0x00000008     ← 访问类型 = EXECUTE
```

`ACCESS_VIOLATION` 的 `param[0]`：`0`=读 `1`=写 `8`=执行。这里明确是**执行权限**违例。

对比 `InstallJump` 为什么没事：它恢复的是被挂钩函数的原始保护
`PAGE_EXECUTE_READ`，本来就可执行。

修法：改用 `VirtualAlloc(PAGE_EXECUTE_READWRITE)` 分配跳板，**且不恢复保护**。

### 附带发现：MILES modloader 是延迟加载插件

多次实测，ASIS 在**游戏启动约 25~30 秒后**才被 modloader 加载。
早期我只等 25 秒就去读日志，正好卡在加载之前，误以为插件没跑起来。
测试时请**等够 60 秒以上**。

---

## 附录 G：差分验证 —— Stage 2 的最终证明

为确认「我们的宽度计算与引擎逐字节一致」，加了差分验证：
用 `BuildTrampoline` 造出原函数的可调用副本，在每次 hook 调用时
**同时调用原函数**并比对返回值。

（原函数走 `__thiscall`；用 `__fastcall(font, sink, str, a3, a4, a5)` 调用
恰好生成相同的调用序列，见附录 C。）

只对**纯 ASCII 串**比对——中文串上原函数本就该给出不同结果，那是我们要改的。

实测结果：

```
[i] 已建原函数跳板 @ 03AD0000（用于差分验证）
[i] --- 真实 Font 对象转储 @ 00D37AFC ---
      +00: 01 00 00 00 00 00 00 00 00 0E 00 0E 00 12 00 0E
      +10: 00 07 00 03 00 21 00 FF 00 ...
[i] 解释: init=1 height=14 unk11=14 unk13=18 est=14
[i] 解释: space=7 inter=3 first=33 last=255 info=095FB0C0
[O] 字段偏移合理性: first=33 last=255
[dbg] call#1 a3=6 a4=0 a5=1 -> 54 len=6 "Single"
[dbg] call#3 a3=13 a4=0 a5=1 -> 125 len=13 "Single Player"
[O] 差分验证: 已比对  25 次, 不符 0 次
[O] 差分验证: 已比对  75 次, 不符 0 次
[O] 差分验证: 已比对 150 次, 不符 0 次
[O] hook 确认生效（已被游戏调用）
```

**150 次 ASCII 串比对，0 次不符** → 宽度计算与引擎完全一致，
英文排版不会漂移。Font 字段偏移也由真实对象实证：`first=33 / last=255 / space=7 / inter=3`。

### Stage 2 完成状态

| 验证项 | 结果 |
|---|---|
| 离线自测（11 条，含双字节/高位尾字节/自定义区） | ✅ 11/11 |
| ABI 校验（`ret 0x10`） | ✅ |
| Font 字段偏移（真实对象实证） | ✅ first=33 last=255 |
| hook 是否被调用 | ✅ 累计 88 次 |
| 与引擎逐串差分比对 | ✅ 150 次 0 不符 |
| 游戏稳定性 | ✅ 无崩溃 |
| 英文排版 | ✅ 正常 |

---

## 附录 H：Stage 3 中文渲染（进行中）

### 为什么不能只注入 FontInfo

引擎的字形表按**单字节**索引（`FontInfo[ch - first_char]`，ch 是 byte），
最多 256 个槽位；而汉字有 5317 个 —— 所以必须自己画。
旧工程的做法也是挂钩 `Font::put` 自绘，本工程沿用该思路。

### 渲染实现（cjk.cpp）

```
字节对 (lead, trail)
  ├─ lead ∈ [0x90,0xA0]  → custidx 表（164 个尾字节危险字的自定义安全对）
  └─ lead ∈ [0xA1,0xF9] + 合法 trail → big5idx 表
        ↓ 字形序号
  宋体点阵 13/16/24px（1bpp 掩码 + (1,1) 阴影，透明色 0 与 255）
        ↓
  引擎 put_bitmap @0x4C2A60（active_buf = off_68123C）绘制
```

- **纯 ASCII 串直接转交原函数**（`Font::put` 跳板），保证英文排版零回归
- 含中文的串分段：ASCII 段走原函数，中文对自绘
- 背景清除复用 `put_bitmap` 填纯色位图，只需 1 个引擎 API

### 本机（GOG）与旧工程（Steam）地址对照

| 函数 | Steam 版 | **本机 GOG 版** |
|---|---|---|
| Font::text_width | 0x4C0750 | **0x4C0780** |
| Font::put | 0x4C0AB0 | **0x4C0AE0** |
| Font::put_paragraph | 0x4C1450 | **0x4C1480** |
| Font::center_put | 0x4C11C0 | **0x4C1140** |
| upper_case (toupper) | 0x4C28C0 | **0x4C28F0** |
| put_bitmap | 0x4C2A30 | **0x4C2A60** |
| active_buf | 0x68123C | **0x68123C**（同） |

Font 对象布局两版一致（+9 std_h / +11 max_w / +13 max_h / +17 space /
+19 inter / +21 first / +23 last / +25 info / +29 bitmap）。

### 本轮修复的三个 bug

| # | 现象 | 根因 | 修法 |
|---|---|---|---|
| 1 | 重影（甲） | 宽度按 13px 进位、字形按 16px 绘制 → 每字重叠 3px | 档位规则统一用 +9(std_height) |
| 2 | 重影（乙） | 颜色直方图把**透明色 0** 当正文色 → 黑字画黑底，只剩阴影 | 直方图排除 0 与 255 |
| 3 | 排版宽度偏差 | `a5==1` 时引擎先转大写再测宽，我们的 hook 没转 | 接入引擎 toupper @0x4C28F0 |

### 绘制路径覆盖

| 函数 | 状态 |
|---|---|
| `Font::put` @0x4C0AE0 | ✅ 已挂钩 |
| `Font::center_put` @0x4C1140 | ✅ 内部调用 `Font::put`，已覆盖 |
| `Font::put_paragraph` @0x4C1480 | ⬜ **自行调 put_bitmap 绘制，必须单独挂钩** —— 段落/提示/战役正文乱码的来源 |
| `Font::put_char` | ⬜ 待确认（教程提示弹窗用） |

---

## 附录 I：编码体系（v2「Big5 原生」）与三处必须一致的地方

### 数据存 Big5，显示走简体

资源文件里存的是 **Big5（繁体）字节**；插件渲染时经
`cp950 解码 → zhconv 转简体 → 查字形表`，所以玩家看到的是**简体**。
因此新增译文必须用「简体文本 → s2t → cp950」编码（`tools/build_gap.py` 的 `enc()`）。

### 危险尾字节 → 自定义对（0x90-0xA0）

Big5 尾字节范围 0x40-0x7E 里，有 7 个字节是**引擎的控制字符**：
`[ ] { | } ~ (0x5B 0x5D 0x7B 0x7C 0x7D 0x7E 0x7F)` —— 例如 `~` 是分页/超链接标记、
`[` `]` 是 tag 定界符。像 **魔(C55D) / 年(A67E) / 外(A57E) / 會(B77C)** 这类常用字
的尾字节正好撞上，引擎会把一个汉字劈成两半解释。

旧工程的解法：把这类字改用 **lead 0x90-0xA0** 的自定义对（Big5 不可能出现的 lead，
且避开国家色码 0x80-0x8F）。本工程沿用同一套映射。

**映射的来源**：旧工程用 `risky_map.init(charset)` 按字符集排序**确定性分配**，
而字符集已无法完整重建 —— 但结果保存在 `fontdata.h` 的 `custidx` 里，
`tools/fontlib.py` 用 `big5idx` 反推「字形 → 字符」，从而把映射逆向出来
（113 个字符可逆）。`build_gap.py` 编码后会自动做这步替换（**长度不变**，都是 2 字节）。

### 补充字形表 fontdata_extra.h

主表的 5317 个字形来自**旧译文的语料**，不含我们新增译文用到的少量汉字
（实测 14 个：课/碎/阀/陲/涌/恭/滓/粉/峻/宽/囤/祇/塑/渗）。

**不动主表**（改主表会让既有资源的全部索引错位），而是追加一张独立表：
`GlyphIndex()` 先查 `big5idx`，为 0 时再查 `g_extraCode[]`，
返回 `N_CHARS + i`；`GlyphMask()` 按索引区间分派。补充表由
`tools/gen_extra.py` 用 simsun 渲染（与主表同参数：单元格 px+2、1bpp、内含 (1,1) 阴影）。

### 三处必须一致

| 项 | 位置 | 说明 |
|---|---|---|
| 字形档位 | `core.h` 的 `GlyphPx()` | 测量侧与绘制侧共用，凭 `max_height(+13)` 分档（16px） |
| 危险尾字节映射 | `tools/fontlib.py` | 与既有资源一致；新增译文必须走同一映射 |
| 字形索引空间 | `cjk.cpp` `GlyphIndex/GlyphMask` | 主表 0..N_CHARS-1，补充表 N_CHARS.. |

---

## 附录 J：Stage 3 绘制路径全覆盖（乱码问题的根因）

引擎有**三条**各自画字的路径，只挂一条就会有区域仍是乱码：

| 函数 | 地址(GOG) | ABI | 覆盖范围 | 状态 |
|---|---|---|---|---|
| `Font::put` | 0x4C0AE0 | ret 0x18 | 单行文本 | ✅ 已挂 |
| `Font::put_paragraph` | 0x4C1480 | ret 0x20 | 段落/简报/列表（**自己画字**） | ✅ 已挂 |
| `Font::put_char` | 0x4C0FE0 | ret 0x0C | 教程提示（逐字绘制，虚表调用） | ✅ 已挂 |
| `Font::center_put` | 0x4C1140 | ret 0x14 | 居中文本 | ✅ 内部调 `Font::put` |
| `center_put_para`（sub_4C1A80） | 0x4C1A80 | — | 居中段落 | ✅ 内部调 `sub_4C11F0` → `Font::put` |

`put_paragraph` 的参数语义（由调用方 `sub_4C13A0` / `sub_4C1E50` 实证）：

```
a3=x1  a4=y1  a5=x2  a6=y2  a7=串  a8=行距  a9=起始绘制行+1  a10=是否绘制
a2(EDX) 与 a3 同值、函数体不用；ECX=this，栈上 8 个参数 -> ret 0x20
```

`sub_4C1E50` 是「只测量不绘制」的循环（反复以 a9=1, a10=0 调用、累加行数，
靠 `*(this+1)=next_text` 回写推进）——所以自实现**必须同样回写状态**，
且 a10=0/1 两种模式的排版结果必须一致。

策略：**纯 ASCII 串一律转交原函数**（中文以外的排版零回归），
含中文的串才自行排版；ASCII 部分仍用引擎自己的字形（`put_bitmap`，与原函数逐字节一致）。

---

## 附录 K：补充翻译进度

盘点工具：`tools/inv_missing.py`（英文原版 vs 我们的中文包，逐 tag 比对）

**已覆盖文件里 191 条「未译」中，182 条是引擎的 `Reserved` 占位槽**（非可见内容），
真实缺口只有 9 条：`t_gmenu`(5) / `t_reps`(1) / `t_sedit`(1) / `t_unit`(1) / `TUT_TEXT`(1)。

整文件缺失（本次已补齐第一批）：

| 文件 | 记录数 | 状态 |
|---|---|---|
| `Campaign/EAST.TXR` | 19 | ✅ 已译并生成 |
| `Campaign/EAST.DLG` | 3 | ✅ |
| `Resource/TUT_INTR.RES` | 12 | ✅ |
| `Resource/INTROTXT.RES` / `CPG_INTR.RES` / `Campaign/INTROTXT.RES` | 1×3 | ✅ |
| `t_gmenu/t_reps/t_sedit/t_unit` 的 9 个 tag | 9 | ✅ |
| `Campaign/tutorial.stg` / `tutorial.evt` | 45 + 28 | ✅ 第二批已完成（100% 覆盖） |
| `Resource/CREDIT.RES` | 4 | ➖ 全是人名，无需翻译 |

工具链：`zh_data.py`（译文源，简体） → `build_gap.py`（编码 + 重映射 + 重建容器）
→ `gen_extra.py`（补字形） → 重新编译 ASI。

### 第二批（教程战役）的两点关键发现

**1. 教程与东方战役同源，能复用就不重译。**

`tutorial.stg` / `tutorial.evt` 与 `EAST.STG` / `EAST.EVT` 出自同一批素材：

| 文件 | 记录数 | 英文与 east 逐字节相同 | 需另写 |
|---|---|---|---|
| `tutorial.stg` | 45 | 17 | 28 |
| `tutorial.evt` | 28 | 7 | 21（其中 16 条只差占位记号） |

- **逐字节相同**的走「同源字节复用」：直接搬 `east.stg`/`east.evt` 已编码好的中文记录，
  不重新编码，字形与自定义对 100% 一致。
- 教程版把 `%s` 换成了**字面记号** `(name)` / `(species)` / `(Date)`。
  复用时按英文里记号的出现顺序逐个替换 `REUSE_EVT_SUB`，
  脚本会校验「记号数 == 中文 `%s` 数」，对不上就放弃复用并报警。
- 只有 5 条（12A / 5A / 8B / 9C1 / 9C2）因为英文结构不同，必须另写。

**2. `着` 编不进 cp950。**

简体「着」不在 Big5 里，zhconv 也不会把它转成「著」，
会被 `enc_zh` 回退成全角空格（游戏里就是一个空洞）。
第二批译文里统一写成「著」。

### 补字：从「扫 gap_zh.json」改成「扫成品资源」

`gen_extra.py` 原来只从 `gap_zh.json`（简体译文源）收集缺字，
**漏掉了同源复用搬过来的字节和 TUT_TEXT.RES 里的旧译文**。
实测已发货的 `TUT_TEXT.RES` 就有 7 个字形是空的（冀 壣 盔 磾 茯 鰨 ヶ）。

新增 `collect_missing_dir()`：直接扫 `update_res_staged/` 下所有成品资源
（跳过 STD.SET —— 它的二进制段会产生近 2000 条假缺字），
用 `is_glyph_char()` 过滤掉符号/框线。`EXTRA_N` 因此 15 → 45。

---

## 附录 L：★★ STD.SET 的「引擎侧字符映射」——乱码的真正根源

### 症状与二分定位

游戏内「新建玩家」对话框左侧那 12 行（国家名）显示为
`鵔漫動 / 犒褡 / 凱漫艋 / 羅倏 / 嚭唱 / 鵔捋 / 蒙屖 …`，
字形是**真实汉字但内容全错**。

用排除法逐步缩小：

| 实验 | 结果 |
|---|---|
| 撤掉全部 `update\Resource` 覆盖 | ✅ 12 行恢复 `Norman / Viking / Roman …` |
| 只排除 `STD.SET`（其余资源照旧） | ✅ 12 行恢复正常 |

**结论：`STD.SET` 是唯一元凶。**

日志侧证据（`put` 钩子记录引擎查表后所见字节）：

```
修复前: <F1><DA><BA><A9><B0><CA>   cp950 解码 = 鵔漫動
修复后: <BA><FB><A8><CA>            cp950 解码 = 維京  ✓
```

### 根因：引擎把 STD.SET 的高位字节逐个查表替换

在 `7K2.exe` 偏移 **`0x27F028`** 找到一张 **256 项按字节值索引的映射表**。
用 12 组已知映射（`A4→F1`、`E9→DA`、`B8→A9`、`A8→BF`、`A5→D1`…）验证，**12/12 吻合**。

机制：**ASCII 落在低位、不受影响**，所以原版英文正常；
旧汉化包把中文写成 Big5，高位字节全被查表替换 → 逐字节被打乱。

```
标准 Big5:  諾 曼  =  BF D5  B0 D2
引擎查表后:        F1 DA  BA CA        ← 完全不同的字节
```

### 表是「部分函数」——这决定了修法

| 区段 | 项数 | 说明 |
|---|---|---|
| `0x80-0xFF` 输入 | 128 | 其中 **33 项映射成 `?`(0x3F)**，另有 2 项落到低位（`D5→0x27`、`F2→0x3D`） |
| 不同输出值 | **95** | 高位 93 个 + 低位 2 个 |
| `0x00-0x7F` | 128 | **不是映射表**（是相邻代码字节）；低位不查表，英文才能正常 |

因此并非所有字节都能「写进去再被引擎还原」。写盘字节 `S` 必须满足
`table[S] == 目标字节`，即目标字节必须在**可生成集合**内。

**Big5 范围内不可生成的字节：`AD` / `AF` / `B8`**（另加 `0x80-0xA0` 整段，
但那不属于 Big5 有效范围），实测影响 **77 个汉字**（爾/特/納/迪/蒂/烏/索/倫/茲/萬…）。

### 修法：逆向预映射 + STD 专用码位

**第一步（通用）**：把目标字节做**逆映射**再写盘，引擎查表后正好还原。

```
写入  inv[table[目标]]   --引擎查表-->   目标   （我们要的 Big5）
```

例：`印度 = A6 4C AB D7` → 写入 `A6 4C AB D7` 的逆映射 → 引擎还原为 `A6 4C AB D7` ✓

**第二步（补盲区）**：`AD/AF/B8` 共 77 个字无源可用，迁到**可达且空闲**的码位：

- `big5idx` 已占 4467 个 Big5 码位，剩余「可达且空闲」有 **3411 个**
- 新增 `fontdata_std.h`：`g_stdOrig[]`（原码）/ `g_stdCode[]`（备用码位）/ `g_stdGlyph[]`（字形下标）
- **字形池完全复用**（映射到主表既有字形，不新增字形）
- `cjk.cpp` 的 `GlyphIndex()` 在 `big5idx` 查空后查 `g_stdCode[]`
- 备用码位只用**低位 trail (0x40-0x7E)**：低位不查表，约束最松（并避开 `[ ] { | } ~` 控制符）

**第三步（顺带修旧包错字）**：旧包把 `NORMAN` 写成「日爾曼」（`A4E9` 在 cp950 里是「日」），
`JAPANES` 写成 `'E日本'`（`E` 挤掉前导空格）。`fix_stdset.py` 内置 `RACE_FIX` 定点修正。

### 三步编码管线

```
旧包字节 ──decode_display──> 显示文本 ──简→繁/cp950──> 标准 Big5
                （自定义对 0x90-0xA0 也解）
                                    │
                    含 AD/AF/B8? ────┴──> 换成 STD 专用码位
                                    │
                          premap（逆映射）──> 写盘
                                    │
                          引擎查表 ──> 还原为标准 Big5 ──> big5idx / stdCode 命中字形
```

### 工具链

| 工具 | 作用 |
|---|---|
| `tools/fontlib.py` | 从 `fontdata.h` 反推「字符 ↔ 自定义对」映射；字节解码 |
| `tools/gen_stdmap.py` | 扫描 STD.SET 已译字段 → 生成 `fontdata_std.h`（含 77/77 回环校验） |
| `tools/fix_stdset.py` | 三步编码 + 写盘（`--dry` 干跑，输出逐条回环样本） |
| `tools/gen_extra.py` | 补字形（同时扫 `gap_zh.json` 与 STD.SET 差异区） |

### 效果

```
translated tokens : 3611
  pre-mapped OK   : 3604      (99.8%)
  reverted to EN  : 7         (含无法编码的符号)
STD slots used    : 77        (AD/AF/B8 盲区)
race name fixes   : 2
```

容器结构校验：52 条记录、偏移表、文件长度与原版**完全一致**，
仅 2.1% 字节变化。端到端离线验证（拿日志实测字节喂字库）：

```
BFD5 A144 B0D2 -> 诺 尔 曼     B3CD A144 A145 -> 凯 尔 特
BAFB A8CA      -> 维 京        C3B9 B0A8      -> 罗 马
A7C6 C3BE      -> 希 腊        A159 A4D3 B0F2 -> 迦 太 基
A4A4 B0EA      -> 中 国        A4E9 A5BB      -> 日 本
BB58 A56A      -> 蒙 古        AE4A A4CE      -> 埃 及
AA69 B4B5      -> 波 斯        A64C ABD7      -> 印 度
```

**全部命中字形，无一缺字。**

### 排查方法论（可复用）

1. **排除法二分**：先撤全部覆盖 → 再逐文件放回，锁定唯一元凶
2. **模板匹配截图**：把屏幕字形与字库点阵做 IoU 匹配，反推 `glyph` 索引，
   再由 `big5idx` 反查该字形的所有 Big5 码 —— 得到「引擎查表后所见字节」
3. **在 EXE 里搜特征字节**：已知 12 组映射，用它们定位 256 项表
4. **区分「映射」与「相邻数据」**：表在 `0x00-0x7F` 的内容是 x86 指令字节，
   靠「英文在原版正常」反推出低位不查表 —— 否则会把 `T[0x4E]=0x00` 当成
   「N 被映射成空」而得出完全错误的结论

**旧工程从未解决这个问题**：它把 STD.SET 的中文直接写成 Big5，
所以这 12 行（以及所有 STD.SET 文本）在旧汉化包里一直是乱码。

---

## 附录：RLE 精灵崩溃取证（`7K2+0x2750`）

多次崩溃表现完全一致，工具：`tools/dumpinfo.py`。

### 崩溃现场

```
EIP = 7K2.exe + 0x2750   异常 0xC0000005 读 0x10C79000
调用链: sub_402610 <- sub_494D80 <- sub_619B40 (call @0x619FFF)
```

`sub_402610` 是 **16bpp 精灵 RLE 解码绘制**（`0xF8` 转义、`0xEF..0xF8` 控制符）；
真正崩的是它的 `.L2` 子函数 **`sub_40274B(ah, ecx, esi)`**：

```c
// 语义：在压缩流里「跳过 ecx 个像素」以实现裁剪
while (ecx) { b = *esi++; if (b < 0xF8) { if (!--ecx) return; } ... }
```

即：**跳过量超过精灵实际数据长度，就读到分配区外的未映射页。**

### 从栈帧还原的实参（`[EBP+8]` 起的 10 个参数）

| dump | 目标坐标 | 精灵 | 绘制区 | 消耗字节 |
|---|---|---|---|---|
| `39892` | (820,597) | `0x11AC6054` | 236×360 | 520,108 |
| `29428` | (948,693) | `0x127FD16C` | 108×264 | 1,060,500 |
| `37060` | (393,445) | `0x10BD313C` | 663×512 | 679,620 |

三次的裁剪参数都是 `left=0 top=0`，且**精灵右下角精确落在视口 (1055,956)**
（`right == 精灵宽-1 && bottom == 精灵高-1`，即未发生裁剪）——
说明这三个精灵都是**整体完整绘制**、只是贴着视口右下角。

### 结论：不要把 `stage.txt` 放进 `update\`

`7K2.exe.37060.dmp` 是**最容易被误读**的一次。取证链条：

1. 日志 `scripts\sk2_zh.log` 明确写着 `stage = 1`、`未打任何补丁`
   —— 源码里 `stage >= 2` 才装第一个 hook，`Stage1_Locate()` 只读；
2. `update\` 早在 **23:50:29** 就被改名成 `update2\`（资源停用），
   而这次运行始于 **23:52:46**；
3. `stage.txt` 当时就在被改名的目录里 → 插件找不到 → 退回 stage 1。

**所以这一跑等于原版**：
没有 hook、没有资源覆盖，画面本就该是全英文。
它不能作为「汉化导致崩溃」的证据；反过来，它说明
**该路径在原版下同样会走到崩溃**。

### 已排除的因素

- **安装损坏**：用 GOG 自带的 `goggame-*.hashdb`（ZIP，记录格式
  `[name:1024][md5:32]`，共 745 条）全量校验 → **745/745 一致，0 损坏**。
  工具：`tools/check_install_integrity.py`
- **直接改动本体**：近 3 天 7K2.exe 及各数据文件均无改动（只动过 `scripts\`、文档）

### A/B 实测结论（用户手动跑出来的）

| 组合 | 结果 |
|---|---|
| ASI 开 + `update\` 关（英文资源） | **不崩溃**，显示正常 |
| ASI 开 + `update\` 开（中文资源） | **崩溃**（`86156.dmp`，同样在 `7K2+0x2750`） |

→ 崩溃的必要条件是「中文文本真的被自绘」，也就是**我们的绘制路径**，
与资源文件本身无关（英文资源下 hook 全部空转也不崩）。

### 已加固：自绘不再可能写穿画布

`sub_403080` 的 ABI 已用 IDA 逐条核对，参数顺序**正确**：

```c
// sub_403080(surface, stride, x, y, bmp16, palette)
//   bmp16 布局 = {u16 w; u16 h; u8 px[w*h]}，255 = 透明
//   v8 = surface + 2*x + y*stride        ← 直接写，不做任何裁剪
```

问题不在参数，在**它完全不裁剪**。原来的兜底用全局 `ScreenW/ScreenH`
判定，但被画的 surface 未必是主屏。现在改成三重：

1. **逐画布宽度**：从 `VgaBuf+268`（行距，由 `sub_4C2A60` 反编译实证）取
   `pitch/2`，或从 puta 路径的 `stride/2`，与全局屏宽取小
2. **提交页探测**：`VirtualQuery` 问 OS 这块矩形是否整块落在 `MEM_COMMIT`
   区间内 —— 不落就**宁可不画**（日志会打 `★目标页未提交 —— 已阻止写穿堆`）
3. 单字节走引擎函数时也补了同样的画布夹取

### 崩溃二分开关（`update\render.ini`）

关掉某条 → 该路径的中文不自绘，其余路径照常。用来把崩溃定位到具体路径。
**注意**：ini 是按子串匹配的，写注释 `# draw=0` 也会被当成开关，别写。

| 开关 | 关掉后谁不画了 |
|---|---|
| `draw=0` | 全部中文自绘（put / 段落 / 逐字节）都退回引擎原函数 |
| `puta=0` | 逐字节路径 `0x4C2110` / `0x4C1F40`（悬浮提示、过场诗句） |
| `para=0` | `put_paragraph`（多行段落排版） |
| `wrap=0` | 居中多行换行 `0x4C1A80` |
| `hyp=0` | 段落里不写引擎的超链接数组（唯一会写引擎全局数组的动作） |
| `clamp=0` | 退回旧的「只用全局屏宽」判定（对照用，不建议） |

排查顺序建议：

1. 默认（全开）跑一次 → 若不再崩，就是上面那三重加固修好了
2. 仍崩 → 加 `draw=0`：
   - 不崩 = 自绘导致，再逐个关 `puta=0` / `para=0` / `wrap=0` 定位到路径
   - 还崩 = 与自绘无关，是中文文本流经引擎路径（查资源记录是否变长，
     工具 `tools/check_rec_growth.py`）

### 字体配色定向覆盖（`fontcolor=`）

**症状**：某几处中文发黑/发灰到看不清，而英文正常。

**原因**：引擎的 ASCII 字形是**预着色位图**（自带渐变描边），中文则是我们生成的
单色点阵，用 `FontColors()` 从该字体位图直方图里取「出现最多的非透明色」当正文色。
一旦某个字体的**描边像素比笔画芯部还多**，众数就取到描边的暗色 → 中文发黑。
英文不受影响，因为它本来就用位图里设计的渐变色。

**修法**：`update\render.ini` 里写 `fontcolor=RVA:值`，多个用 `;` 分隔。
值可以是 `0-255` 的调色板索引，或关键字 `white`（取调色板最亮项，排除 255——
255 被字形缓冲当透明色，取到它会让文字整个消失）。

```
fontcolor=28774C:white;28873C:white
```

**怎么拿到 RVA**：日志里每次取色都会打一行，带 RVA 和**样本串**，直接认 UI：

```
[i] Font 0076873C RVA=28873C 档位=?px 颜色: 正文=? 阴影=? 核心峰=?(?) | 直方图前四 ... | 样本=人口
```

> ⚠️ ini 按子串匹配，**别写注释**（`# fontcolor=...` 会被当成真配置）。

**已配置的字体**（RVA 相对模块基址，不随 ASLR 变）：

| RVA | 档位 | 画什么 | 处理 |
|---|---|---|---|
| `28774C` | 24px | 过场诗句（忆往昔金戈铁马…） | `white` — 字形含 112/146/149/113 四阶，众数落在最暗的 112 |
| `28873C` | — | 城镇面板标签：**人口 / 農民 / 工人 / 反抗度 / 忠誠度** | `white` — 与过场同症状 |

> `28873C` 这个字体**只画这 4~5 个标签**（日志统计 53 次绘制全是它们），
> 所以定向覆盖它不会影响其它任何界面。

**若白色太刺眼**：把 `white` 换成具体索引即可，例如 `fontcolor=28873C:220`。
索引含义见日志里那行的「直方图前四」（`色号(像素数)`），挑一个亮的即可。

---

## 崩溃真凶：STD.SET 的二进制数值字段被当成汉字改写（已修）

用户 A/B 进一步收敛到：**只要 `update\Resource\STD.SET` 存在就崩**。真因不是绘制，
是**资源内容本身被我们写坏了**。

### 根因

STD.SET 是 52 段的结构化二进制。其中 `SFRAME` / `FBITMAP` / `FBITMAP2` 三段是
「名字 + u32 偏移」的紧凑表，例如：

```
"NO-A5-7 " | a8 7c 00 00 | " NO_CIV"     u32 偏移 = 0x00007ca8 = 31912
```

这些 u32 的**低两字节是纯数值**，但若恰好落在大五码危险尾字节范围
（第二字节 ∈ {5B,5C,5D,7B,7C,7D,7E,7F}），就会被「危险尾字节 → 自定义对」
重映射当成汉字改写：

```
a8 7c  ->  91 6f      偏移 31912 变成 28561
```

引擎按错误偏移去读精灵/位图数据 → RLE 解码器越过缓冲区读飞
→ 崩溃在 `7K2+0x2750`（`sub_40274B`「在压缩流里跳过 N 个像素」）。

**与之前的自绘加固完全无关**：加固没错，只是这次崩的不是那条路。

### 误伤统计

| 段 | 处数 | 性质 |
|---|---|---|
| SFRAME | 46 | 精灵帧偏移表 |
| FBITMAP2 | 5 | 设施位图偏移表 |
| FBITMAP | 1 | 设施位图偏移表 |

另发现 `FBUILD` / `FBUILD2` / `TECH` / `TECH_DUP` 各 1 处：原版二进制 `\x9d\x4b` /
`\x9d\x6b` 之后的 ASCII 文本 `sehus` 被「尾巴清理」误删，已一并还原。

### 修复

- 新增 `tools/fix_stdset_binary.py`：检出并还原这类误伤。判据要求同时满足
  「原版是标准大五码危险对」+「汉化版是自定义对」+「其后构成 u32 数值字段
  或位于明确的二进制段」，因此不会碰到真正的译文
- `fix_stdset.py`：在 `fix_risky.remap_verified`（整文件扫描、不认段结构）
  之后新增**固定末步**——把扫描出的二进制误伤原样还原。实测 57 处重映射中
  52 处被正确拦截，以后重新生成也不会再引入

### 一个已踩过的坑

早期判据用「前缀是否含高位字节且未被汉化改写」来区分误伤，在 `RACENAME` 段
**误判 199 处**：中文名之间无空格分隔，前缀回溯会跨过多个名字。
现已回滚，改为只按「u32 数值字段形状 + 二进制段白名单」判定。
