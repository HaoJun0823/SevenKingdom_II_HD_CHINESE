# archives —— 一次性 / 孤立 / 可重建物归档

本目录存放**不再参与日常工作流**的东西。全部是「移动」过来而非删除，
还原方式只有一个：`python -c "import shutil; shutil.move(旧, 新)"` 或直接把子目录搬回原处。
明细清单见 `00_MANIFEST.txt`。

> 2026-10-05 一次性整理：132 个文件 / 147.6 MB，共 6 类。

## 01_build_artifacts（95 MB）—— 可重建，删了无所谓

| 原名 | 内容 | 怎么还原 |
|---|---|---|
| `.vs/` | VS IDE 缓存（92 MB） | 打开一次解决方案自动重建；已加 .gitignore |
| `build/` | cl.exe 编译出的 .obj + sk2_zh.asi（2.5 MB） | `cd tools && python build.py` 自动重建 |

## 02_ui_probe_assets（46 MB）—— 探测阶段截图

`tools/_shots/`、`tools/_nav/`、`tools/_crop/`、`tools/_render/`
：早期「自动探索游戏界面」阶段留下的 UI 定位截图（bmp + png 双份），
任务完成后就没人再用了。已加 .gitignore。

## 03_backups（6.6 MB）—— 旧回滚点

- `res_backup/` —— 早期 `fix_stdset*.py` 系列的手写备份目录。
  那批脚本本身也已归档（见 `05_oneoff_scripts/tools/`），新流程改用
  `records/*.bin.bak_*` 同名备份 + `/tmp` 快照，本目录不再被写入。
- `update_res_staged.bak_before_fix/` —— 上一轮修复前的部署快照，已被上面取代。

## 04_reports —— 一次性报告（**已入库 git**，可随时 `git show` 取回）

`pending_list.txt`、`racename_fix.txt`、`unpack_diff_report.txt/.json`
：10-05 那轮「167→107 处可见界面翻译」的盘点产物。
结论已落到 `README.md` 与 `tools/scan_pending.py` 的判定口径里。

## 06_internals —— 本地私有物（**不入 git**，还原只需搬回工程根）

| 原名 | 为什么归档 |
|---|---|
| `play.cmd` | 早期按 Stage 1/2 启动游戏的调试脚本，硬编码本机路径 `I:\LocalGames\Seven Kingdoms II HD`。对外没价值，且换台电脑就是错的 |
| `STATUS.md` | 会话内跨轮接手记账，满篇「状态不明 / 待用户实测」，属于跟人协作的临时标记，不是工程文档 |
| `update_README.txt` | 原 `update/README.txt`，写于「Stage 3 未实现、中文资源不敢投放」的时期；现已直接部署，说明已过时（新说明在根 `README.md`） |

这三项都**刻意不入库**：GitHub 上看不到，本地照样能搬回来用。

## 05_oneoff_scripts —— 一次性探针脚本（**已入库 git**）

32 个 `tools/*.py`，按用途分三组：

1. **UI 自动探索组**（`auto_play.py` `hover_test.py` `nav.py` `run_game.py`…）
   靠 `winctl` 驱动窗口自动点按钮截图，用于反推菜单文字。
   人工分析上线后即废弃。
2. **反汇编摸底组**（`find_vtable.py` `find_calls.py` `disasm_fn.py` `find_charset_users.py`…）
   拿 IDA/capstone 找文本渲染函数与字符集使用者，用于定位 hook 点。
3. **STD.SET 翻修过程脚本**（`fix_stdset.py` `fix_template.py` `fix_risky.py` `fix_stdset_binary.py`…）
   10-04～10-05 逐字段修 STD.SET 时的中间步骤，
   已被 `db_table.py` + `fix_names.py` / `fix_unit.py` / `fix_firm_names.py` /
   `fix_bad_bytes.py` / `fix_techclas.py` 这套主线工具取代。

**注意**：这些脚本会 `import fontlib / render_text / gen_stdmap` 等，
那些**共用模块仍留在 `tools/`**，只有脚本本身进这里。

## 保留在 `tools/` 的核心工具链（20 个 .py）

```
db_table.py  fontlib.py  zhcode.py          # 表解析 / 字体对 / 编码
fix_names.py  fix_unit.py  fix_firm_names.py  fix_bad_bytes.py  fix_techclas.py
scan_pending.py  align_evt_order.py  check_index.py  check_struct.py
render_text.py  winctl.py  gen_stdmap.py  gen_extra.py  build_gap.py
tut_zh.py  build.py  run_game.py
```

改名前那个长名字目录 `unpack_data_cht_from_original_cht_game_may_be`
已恢复为 `unpack_data_cht`（git 识别为 rename，内容零丢失，
顺带让 `tools/diff_unpack.py` 的依赖路径重新可用）。
