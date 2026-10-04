// dllmain.cpp — ASI 插件入口
//
// 阶段划分（每阶段可独立验证，出问题立刻停）：
//   Stage 1  仅定位 + 打印地址与字节，验证签名搜索是否命中
//   Stage 2  挂钩 text_width，双字节宽度
//   Stage 3  注入等效 FontInfo，实现实际渲染
//
// 当前默认 Stage 1：不挂钩任何函数，只把逆向结论打印到日志，
//                确认「签名能命中、地址正确、Font 偏移正确」后再放开。
#include "pch.h"
#include "core.h"
#include "fontwidth.h"
#include "hooks.h"
#include "cjk.h"
#include "diag.h"
#include <cstdlib>

using namespace sk2;

// 阶段由 ReadStage() 解析（环境变量或 update\stage.txt），见下。
void StartCallMonitor();   // 前置声明：Stage2 里调用

// -- 阶段 1：定位并打印，不打补丁 ----------------------------
static void Stage1_Locate() {
    Log("=====================================================\r\n");
    Log(" 7K2 HD CJK 注入 — Stage 1 定位自检\r\n");
    Log("=====================================================\r\n");

    uint8_t* base = Base();
    Log("[i] main module base = %p  (delta = 0x%X)\r\n", base, Delta());
    if (reinterpret_cast<uint32_t>(base) != 0x400000)
        Log("[!] ImageBase 非 0x400000，delta 已启用\r\n");

    // 四个核心签名
    struct Target { const char* name; const uint8_t* sig; int len; uint32_t expect; };
    const Target targets[] = {
        { "Font::text_width",    SIG_TEXT_WIDTH,      SIG_TEXT_WIDTH_LEN,      0x4C0780 },
        { "Font::put",           SIG_PUT,             SIG_PUT_LEN,             0x4C0AE0 },
        { "Font::put_paragraph", SIG_PUT_PARAGRAPH,   SIG_PUT_PARAGRAPH_LEN,   0x4C1480 },
        { "Font::center_put",    SIG_CENTER_PUT,      SIG_CENTER_PUT_LEN,      0x4C1140 },
    };

    Log("\r\n--- 签名搜索结果 ---\r\n");
    for (const auto& t : targets) {
        void* got = FindInText(t.sig, t.len);
        if (!got) {
            Log("[X] %-22s 签名未命中\r\n", t.name);
            continue;
        }
        uint32_t va = static_cast<uint32_t>(reinterpret_cast<uintptr_t>(got));
        int32_t diff = static_cast<int32_t>(va - t.expect);
        if (diff == 0)
            Log("[O] %-22s VA=%08X  与 IDA 记录一致\r\n", t.name, va);
        else
            Log("[~] %-22s VA=%08X  (IDA记录 %08X, 差 %+d)\r\n", t.name, va, t.expect, diff);
        LogBytes("      bytes", got, 16);
    }

    // 全局变量可达性检查
    // RVA 已含基址相对量，地址 = Base()+rva。校验用映像实际范围（不是首选 VA）。
    Log("\r\n--- 全局变量 (实际地址) ---\r\n");
    uint8_t* modBase = Base();
    uint8_t* imgEnd  = modBase + 0x0C00000;      // .reloc 结束，约 0xC00000
    struct GV { const char* name; uint32_t rva; int size; };
    const GV gvs[] = {
        { "screen_w",  RVA_SCREEN_W,     4 },
        { "screen_h",  RVA_SCREEN_H,     4 },
        { "win_flag",  RVA_WINDOW_FLAG,  1 },
        { "line_cnt",  RVA_LINE_COUNT,   4 },
    };
    for (const auto& g : gvs) {
        void* p = Rva(g.rva);
        uint8_t* up = static_cast<uint8_t*>(p);
        bool inRange = (up >= modBase && up + g.size <= imgEnd);
        int val = 0;
        if (inRange) memcpy(&val, p, g.size);
        uint32_t va = static_cast<uint32_t>(reinterpret_cast<uintptr_t>(p));
        Log("[%s] %-9s rva=%08X (IDA VA %08X) -> 实际 %08X = %d (0x%X)\r\n",
            inRange ? "i" : "X", g.name, g.rva, Vip(g.rva), va, val, val);
    }
    Log("[i] base = %08X  delta = 0x%X  映像范围 %08X-%08X\r\n",
        modBase, Delta(), modBase, imgEnd);

    // center_put 里对 text_width 的 call ——
    // 这是引擎自己调 text_width 的地方，可用于验证 hook 是否真的生效
    void* center = FindInText(SIG_CENTER_PUT, SIG_CENTER_PUT_LEN);
    void* tw     = FindInText(SIG_TEXT_WIDTH, SIG_TEXT_WIDTH_LEN);
    if (center) {
        uint8_t* p = static_cast<uint8_t*>(center);
        Log("\r\n--- center_put 内的 call 指令 ---\r\n");
        for (int off = 0x10; off < 0x80; ++off) {
            if (p[off] != 0xE8) continue;
            int32_t rel = 0;
            memcpy(&rel, p + off + 1, 4);
            void* target = p + off + 5 + rel;
            Log("[i] +0x%02X: call %08X%s\r\n", off,
                static_cast<uint32_t>(reinterpret_cast<uintptr_t>(target)),
                (target == tw) ? "   <= text_width (验证锚点)" : "");
        }
    }

    Log("\r\n--- Stage 1 完成，未打任何补丁 ---\r\n");
    Log("[!] 签名全部命中后，可设环境变量 SK2_STAGE=2 进入宽度挂钩\r\n");
}

