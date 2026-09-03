# -*- coding: utf-8 -*-
"""EPUB 美化工具

对指定书籍的 EPUB 格式执行无损美化（目录样式 / 章节名样式 / 字体排版），
以「生成新书」模式入库，原书零改动：

- **目录**：书内已有目录页则注入统一样式；无目录页时从 NCX/nav 生成
  ``mb-toc.xhtml`` 目录页并注册进 OPF（spine 首条）；
- **章节名**：三层识别章节标题（h1-h6 / 已知标题类 / 段落文本章节正则，
  正则移植自 hehetoshang/txt2epub-next，MIT），标记 ``mb-ch`` 统一样式
  （居中、分页、标题字体、留白），章首段顶格；
- **字体**：注入 ``mb-beauty.css`` 覆盖层，正文/标题/引文三档系统字体栈
  （不嵌入字体文件），可选「保留原书字体」。

对外接口：
- :meth:`preview` 同步返回分析结果 + 可用预设列表；
- :meth:`run` 后台执行美化并入库。

@author: 黏菌, 2026
"""
import logging
import os
import threading
import time
import traceback
from typing import Optional

from webserver.i18n import _
from webserver.services import AsyncService
from webserver.services.background_service import BackgroundService, BackgroundTask
from webserver.toolbox.base_tool import BaseTool

from webserver.toolbox.utils import book_utils
from webserver.toolbox.utils import epub_beautify_lib
from webserver.toolbox.utils.styles import get_preset_css, list_presets, list_toc_styles


