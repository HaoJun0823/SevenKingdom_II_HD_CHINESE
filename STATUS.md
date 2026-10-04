# 当前状态标记（2026-10-05 04:25）

> 本文件用于跨会话接手。**状态不明 = 未经用户实测验证的改动。**

## 一、待用户验证（状态不明）

### 1. FIRM/FIRM2 建筑名修复 20 处 —— 状态不明
- 改动：`tools/fix_firm_names.py` 等长替换，已写入 `unpack_data_chs`
- **已打包但未部署**：`update\Resource\STD.SET` 仍是我打包前的旧版
  （打包产物在 `%TEMP%\sk2_out2\STD.SET`，1322443B）
- 阻塞原因：部署时游戏进程 PID 13600 占用文件
- 预期效果：`Inn` 显示为「酒館」而非「酒」；`神壇 of Power` → `神壇` 等 4 处残留英文消失
- 风险：低（等长替换，结构校验 0 变化）
- 回退：`update\Resource\STD.SET` 换回任一 `.bak`

### 2. 逐字符诊断 `seg=2` —— 状态不明
- 改动：`cjk.cpp` 新增 `g_asciiDiag`，段落绘制遍逐字符打点
- 编译通过：1305088 字节，**只更新了仓库副本** `scripts\sk2_zh.asi`
- **`scripts\sk2_zh.asi`（游戏目录）仍是旧版 1304576**
- `update\render.ini` 已切到 `seg=2`
- 目的：定位「游戏进行时间」的数字为什么不显示
- 风险：零（纯诊断，`g_asciiDiag` 默认关，且 render.ini 才知道）

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

### 4. x64dbg MCP 反复掉线（本轮再次确认）
工具索引里已查不到任何 x64dbg 工具（此前可用的
`debug_get_state` / `debug_pause` / `register_get_batch` 全部消失）。
自动取证功能已替代其作用，且不受系统卡顿影响 —— 无需再依赖它。

## 三、已确认修复（有依据、无需重查）

| 项 | 提交 | 状态 |
|---|---|---|
| STD.SET 建筑名漏译 + 残留（179 处） | `2bf52b8` | 已部署，用户测过建造菜单 |
| diff 工具假阳性修正（空记录/控制符） | `2bf52b8` | 已验证 |
| EAST.EVT / EAST.PLT 顺序对齐 | `16290f8` | **已部署，待用户跑战役验证** |
| STD.SET 表解析器 `db_table.py` | `89ba86b` | 工具 |

**EAST.EVT 对齐的性质**：原先报「49 处结构损坏」是**误报**。
residx 索引项只有「9 字节名 + 4 字节偏移」，无序号字段，引擎按名字查找
（源码 `res_event.read("11A")`），顺序不影响取数据。对齐纯粹是消除 diff 误报、
便于日后校对，记录内容逐字节未变。

## 四、已知未做（待用户决定）

### UNIT 表 31 条可见单位名未翻译
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

## 五、接手步骤

```bash
cd /g/Projects/SavenKingdom_II_HD_CHINESE

# 1. 先备份游戏当前 update 资源
cp -r "I:/LocalGames/Seven Kingdoms II HD/update" /tmp/update_before_next

# 2. 部署 FIRM 修复（重新打包即可，勿用旧的 %TEMP% 产物）
cd tools_packer && python pack.py \
  "../unpack_data_chs/Resource/STD.SET.unpacked" "/tmp/STD.SET.firm"
cp /tmp/STD.SET.firm "I:/LocalGames/Seven Kingdoms II HD/update/Resource/STD.SET"

# 3. 部署新 ASI
cp ../SavenKingdom_II_HD_CHINESE/objs/sk2_zh.asi \
   "I:/LocalGames/Seven Kingdoms II HD/scripts/sk2_zh.asi"

# 4. 确认 render.ini 为 seg=2
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
- 判定翻译状态要用**字段级**扫描（`db_table.py`），
  整表 cp950 可解码会把含二进制字段的表整表跳过 → 假阴性
