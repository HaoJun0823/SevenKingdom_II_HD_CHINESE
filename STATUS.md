# 当前状态标记（2026-10-05 04:30）

> 本文件用于跨会话接手。**状态不明 = 未经用户实测验证的改动。**

## 一、待用户验证（状态不明）

### 1. 全部本轮改动 —— 状态不明
- `update\Resource\STD.SET` 1322443B（04:29 部署）
  - FIRM/FIRM2 建筑名 20 处（`Inn`→`酒館`、4 处残留英文、2 处重复、2 处坏字、1 处错译）
  - MONSTER/TECHCLAS/RACE 坏字节 44 处（`Fryhtan`→`異族` 等）
  - TECHCLAS 残留英文 4 处
  - 四项校验：文件长/记录数/记录名/记录长度 全部与原版一致
- `scripts\sk2_zh.asi` 1305088 字节（04:26 部署）
- `update\render.ini` 已切 `seg=2`
- 部署前备份：`/tmp/update_before_042607`

### 2. 逐字符诊断 `seg=2` —— 目的：定位「游戏进行时间」数字不显示
`cjk.cpp` 新增 `g_asciiDiag`，在段落绘制遍对每个单字节字符打点：
字符码 / 字体 RVA / `FIRST_CHAR~LAST_CHAR` / 有无字形条目 / 字形宽 /
画布宽高。用于区分三种可能：
1. 码不在字体范围外 → `InfoEntry` 返回空 → 被跳过（**目前最怀疑**）
2. 字形宽 `e[1] == 0`
3. 字形正常但被越界检查拦掉

上一档 `seg=1` 已暴露异常：`[seg] #20 段="1" x=1131 测量w=5 原函数返回r=1130`
（返回位置比起点还小 1，等于这段什么都没画），但时间文本走 `put_paragraph`
路径，`seg=1` 覆盖不到，故加第 2 档。

## 二、已定性、不用再查

### 3. 游戏卡死 —— 引擎侧，与本插件无关（已定性）
自动取证抓到 4 次停滞，证据链完整：

| 次 | EIP | 指令 | 停滞 |
|---|---|---|---|
| 1 | `77E59DAC` | `C2 08 00` = `ret 8` | 10 秒 |
| 2 | `7764282C` | `C2 04 00` = `ret 4` | 8 秒 |
| 3 | 同上 | 同上 | 6 秒 |
| 4 | 同上 | 同上 | 28 秒 |

1. EIP 落在 **kernel32 的函数尾声 `ret`**，非可执行指令 → 线程在**等系统调用返回**
2. 停滞期间本插件 hook 计数**全为 0**（`字形=0 put=0 text_width=0`）→ 完全没参与
3. 栈回溯指向 `sub_532F30`，其尾部是
   `if( GetCursorPos(&Point) && ScreenToClient(hWnd, &Point) )`
   —— **每帧问系统要鼠标位置**
4. 熔断看门狗未触发（峰值 3787/秒 < 阈值 40000/秒）→ 兜底机制干净，没误伤

结论：DirectDraw 全屏独占 + 桌面合成器冲突，引擎等输入队列。
**建议用户改窗口模式验证**（窗口模式下该阻塞通常消失）。
死循环会表现为 EIP 稳定停在某条指令；此处跨 4 次采样落在两个不同内核地址。

### 4. x64dbg MCP 反复掉线
工具索引里已查不到任何 x64dbg 工具。自动取证已替代其作用，
且不受系统卡顿影响 —— 无需再依赖它。

## 三、已确认修复（有依据、无需重查）

| 项 | 提交 | 状态 |
|---|---|---|
| STD.SET 建筑名漏译 + 残留（179 处） | `2bf52b8` | 已部署，用户测过建造菜单 |
| diff 工具假阳性修正（空记录/控制符） | `2bf52b8` | 已验证 |
| EAST.EVT / EAST.PLT 顺序对齐 | `16290f8` | 已部署，待用户跑战役验证 |
| STD.SET 表解析器 `db_table.py` | `89ba86b` | 工具 |
| FIRM/FIRM2 + 坏字节 + TECHCLAS（48 处） | `50633ce` | 已部署，待验证 |

**EAST.EVT 对齐的性质**：原先报「49 处结构损坏」是**误报**。
residx 索引项只有「9 字节名 + 4 字节偏移」，无序号字段，引擎按名字查找
（源码 `res_event.read("11A")`），顺序不影响取数据。对齐纯粹是消除 diff 误报、
便于日后校对，记录内容逐字节未变。

## 四、已知未做（待用户决定 / 待处理）

### 4.1 剩余 167 处坏字节（本轮新发现，按影响面排序）
| 表 | 数量 | 内容 |
|---|---|---|
| `RACENAME` | ~120 | 随机人名（维京/罗马/蒙古等族），**界面可见** |
| `TOWNNAME` | ~26 | 城镇名（霍姆德、米克拉…） |
| `TECH` | 6 | 科技描述（含 4 处国家专属建筑残留英文） |
| `HERO` | 5 | 英雄名（阿伽门农、巴图尔…） |
| `FBUILD`/`FBUILD2` | 2 | `Viking <坏字>維京騎兵基地`（上轮清理残留时误伤） |