class EpubBeautifyTool(BaseTool):
    """对指定书籍的 EPUB 执行美化并生成新书。"""

    service_item_name = "EPUB美化"

    _run_lock = threading.Lock()
    _last_task_id: Optional[int] = None

    @classmethod
    def is_running(cls) -> bool:
        task = cls.get_last_task()
        return bool(task and task.get("status") == BackgroundTask.STATUS_RUNNING)

    @classmethod
    def get_last_task(cls) -> Optional[dict]:
        if cls._last_task_id is None:
            return None
        return BackgroundService().get_task(cls._last_task_id)

    # ------------------------------------------------------------ 背景图片

    _BG_NAME = 'bg_custom.jpg'
    _BG_MAX_BYTES = 3 * 1024 * 1024
    _BG_ALLOWED_EXT = ('.jpg', '.jpeg', '.png', '.webp')

    def bg_image_path(self) -> str:
        """已上传背景图（工具根目录，全局复用）。"""
        return os.path.join(self.get_work_dir(), self._BG_NAME)

    def save_bg_image(self, data: bytes, filename: str, builtin_id: str = '') -> dict:
        """保存全书背景图：PIL 统一重编码为 JPEG（宽>1080 等比缩小）。

        :param builtin_id: 非空时忽略 data/filename，改用内置纹理。
        :raises ValueError: 格式/大小不合法或纹理 id 非法。
        """
        if builtin_id:
            from webserver.toolbox.utils.styles import get_texture_bytes
            data, _mt = get_texture_bytes(builtin_id)
        else:
            ext = os.path.splitext(filename or '')[1].lower()
            if ext not in self._BG_ALLOWED_EXT:
                raise ValueError(_('背景图仅支持 jpg / png / webp 格式'))
            if len(data) > self._BG_MAX_BYTES:
                raise ValueError(_('背景图不能超过 3MB'))
        try:
            from PIL import Image
        except ImportError as err:
            raise RuntimeError(_('服务器缺少图像处理组件(PIL)，无法处理背景图')) from err
        import io as _io
        img = Image.open(_io.BytesIO(data)).convert('RGB')
        w, h = img.size
        target_w = 1080
        if w > target_w:
            img = img.resize((target_w, max(1, int(h * target_w / w))), Image.LANCZOS)
            w, h = img.size
        buf = _io.BytesIO()
        img.save(buf, 'JPEG', quality=85, optimize=True)
        out = self.bg_image_path()
        os.makedirs(os.path.dirname(out), exist_ok=True)
        payload = buf.getvalue()
        with open(out, 'wb') as f:
            f.write(payload)
        return {'bytes': len(payload), 'width': w, 'height': h}

    def delete_bg_image(self) -> bool:
        p = self.bg_image_path()
        if os.path.exists(p):
            os.remove(p)
            return True
        return False

    def has_bg_image(self) -> bool:
        return os.path.exists(self.bg_image_path())

    @staticmethod
    def info() -> dict:
        return {
            "tool_id": "epub_beautify",
            "name": "EPUB美化",
            "description": "美化 EPUB 的目录、章节名与字体排版（12 套风格预设 × 4 种目录形式，含竖排右翻古籍；卷章分级、双行排版、对话行点缀；支持批量队列与全书底色/自定义配色），生成新书",
            "revision": "0.1.0",
            "author": "黏菌",
            "publish_date": "2026-08-22",
        }

    # ------------------------------------------------------------ 预览（同步）

    # 预设卡片可视化所需的色板字段（presets.json 元数据直通）
    _PRESET_PALETTE_KEYS = (
        "scene", "line_height", "title_size",
        "accent", "accent_light", "accent_dark", "muted", "border",
        "quote_bg", "code_bg", "toc_gradient", "page_progression",
    )

    @AsyncService.register_function
    def preview(self, book_id: int) -> dict:
        """同步返回书籍分析 + 预设列表。

        :param book_id: Calibre 书籍 ID。
        :return dict: ``analysis``（目录形态/标题统计/字体现状）与 ``presets``。
        :raises RuntimeError: 书籍不存在 / 无 EPUB / 文件缺失。
        """
        epub_path = book_utils.get_book_file(self, book_id, "EPUB")
        analysis = epub_beautify_lib.analyze_epub(epub_path)
        presets = []
        for pid, meta in list_presets().items():
            item = {
                "id": pid,
                "name": meta.get("name", pid),
                "name_en": meta.get("name_en", pid),
                "description": meta.get("description", ""),
            }
            for key in self._PRESET_PALETTE_KEYS:
                if key in meta:
                    item[key] = meta[key]
            presets.append(item)
        return {"analysis": analysis, "presets": presets, "toc_styles": list_toc_styles()}

    # ------------------------------------------------------------- 后台执行

    @staticmethod
    def _normalize_font_overrides(use_system_fonts: bool, font_overrides) -> Optional[dict]:
        """归一化字体子开关：兼容旧 use_system_fonts 布尔与新细粒度 dict。"""
        if isinstance(font_overrides, dict):
            # 仅保留合法键，缺省回落到 use_system_fonts
            norm = {}
            for k in ("body", "head", "kai", "code"):
                if k in font_overrides:
                    norm[k] = bool(font_overrides[k])
                else:
                    norm[k] = bool(use_system_fonts)
            return norm
        if use_system_fonts is None:
            return None
        return {
            "body": bool(use_system_fonts),
            "head": bool(use_system_fonts),
            "kai": bool(use_system_fonts),
            "code": bool(use_system_fonts),
        }

    @AsyncService.register_service
    def run(self, preset: str, use_system_fonts: bool,
            toc_style: str, suffix: str, user_id: int,
            book_ids=None, book_id: Optional[int] = None,
            font_overrides: Optional[dict] = None,
            toc_depth: Optional[int] = None,
            cleanup: Optional[dict] = None,
            palette_overrides: Optional[dict] = None,
            page_tint: Optional[bool] = None,
            dialogue: Optional[bool] = None,
            title_split: Optional[bool] = None,
            bg_image: Optional[bool] = None,
            toc_columns: Optional[bool] = None,
            para_mode: Optional[str] = None,
            para_indent: Optional[bool] = None,
            para_gap=None,
            notes: Optional[bool] = None,
            note_mark: Optional[str] = None) -> None:
        """后台执行美化并生成新书（支持批量队列）。

        :param book_ids:         批量书籍 ID 列表（去重后按序执行，不限本数）。
        :param book_id:          单本书 ID（兼容旧接口；与 book_ids 二选一）。
        :param preset:           预设 id（classic/modern/webnovel/classical/navy/youth/children/refined/xuanzhi/inkstone/voyage/vertclassical）。
        :param use_system_fonts: 是否统一系统字体栈（False 保留原书字体，兼容旧接口）。
        :param toc_style:        目录形式（elegant 精致 / cool 酷炫 / seal 朱印 / minimal 极简），配色随预设令牌。
        :param suffix:           新书标题后缀（默认「（美化版）」）。
        :param user_id:          操作用户 ID。
        :param font_overrides:   细粒度字体开关 {"body":bool,"head":bool,"kai":bool,"code":bool}，覆盖 use_system_fonts。
        :param toc_depth:        目录收录层级上限（None=全部；1/2/3=只收前 N 级）。
        :param cleanup:          内容清理开关 {"leading":bool,"empty":bool,"meta":bool,"toc_blank":bool}，
                                 默认 段首空格归一开 / 空段清理关 / 冗余 meta 移除开 / 目录空白条目净化开。
        :param palette_overrides: 自定义配色 {token: hex}（accent/accent_light 等，非法值抛 ValueError；
                                 覆盖 accent 时自动派生夜间色与目录渐变）。
        :param page_tint:        全书主题底色三态：True=纸色铺满 / False=阅读器默认 / None=跟随预设。
        :param dialogue:         对话行点缀开关（True=为「『“起始段落打 mb-dialog，
                                 样式由预设令牌驱动：楷体/米底/主题色竖线）。默认关闭。
        :param title_split:      双行排版开关（True=纯文本章题拆为章节号小字 + 标题大字）。默认关闭。
        :param bg_image:         背景图片开关（True=把已上传的背景图写入包内并铺满；
                                 激活时接管 page_tint 的底色语义，夜间自动压暗保可读）。默认关闭。
        :param para_mode:        【兼容旧参数】indent/spacing；spacing 等价于
                                 para_indent=False。新代码请用下面两个。
        :param toc_columns:      目录双栏开关（True=生成的目录页宽屏双栏排布）。默认关闭。
        :param para_indent:      首行缩进开关（True=缩进制默认 / False=全部顶格），
                                 独立于段距。
        :param para_gap:         段间距数值（em，0=跟随预设，范围 [0,3]，非法值抛错），
                                 可与任意缩进组合。
        :param notes:            弹注/标注美化开关（标注符随预设着色、注释卡样式、
                                 B 型掌书系书自动补齐 EPUB3 弹注语义）。默认关。
        :param note_mark:        标注样式：orig 原图标（默认）/ sym ※ / num [n] /
                                 svg:<dot|fold|inkdrop|spark|sealdot> 自绘图形（随主题染色）。

        批量语义：单本失败不断批，逐本汇总结果；进度按书数折算
        （progress_data 携带 book_index/book_total/current_title）。
        预设元数据含 ``page_progression`` 时（如 vertclassical 竖排古籍 = rtl），
        自动把 spine 设为对应翻页方向。
        """
        raw = list(book_ids) if book_ids else ([book_id] if book_id else [])
        try:
            ids = [int(b) for b in raw]
        except (TypeError, ValueError):
            ids = []
        ids = list(dict.fromkeys(ids))
        total = len(ids)

        if not total:
            # 校验放在抢锁之前：避免拿到锁后提前 return 却忘记 release，把锁永久卡死
            skip_task_id = self.create_task(progress_data={"status": "failed"})
            self.complete_task(skip_task_id, error_message=_("未提供有效的书籍 ID"))
            # P3：仅在无在跑任务可轮询时才落 skip id，避免覆盖在跑任务的轮询句柄
            if not EpubBeautifyTool.is_running():
                EpubBeautifyTool._last_task_id = skip_task_id
            return
        acquired = EpubBeautifyTool._run_lock.acquire(blocking=False)
        if not acquired:
            # 静默跳过会让前端永远轮询不到任务（卡"处理中"），落一条失败任务；
            # P3：仅在无在跑任务可轮询时才落 skip id（同上，防覆盖）
            skip_task_id = self.create_task(progress_data={"status": "failed", "book_ids": ids})
            self.complete_task(
                skip_task_id,
                error_message=_("已有美化任务正在运行，请等待完成后再试"),
            )
            if not EpubBeautifyTool.is_running():
                EpubBeautifyTool._last_task_id = skip_task_id
            logging.warning(
                "[EpubBeautifyTool] Already running, skipping run for ids=%s [uid:%d]",
                ids, user_id,
            )
            return

        task_id = None
        error_message = None
        ok_count = 0
        fail_count = 0
        last_new_book_id = None
        results = []

        try:
            task_id = self.create_task(
                progress_data={"status": "starting", "book_ids": ids, "book_total": total})
            EpubBeautifyTool._last_task_id = task_id

            # 参数校验一次（与具体书籍无关）：预设 / 目录形式 / 配色 / 字体开关
            try:
                if para_mode not in (None, "", "indent", "spacing"):
                    raise ValueError("unknown para_mode: %s" % para_mode)
                # 段落排版：新参数优先；旧 para_mode="spacing" 映射为关缩进
                eff_indent = para_indent
                if eff_indent is None and para_mode == "spacing":
                    eff_indent = False
                overrides = self._normalize_font_overrides(use_system_fonts, font_overrides)
                preset_css = get_preset_css(
                    preset, use_system_fonts, toc_style, overrides,
                    palette_overrides=palette_overrides,
                    page_tint=(None if bg_image else page_tint),
                    bg_image=({'url': 'mb-bg.jpg'} if bg_image else None),
                    para_indent=(True if eff_indent is None else eff_indent),
                    para_gap=para_gap,
                    toc_columns=bool(toc_columns),
                )
            except ValueError as err:
                error_message = _("参数不合法（预设/目录形式/配色/段距/弹注）：%s") % err
                logging.error("[EpubBeautifyTool] Bad params %r/%r [uid:%d]", preset, toc_style, user_id)
                return
            if notes:
                try:
                    epub_beautify_lib._validate_note_mark(note_mark or 'orig')
                except ValueError as err:
                    error_message = _("标注样式不合法：%s") % err
                    logging.error("[EpubBeautifyTool] Bad note_mark %r [uid:%d]", note_mark, user_id)
                    return

            # 竖排等预设可声明翻页方向（page_progression: rtl）
            page_progression = (list_presets().get(preset) or {}).get("page_progression") or None

            # 背景图：读一次全局缓存图；激活时接管底色三态
            extra_assets = None
            if bg_image:
                bp = self.bg_image_path()
                if not os.path.exists(bp):
                    raise RuntimeError(_('未找到已上传的背景图片，请先上传或选择内置纹理'))
                with open(bp, 'rb') as f:
                    extra_assets = {'mb-bg.jpg': (f.read(), 'image/jpeg')}

            for idx, bid in enumerate(ids):
                base = idx * 100.0 / total

                def _pct(book_pct):
                    return int(min(99, (base + book_pct / total)))

                book_title = "Unknown"
                work_dir = None
                try:
                    books = self.api.calibre.get_data_as_dict([bid])
                    if not books:
                        raise RuntimeError(_("书籍不存在：ID=%d") % bid)
                    book_title = books[0].get("title", "Unknown")
                    epub_path = book_utils.get_book_file(self, bid, "EPUB")

                    prog_common = {
                        "status": "running", "book_index": idx + 1,
                        "book_total": total, "current_title": book_title,
                        "book_id": bid,
                    }
                    self.update_task_progress(task_id, _pct(10), dict(prog_common, stage="analyzing"))

                    work_dir = self.get_work_dir(str(bid))
                    out_path = os.path.join(work_dir, "beautified_%d.epub" % int(time.time()))

                    self.update_task_progress(task_id, _pct(30), dict(prog_common, stage="processing"))

                    stats = epub_beautify_lib.beautify(
                        epub_path, out_path, preset_css,
                        toc_style=toc_style, page_progression=page_progression,
                        toc_depth=toc_depth, cleanup=cleanup,
                        dialogue=bool(dialogue), split_title=bool(title_split),
                        extra_assets=extra_assets,
                        notes=bool(notes), note_mark=(note_mark or 'orig'),
                    )

                    self.update_task_progress(task_id, _pct(80), dict(prog_common, stage="saving"))

                    new_book_id = book_utils.import_as_new_book(
                        self, bid, out_path, suffix or _("（美化版）"), user_id,
                    )
                    last_new_book_id = new_book_id
                    ok_count += 1
                    results.append({"book_id": bid, "ok": True, "new_book_id": new_book_id})

                    self.update_task_progress(
                        task_id, _pct(95),
                        dict(prog_common, stage="saving", new_book_id=new_book_id),
                    )
                    logging.info(
                        "[EpubBeautifyTool] Beautified book_id=%d (headers=%d, vols=%d, splits=%d, toc=%s, rtl=%s, dialogs=%d, notes=%s/%s) -> new book_id=%d [uid:%d]",
                        bid, stats.get("marked_headers", 0), stats.get("marked_volumes", 0),
                        stats.get("titles_split", 0), stats.get("toc_generated"),
                        stats.get("page_progression") or "-", stats.get("dialogues_marked", 0),
                        stats.get("notes_refs", 0), stats.get("note_mark") or "-",
                        new_book_id, user_id,
                    )
                    self.cleanup_work_dir(work_dir)

                    self.add_msg(
                        user_id, "success",
                        _(u"书籍 [%s] 美化成功！已生成新书（章节标题 %d 处，目录页 %s）")
                        % (book_title, stats.get("marked_headers", 0),
                           _("已生成") if stats.get("toc_generated") else _("保留原样")),
                    )
                except Exception as err:
                    fail_count += 1
                    results.append({"book_id": bid, "ok": False, "error": str(err)})
                    self.add_msg(user_id, "danger", _(u"书籍 [%s] 美化失败！") % book_title)
                    logging.error("[EpubBeautifyTool] Failed for book_id=%d: %s", bid, err)
                    logging.error(traceback.format_exc())
                    if work_dir is not None:
                        # 失败时清理本次已生成的中间文件，避免同一本书反复重试时
                        # 在工作目录下堆积多份带时间戳的 beautified_*.epub 残留
                        self.cleanup_work_dir(work_dir)

            if fail_count and not ok_count:
                error_message = _("批量美化全部失败（共 %d 本）") % fail_count
            elif total > 1:
                self.add_msg(
                    user_id, "success" if not fail_count else "warning",
                    _(u"批量美化完成：成功 %d 本，失败 %d 本。") % (ok_count, fail_count),
                )

        except Exception as err:
            error_message = str(err)
            logging.error("[EpubBeautifyTool] Unexpected error [uid:%d]: %s", user_id, err)
            logging.error(traceback.format_exc())
        finally:
            if task_id is not None:
                # 完成前先更新最终进度（complete 会固化状态）
                if error_message is None:
                    self.update_task_progress(
                        task_id, 100,
                        {"status": "completed", "book_ids": ids, "book_total": total,
                         "book_id": ids[0], "new_book_id": last_new_book_id,
                         "results": results},
                    )
                self.complete_task(task_id, error_message=error_message)
            # P4：locked() 恒真会掩盖误释放——只在本次确曾抢到锁时释放
            if acquired:
                EpubBeautifyTool._run_lock.release()
