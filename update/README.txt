此目录用于 modloader 的 OverloadFromFolder（资源覆盖）。
中文资源暂不放入 —— 渲染器（Stage 3）尚未实现，
提前放入会导致 Big5 字节被引擎当单字节 glyph 查找，显示为乱码。

资源请放在工程根的 update_res_staged/ 下，
待 Stage 3 通过后再 deploy.cmd 投放。