// -- 阶段 2：挂钩 text_width --------------------------------
static void Stage2_TextWidth() {
    Log("\r\n=== Stage 2: text_width 双字节挂钩 ===\r\n");

    // 先离线自测：此时资源仍是英文，游戏里跑不到双字节分支，
    // 用假 Font 直接验证宽度算法，避免"看不出问题"就以为没问题。
    SelfTest();

    if (!InstallTextWidth()) {
        Log("[X] text_width 挂钩失败\r\n");
        return;
    }
    Log("[O] text_width 已挂钩\r\n");
    Log("[!] 资源仍为英文，排版可能有细微变化，属预期\r\n");
    Log("[i] 运行中若出现含高位字节的串，会打印 [dbg] tw#N 探针行\r\n");
    StartCallMonitor();   // 周期性输出调用计数，确定 hook 是否真的被调用
}

// -- 调用监控：证明 hook 是否真的在跑 ------------------------
// 背景：英文资源下探针不会触发，日志里「一片安静」无法区分
//       「hook 没生效」与「没有中文串」。故周期输出累计计数。
static void CallMonitorProc() {
    static bool started = false;
    if (started) return;
    started = true;
    for (int i = 1; i <= 24; ++i) {
        Sleep(5000);
        LONG n = TextWidthCallCount();
        LONG p = PutCallCount();
        LONG z = CjkGlyphCount();
        LONG v = VqCount();
        Log("[i] 监控 %2d 次 (每5秒): text_width=%ld  put=%ld  段落=%ld  单字=%ld  "
            "中文字形=%ld  VirtualQuery=%ld\r\n",
            i, n, p, ParagraphCallCount(), PutCharCallCount(), z, v);
        if (n > 0 && i >= 3) {
            Log("[O] hook 确认生效（已被游戏调用）\r\n");
            break;
        }
    }
}

void StartCallMonitor() {
    HANDLE t = CreateThread(nullptr, 0,
        [](LPVOID) -> DWORD { CallMonitorProc(); return 0; }, nullptr, 0, nullptr);
    if (t) CloseHandle(t);
}

// -- 阶段 3：中文渲染 ----------------------------------------
static void Stage3_FontInfo() {
    Log("\r\n=== Stage 3: 中文渲染 ===\r\n");

    // 先跑字形自测，确认字库与索引表可用
    CjkSelfTest();

    if (!InstallPut()) {
        Log("[X] Font::put 挂钩失败 —— 中文不会显示\r\n");
        return;
    }
    // 段落/简报/列表走的是 put_paragraph（它自己画字，不经过 Font::put），
    // 必须单独挂钩，否则这些区域仍是单字节乱码、且换行错位。
    if (!InstallParagraph())
        Log("[!] put_paragraph 未挂钩：段落类文本仍会乱码\r\n");
    // HD 教程提示走「逐字绘制」的 put_char，同样自己画字，需单独挂钩
    if (!InstallPutChar())
        Log("[!] put_char 未挂钩（教程提示类文本可能仍有叠字）\r\n");
    // 第 4 条路径：Font 里**不经过 put** 的逐字节 ASCII 绘制（悬浮提示/HUD）
    if (!InstallPutAscii())
        Log("[!] 逐字节绘制路径未挂钩（悬浮提示等可能仍乱码）\r\n");
    // 第 5 条路径：居中多行文本——原函数只在空格断行，中文会被 UI 截断
    if (!InstallTextWrap())
        Log("[!] 多行文本换行未挂钩（超宽中文不会自动折行）\r\n");
    // exe 内置 UI 标签（Change Display Mode / Full Screen Mode 等）运行时本地化
    PatchExeStrings();
    Log("[O] 中文渲染已就绪\r\n");
    Log("[!] 纯 ASCII 文本仍走原函数；含中文的串由本插件自绘\r\n");
    Log("[i] 若中文大小不合适，可在 update\\fontsize.txt 写 13 / 16 / 24 覆盖\r\n");
}