坏字节成因：译者做「英文→中文」等长替换时整体右移 1 字节，
中文的 Big5 前导字节丢失，尾字节与后字拼成非法序列。
修法同 `fix_bad_bytes.py`：以「原版同位置英文」为锚点，逐条核对后等长替换。

### 4.2 UNIT 表 31 条可见单位名未翻译
- `UNIT` 表完全未翻译（与原版 MD5 相同），但 74 条里只有 **31 条会显示**
  （`RACE_ID=0` 或 `class=WAGON`），其余走已翻译的 RACE/MONSTER 表
- 可见的 31 条：Wagon / Caravan / Catapult / Ballista / Spitfire / Cannon /
  Porcupine / Unicorn / Mega Cannon / Mega Unicon / Mega Saw / Nemezez / Cobrez /
  Peltez / **Archangel / Thor / Dagodevas / Mars / Athena / Baal-Hammon / Chi Lin /
  Amaterasu / Tengri / Isis / Mithra / Hanuman** / Bheema / Tarmes / Jaguara /
  Goril / Rhinokeros
- 另有 `NAME1`/`NAME2` 共 14 个随机人名未翻译（Robert/Lincoln/Peter…）
- 阻塞点：**神名译法需用户确认风格**（`Archangel` = 大天使 / 天使長？
  `Thor` = 雷神 / 索爾？），避免与 `t_unit.res` 现有中文打架
- 字段宽度：UNIT NAME=30 字节、NAME1/2 FIRSTNAME/LASTNAME=12 字节，可等长替换

### 4.3 `TECH_DUP` 整表未翻译
`TECH_DUP` 是 `TECH` 的副本，`TECH` 翻了但副本没同步（69 条 DESC 全英文）。
需确认这张表是否真的会被引擎读取，再决定是否补译。

## 五、接手步骤

```bash
cd /g/Projects/SavenKingdom_II_HD_CHINESE

# 1. 先备份游戏当前 update 资源
cp -r "I:/LocalGames/Seven Kingdoms II HD/update" /tmp/update_before_next

# 2. 改完 unpack_data_chs 后重新打包（勿用旧的 %TEMP% 产物）
cd tools_packer && python pack.py \
  "../unpack_data_chs/Resource/STD.SET.unpacked" "C:/Users/HAOJUN~1/AppData/Local/Temp/STD.SET.new"
cp "C:/Users/HAOJUN~1/AppData/Local/Temp/STD.SET.new" \
   "I:/LocalGames/Seven Kingdoms II HD/update/Resource/STD.SET"

# 3. 部署新 ASI
cp ../SavenKingdom_II_HD_CHINESE/objs/sk2_zh.asi \
   "I:/LocalGames/Seven Kingdoms II HD/scripts/sk2_zh.asi"

# 4. 四项结构校验（每次打包后必做）
python -c "
import sys, os; sys.path.insert(0,'.')
import packlib as P
a=open(r'I:\LocalGames\Seven Kingdoms II HD\Resource\STD.SET','rb').read()
b=open(os.path.join(os.environ['TEMP'],'STD.SET.new'),'rb').read()
ca,ea=P.read_residx(a); cb,eb=P.read_residx(b)
print('长度',len(a)==len(b),'记录数',ca==cb,
      '名不同',len([i for i in range(ca) if ea[i][0]!=eb[i][0]]),
      '长变化',len([i for i in range(ca) if len(ea[i][1] or b'')!=len(eb[i][1] or b'')]))
"
```

验证要点：
- 建造菜单里 `Inn` 应显示「酒館」（不是「酒」）
- 调出「游戏进行时间」界面 → 日志出现 `[asc]` 行 → 看 `FIRST/LAST` 是否覆盖 `0x30`
- 战役能正常跑完（验证 EAST.EVT 对齐无副作用）

## 六、仓库约定（务必遵守）

- **助手禁止主动启动/唤起游戏**（用户明确要求），测试由用户手动进行并回报
- 提交消息用文件方式（`-F`），避免引号破坏 shell 解析
- 等长替换是本项目的核心安全手段：改名前后必须校验
  「文件长度 / 记录数 / 记录名 / 每条记录长度」四项
- 判定翻译状态要用**字段名白名单**扫描（见 `fix_bad_bytes.py` 头部说明）：
  - `*PTR` / `PAL_PTR` / `BITMAPPTR` 是二进制指针，不是字符串
  - `SPRITE.NAME` 全是内部 ID（`NO_CIV`/`CATAPULT`），**本就该保持英文**
  - 坏字节检测：cp950 解码是否出 `U+FFFD`，不要用「值 >= 0x80」判中文
- 打包路径用 Windows 形式（`C:/Users/HAOJUN~1/AppData/Local/Temp`），
  MSYS 的 `/tmp` 与 Python 看到的不是同一个路径