// 读阶段：优先环境变量，其次 modules\stage.txt / scripts\stage.txt，再其次 update\stage.txt
// ★ 关键：阶段标记**绝不能放在 update\ 里**。实测把 update\ 改名成 update2\（想临时停用资源）
//   会连 stage.txt 一起带走 → 阶段退回 1 → 所有 hook 都不装 → 那次运行变成了「伪原版」，
//   据此得出的「原版也崩 / 汉化才崩」结论全是错的（7K2.exe.37060.dmp 就是这个坑）。
// ★ 缺省 = 3（完整汉化）：加载了本插件却什么都不做，是最大的误导源。
//   想退出到「只定位不挂钩」，显式写 stage.txt = 1。
static DWORD ReadStage() {
    static const char* kFiles[] = {
        "modules\\stage.txt",   // modloader 标准约定
        "scripts\\stage.txt",   // 我们自己的位置
        "update\\stage.txt",    // 旧位置，保留兼容
    };
    char path[MAX_PATH] = {};
    GetModuleFileNameA(nullptr, path, MAX_PATH);
    char* slash = strrchr(path, '\\');
    if (slash) slash[1] = 0;
    const size_t dirlen = strlen(path);
    DWORD stage = 3;              // ★ 缺省 = 完整汉化（放最前面，避免分支里遗漏）

    // 1) 环境变量
    char buf[32] = {};
    DWORD n = GetEnvironmentVariableA("SK2_STAGE", buf, sizeof(buf));
    if (n > 0 && n < sizeof(buf)) {
        stage = (DWORD)strtoul(buf, nullptr, 10);
        Log("[i] stage 来自环境变量 = %lu\r\n", stage);
        return stage;
    }
    // 2) 依次找 stage.txt
    for (const char* rel : kFiles) {
        lstrcpyA(path + dirlen, rel);
        HANDLE f = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
                               nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (f == INVALID_HANDLE_VALUE) continue;
        char b[32] = {};
        DWORD r = 0;
        ReadFile(f, b, sizeof(b) - 1, &r, nullptr);
        CloseHandle(f);
        if (r > 0) {
            stage = (DWORD)strtoul(b, nullptr, 10);
            Log("[i] stage 来自 %s = %lu\r\n", rel, stage);
            return stage;
        }
    }
    Log("[i] 未找到 stage.txt（已查 modules/scripts/update），stage 缺省 = 3（完整汉化）\r\n");
    return stage;
}

static void Worker() {
    // 单例保护：modloader 会扫描 scripts\ 与 update\ 两处，
    // 若同名 asi 同时存在于两个目录会被加载两次 → 双份 Worker 并发打补丁、
    // 并发写同一个日志文件（日志交错错乱）。
    // 用命名互斥体确保只有一个实例真正干活。
    HANDLE once = CreateMutexA(nullptr, FALSE, "Global\\sk2_zh_asi_singleton_v1");
    if (once && GetLastError() == ERROR_ALREADY_EXISTS) {
        InitLog();
        Log("[!] 检测到本插件已有实例运行（重复加载），此实例跳过。\r\n");
        Log("[!] 请删除 scripts\\ 或 update\\ 其中一份 sk2_zh.asi。\r\n");
        CloseLog();
        return;
    }

    InitLog();
    DWORD stage = ReadStage();
    Log("\r\n\r\n########## 启动 ##########\r\n");
    Log("[i] 本文件编译于 %s %s（注意：下面每段启动的时间戳才是运行时刻）\r\n",
        __DATE__, __TIME__);
    {
        SYSTEMTIME st{};
        GetLocalTime(&st);
        Log("[i] === 本次运行开始 %04d-%02d-%02d %02d:%02d:%02d ===\r\n",
            st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond);
    }
    Log("[i] log    = %s\r\n", LogPath());
    Log("[i] stage  = %lu\r\n", stage);

    Stage1_Locate();                                  // 阶段 1 总是执行
    if (stage >= 2) Stage2_TextWidth();
    if (stage >= 3) Stage3_FontInfo();

    Log("\r\n########## 安装阶段完成 ##########\r\n");
    if (stage == 1)
        Log("[i] 本次为 Stage 1：只定位自检，**未打任何补丁**，画面无变化是正常的。\r\n");

    // ★ 绝不能在这里 CloseLog()！
    // 之前在这里关掉日志，导致之后 hook 里的所有输出
    // （Font 转储 / 调用追踪 / 探针）都写进了已关闭的句柄而被丢弃，
    // 表现为「日志里一片安静」，误判为 hook 没生效。
    // 日志保持打开直到进程退出（DLL_PROCESS_DETACH 时再关）。
    Log("[i] 日志保持打开，后续 hook 输出将继续追加到本文件。\r\n");

    // 周期性把缺字形统计刷到日志 —— 即使之后崩溃（来不及走 DETACH）也留有证据。
    DiagStartFlusher();
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD reason, LPVOID reserved) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(hModule);
        // ASI loader 在主程序早期加载。用独立线程延后，确保 .text 与全局变量就绪，
        // 同时避开 loader lock（不能在 DllMain 里做重活）。
        HANDLE t = CreateThread(nullptr, 0,
            [](LPVOID) -> DWORD { Worker(); return 0; }, nullptr, 0, nullptr);
        if (t) CloseHandle(t);
    } else if (reason == DLL_PROCESS_DETACH) {
        // 缺字形汇总必须在 CloseLog 之前
        DiagDumpMissing();
        CloseLog();
    }
    return TRUE;
}
