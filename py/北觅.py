# -*- coding: utf-8 -*-
"""
北觅影视 - v.luttt.com
参考「歪比巴卜」写法适配的 TVBox/FongMi 站点源插件。

站点特征（与 wbbb1.com 不同，已按实测调整）：
1. MacCMS 10 + Conch(海螺) 模板，URL 体系：/vodtype/ /vodshow/ /voddetail/ /vodplay/ /vodsearch/
2. 无搜索验证码、无滑动验证、无服务端 cookie 预热，普通请求即可访问（保留轻量限速与重试）。
3. 播放页 player_aaaa 直接给出 encrypt=0 的真实 m3u8 直链，无需解析域名 API / RC4 / AES 解密。
4. 筛选 URL 为 12 段结构：{tid}-{地区}-{排序}-{空}-{语言}-{字母}-{空}-{空}-{页码}-{空}-{空}-{年份}
5. 声明 searchable/quickSearch/filterable/changeable，支持壳子聚合换源；清洗片名后缀提升匹配度。
"""
import re
import json
import base64
import time
import urllib.parse
import requests
from urllib.parse import quote
from base.spider import Spider

class Spider(Spider):
    # ==================== 基础配置 ====================
    name = "北觅影视"
    base_url = "https://v.luttt.com"
    site_url = "https://v.luttt.com"

    # 聚合搜索配置
    searchable = 1
    quickSearch = 1
    filterable = 1
    changeable = 1

    # ==================== 请求头 ====================
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://v.luttt.com/",
        "Connection": "keep-alive",
    }

    play_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://v.luttt.com/",
        "Accept": "*/*",
    }

    # ==================== 分类（导航实测） ====================
    CATEGORY_NAMES = {
        "1": "电影",
        "2": "连续剧",
        "3": "综艺",
        "4": "动漫",
        "20": "纪录片",
        "35": "动画片",
    }

    def __init__(self):
        super().__init__()
        self._session = requests.Session()
        self._session.headers.update(self.headers)
        self._cookies = ""
        self._play_cache = {}
        self._cache_ttl = 1800
        # 请求间隔控制（站点无明显风控，但保留轻度限速）
        self._last_req_time = 0
        self._min_req_interval = 0.6
        # 搜索限速：站点提示"搜索时间间隔为3秒"，超频会返回系统提示页
        self._last_search_time = 0
        self._search_interval = 3.5
        # 预编译正则
        self._re_vplay_link = re.compile(
            r'<a[^>]*href="/vodplay/(\d+)-(\d+)-(\d+)\.html"[^>]*>(?:<[^>]+>)*([^<]*)</a>'
        )
        self._re_name_garbage = re.compile(
            r'[\s\-_]*(?:HD|TC|TS|抢先版|枪版|DVD|BD|1080P|720P|4K|2K|高清|超清|蓝光|国语|粤语|中字|中英双字|完整版|全集|未删减版|(?:第[0-9一二三四五六七八九十]+[集季期]))\s*$',
            re.I
        )

    # ==================== 通用工具 ====================
    def _log(self, msg):
        print(f"[{self.name}] {msg}")

    def _clean_vod_name(self, name):
        """清洗片名，去掉清晰度/版本/集数后缀，方便聚合搜索匹配"""
        if not name:
            return name
        prev = name
        while True:
            cleaned = self._re_name_garbage.sub('', prev).strip()
            if cleaned == prev:
                break
            prev = cleaned
        return prev

    def _clean_html(self, text):
        if not text:
            return ""
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _quote_filter_value(self, v):
        """筛选值统一编码，已编码的不二次编码"""
        if not v:
            return ""
        try:
            return quote(urllib.parse.unquote(str(v)))
        except Exception:
            return quote(str(v))

    # ==================== 请求封装 ====================
    def fetch(self, url, headers=None, timeout=15):
        self._apply_req_delay()
        return self._session.get(url, headers=headers or {}, timeout=timeout)

    def _apply_req_delay(self):
        now = time.time()
        elapsed = now - self._last_req_time
        if 0 < elapsed < self._min_req_interval:
            time.sleep(self._min_req_interval - elapsed)
        self._last_req_time = time.time()

    def _extract_cookies(self, resp):
        """从响应提取 Set-Cookie 并入会话"""
        cookie_list = []
        try:
            if hasattr(resp, 'cookies') and resp.cookies:
                for c in resp.cookies:
                    cookie_list.append(f"{c.name}={c.value}")
        except Exception:
            pass
        try:
            if "Set-Cookie" in resp.headers:
                raw = resp.headers["Set-Cookie"]
                if isinstance(raw, list):
                    for c in raw:
                        cookie_list.append(c.split(";")[0])
                else:
                    cookie_list.append(raw.split(";")[0])
        except Exception:
            pass
        if cookie_list:
            existing = {k.strip(): v for k, v in [x.split('=', 1) for x in self._cookies.split('; ') if '=' in x]}
            for c in cookie_list:
                if '=' in c:
                    k, v = c.split('=', 1)
                    existing[k.strip()] = v
            self._cookies = "; ".join(f"{k}={v}" for k, v in existing.items())

    def _is_blocked_page(self, html):
        """轻量封禁/异常页检测（含站点搜索频率限制提示页）"""
        if not html:
            return True
        markers = ('You are being rate limited', 'Error 1015', 'cf-error-details',
                   'Access denied |', '404 Not Found', '请不要频繁操作')
        return any(m in html for m in markers)

    def _get(self, url, max_retry=3, timeout=12):
        """GET 封装：异常捕获 + 重试 + 会话 Cookie"""
        h = self.headers.copy()
        for attempt in range(max_retry):
            try:
                resp = self.fetch(url, headers=h, timeout=timeout)
                self._extract_cookies(resp)
                html = resp.text
                if self._is_blocked_page(html) and attempt < max_retry - 1:
                    # 频率限制提示页需要等待更久（站点要求搜索间隔3秒）
                    wait = self._search_interval if '请不要频繁操作' in html else 1 + attempt
                    self._log(f"第{attempt+1}次请求被限速/拦截，等待{wait:.1f}s后重试: {url}")
                    time.sleep(wait)
                    continue
                return html
            except Exception as e:
                self._log(f"请求失败: {url}, {e}")
                if attempt < max_retry - 1:
                    time.sleep(1 + attempt)
                    continue
        return ""

    # ==================== 筛选器配置（段位：1地区 2排序 4语言 5字母 8页码 11年份） ====================
    # 注：该站筛选页不参与分页（带筛选的 URL 直接返回全部匹配）；"0-9"字母链接在站点自身也失效，字母仅保留 A-Z
    _LETTERS = [{"n": c, "v": c} for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
    _YEARS = [{"n": str(y), "v": str(y)} for y in range(2026, 2014, -1)]

    FILTERS = {
        "1": [
            {"key": "area", "name": "地区", "value": [{"n": "全部", "v": ""}, {"n": "大陆", "v": "大陆"}, {"n": "香港", "v": "香港"}, {"n": "台湾", "v": "台湾"}, {"n": "美国", "v": "美国"}, {"n": "法国", "v": "法国"}, {"n": "英国", "v": "英国"}, {"n": "日本", "v": "日本"}, {"n": "韩国", "v": "韩国"}, {"n": "德国", "v": "德国"}, {"n": "泰国", "v": "泰国"}, {"n": "印度", "v": "印度"}, {"n": "意大利", "v": "意大利"}, {"n": "西班牙", "v": "西班牙"}, {"n": "加拿大", "v": "加拿大"}, {"n": "其他", "v": "其他"}]},
            {"key": "by", "name": "排序", "value": [{"n": "最新", "v": "time"}, {"n": "最热", "v": "hits"}, {"n": "好评", "v": "score"}]},
            {"key": "lang", "name": "语言", "value": [{"n": "全部", "v": ""}, {"n": "国语", "v": "国语"}, {"n": "英语", "v": "英语"}, {"n": "粤语", "v": "粤语"}, {"n": "闽南语", "v": "闽南语"}, {"n": "韩语", "v": "韩语"}, {"n": "日语", "v": "日语"}, {"n": "法语", "v": "法语"}, {"n": "德语", "v": "德语"}, {"n": "其它", "v": "其它"}]},
            {"key": "letter", "name": "字母", "value": [{"n": "全部", "v": ""}] + _LETTERS},
            {"key": "year", "name": "年份", "value": [{"n": "全部", "v": ""}] + _YEARS},
        ],
        "2": [
            {"key": "area", "name": "地区", "value": [{"n": "全部", "v": ""}, {"n": "内地", "v": "内地"}, {"n": "香港", "v": "香港"}, {"n": "台湾", "v": "台湾"}, {"n": "韩国", "v": "韩国"}, {"n": "日本", "v": "日本"}, {"n": "美国", "v": "美国"}, {"n": "泰国", "v": "泰国"}, {"n": "英国", "v": "英国"}, {"n": "新加坡", "v": "新加坡"}, {"n": "其他", "v": "其他"}]},
            {"key": "by", "name": "排序", "value": [{"n": "最新", "v": "time"}, {"n": "最热", "v": "hits"}, {"n": "好评", "v": "score"}]},
            {"key": "lang", "name": "语言", "value": [{"n": "全部", "v": ""}, {"n": "国语", "v": "国语"}, {"n": "英语", "v": "英语"}, {"n": "粤语", "v": "粤语"}, {"n": "闽南语", "v": "闽南语"}, {"n": "韩语", "v": "韩语"}, {"n": "日语", "v": "日语"}, {"n": "其它", "v": "其它"}]},
            {"key": "letter", "name": "字母", "value": [{"n": "全部", "v": ""}] + _LETTERS},
            {"key": "year", "name": "年份", "value": [{"n": "全部", "v": ""}] + _YEARS},
        ],
        "3": [
            {"key": "area", "name": "地区", "value": [{"n": "全部", "v": ""}, {"n": "大陆", "v": "大陆"}, {"n": "港台", "v": "港台"}, {"n": "日韩", "v": "日韩"}, {"n": "欧美", "v": "欧美"}]},
            {"key": "by", "name": "排序", "value": [{"n": "最新", "v": "time"}, {"n": "最热", "v": "hits"}, {"n": "好评", "v": "score"}]},
            {"key": "lang", "name": "语言", "value": [{"n": "全部", "v": ""}, {"n": "国语", "v": "国语"}, {"n": "英语", "v": "英语"}, {"n": "粤语", "v": "粤语"}, {"n": "闽南语", "v": "闽南语"}, {"n": "韩语", "v": "韩语"}, {"n": "日语", "v": "日语"}, {"n": "其它", "v": "其它"}]},
            {"key": "letter", "name": "字母", "value": [{"n": "全部", "v": ""}] + _LETTERS},
            {"key": "year", "name": "年份", "value": [{"n": "全部", "v": ""}] + _YEARS},
        ],
        "4": [
            {"key": "area", "name": "地区", "value": [{"n": "全部", "v": ""}, {"n": "大陆", "v": "大陆"}, {"n": "日本", "v": "日本"}, {"n": "欧美", "v": "欧美"}, {"n": "其他", "v": "其他"}]},
            {"key": "by", "name": "排序", "value": [{"n": "最新", "v": "time"}, {"n": "最热", "v": "hits"}, {"n": "好评", "v": "score"}]},
            {"key": "lang", "name": "语言", "value": [{"n": "全部", "v": ""}, {"n": "国语", "v": "国语"}, {"n": "英语", "v": "英语"}, {"n": "粤语", "v": "粤语"}, {"n": "闽南语", "v": "闽南语"}, {"n": "韩语", "v": "韩语"}, {"n": "日语", "v": "日语"}, {"n": "其它", "v": "其它"}]},
            {"key": "letter", "name": "字母", "value": [{"n": "全部", "v": ""}] + _LETTERS},
            {"key": "year", "name": "年份", "value": [{"n": "全部", "v": ""}] + _YEARS},
        ],
        "20": [
            {"key": "by", "name": "排序", "value": [{"n": "最新", "v": "time"}, {"n": "最热", "v": "hits"}, {"n": "好评", "v": "score"}]},
            {"key": "letter", "name": "字母", "value": [{"n": "全部", "v": ""}] + _LETTERS},
        ],
        "35": [
            {"key": "by", "name": "排序", "value": [{"n": "最新", "v": "time"}, {"n": "最热", "v": "hits"}, {"n": "好评", "v": "score"}]},
            {"key": "letter", "name": "字母", "value": [{"n": "全部", "v": ""}] + _LETTERS},
        ],
    }

    # ==================== 列表解析 ====================
    def _parse_video_list(self, html):
        """通用卡片解析（首页/分类/搜索共用 hl-item-thumb 卡片）"""
        videos = []
        if not html:
            return videos
        pattern = re.compile(
            r'<a[^>]*class="[^"]*hl-item-thumb[^"]*"[^>]*>', re.I
        )
        for m in pattern.finditer(html):
            start = m.start()
            tag_end = m.end()
            tag = html[m.start():tag_end]

            idm = re.search(r'href="/voddetail/(\d+)\.html"', tag)
            if not idm:
                continue
            vod_id = idm.group(1)

            namem = re.search(r'title="([^"]*)"', tag)
            vod_name = self._clean_vod_name(namem.group(1).strip()) if namem else ""

            picm = re.search(r'data-original="([^"]+)"', tag)
            vod_pic = picm.group(1).strip() if picm else ""
            if vod_pic.startswith("//"):
                vod_pic = "https:" + vod_pic

            # 卡片闭合：找 </a>
            close = html.find('</a>', tag_end)
            block = html[tag_end:close] if close > 0 else ""
            note = re.search(r'<span[^>]*class="[^"]*remarks[^"]*"[^>]*>([^<]*)</span>', block)
            vod_remarks = note.group(1).strip() if note else ""

            if not vod_name and not vod_pic:
                continue
            videos.append({
                "vod_id": vod_id,
                "vod_name": vod_name,
                "vod_pic": vod_pic,
                "vod_remarks": vod_remarks,
            })
        # 去重（首页同片多次出现）
        seen, uniq = set(), []
        for v in videos:
            k = v["vod_id"]
            if k not in seen:
                seen.add(k)
                uniq.append(v)
        return uniq

    # ==================== 分类 URL 构造 ====================
    def _build_show_url(self, tid, pg, flt):
        """12 段 URL: {tid}-{area}-{by}-{空}-{lang}-{letter}-{空}-{空}-{page}-{空}-{空}-{year}
        实测：该站带筛选的 URL 不参与分页（筛选+page>1 会返回空），故有筛选时强制 page=1"""
        area = self._quote_filter_value(flt.get("area", ""))
        by = self._quote_filter_value(flt.get("by", ""))
        lang = self._quote_filter_value(flt.get("lang", ""))
        letter = self._quote_filter_value(flt.get("letter", ""))
        year = self._quote_filter_value(flt.get("year", ""))
        has_filter = any([area, by, lang, letter, year])
        page = 1 if has_filter else pg
        parts = [
            str(tid), area, by, "", lang, letter, "", "",
            str(page) if page > 1 else "", "", "", year
        ]
        return f"{self.base_url}/vodshow/{'-'.join(parts)}.html"

    # ==================== 详情解析 ====================
    def _parse_detail_info(self, html):
        """解析详情信息行: 片名/状态/主演/导演/年份/地区/类型/简介"""
        info = {}
        for m in re.finditer(
            r'<li[^>]*class="[^"]*hl-col-xs-12[^"]*"[^>]*>\s*<em[^>]*class="[^"]*hl-text-muted[^"]*"[^>]*>([^：]+)：</em>(.*?)</li>',
            html, re.DOTALL
        ):
            key = m.group(1).strip()
            val = self._clean_html(m.group(2))
            if key in ("片名", "状态", "年份", "地区", "类型"):
                val = re.sub(r'^(全部|未知)\s*$', '', val)
            info[key] = val
        if not info.get("简介"):
            dm = re.search(r'<div[^>]*class="[^"]*hl-info-content[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
            if dm:
                info["简介"] = self._clean_html(dm.group(1))
        return info

    def _parse_play_sources(self, html):
        """解析播放线路与集数：tab 顺序 ↔ sid 分组顺序对齐"""
        sources = []
        if not html:
            return sources

        # 1. 线路名（过滤 javascript: 占位）
        tabs = re.findall(
            r'<a[^>]*class="[^"]*hl-tabs-btn[^"]*"[^>]*>(?:<i[^>]*></i>\s*)?(?:&nbsp;)?([^<]{1,20})</a>',
            html
        )
        names = []
        for t in tabs:
            t = t.strip()
            if t and t not in names and not t.startswith("javascript"):
                names.append(t)

        # 2. 集数：按 sid 分组 + 按链接去重（Conch 模板"立即播放"按钮与第01集同链接）
        groups = {}
        for m in self._re_vplay_link.finditer(html):
            vid, sid, nid, name = m.groups()
            link = f"{vid}-{sid}-{nid}"
            # 去掉 &nbsp; 实体与 NBSP 字符
            name = name.replace("&nbsp;", "").replace("\u00a0", "").strip()
            is_btn = name in ("立即播放", "马上播放")
            if sid not in groups:
                groups[sid] = {}
            if link in groups[sid]:
                # 保留集数名，丢弃重复的"立即播放"按钮
                if is_btn:
                    continue
                if groups[sid][link] in ("立即播放", "马上播放"):
                    groups[sid][link] = name
            else:
                groups[sid][link] = name
        sids = sorted(groups.keys())

        # 3. 对齐线路名与分组（dict -> 有序列表）
        episodes_of = {sid: [{"name": nm, "link": lnk} for lnk, nm in groups[sid].items()] for sid in sids}
        if names and len(names) == len(sids):
            for sid, sid_name in zip(sids, names):
                sources.append({"source_name": sid_name, "episodes": episodes_of[sid]})
        else:
            for sid in sids:
                sources.append({"source_name": f"线路{sid}", "episodes": episodes_of[sid]})

        # 4. 4K/蓝光线路置顶
        if sources:
            def _rank(i):
                nm = sources[i]["source_name"]
                is_4k = any(k in nm for k in ("4K", "4k", "2160", "2160P", "2160p"))
                is_bluray = "蓝光" in nm
                cnt = len(sources[i]["episodes"])
                no_eps = 1 if cnt == 0 else 0
                order = 0 if is_4k else (1 if is_bluray else 2)
                return (no_eps, order, i)
            sources = [sources[i] for i in sorted(range(len(sources)), key=_rank)]
        return sources

    # ==================== 播放地址解析 ====================
    def _extract_player_aaaa(self, html):
        """提取 player_aaaa 字典（字符串感知的花括号匹配）"""
        if not html:
            return None
        m = re.search(r'player_aaaa\s*=\s*', html)
        if not m:
            return None
        start = m.end()
        while start < len(html) and html[start] != '{':
            start += 1
        if start >= len(html):
            return None
        depth = 1
        i = start + 1
        in_string = False
        escape = False
        while i < len(html) and depth > 0:
            c = html[i]
            if in_string:
                if escape:
                    escape = False
                elif c == '\\':
                    escape = True
                elif c == '"':
                    in_string = False
            else:
                if c == '"':
                    in_string = True
                elif c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
            i += 1
        if depth == 0:
            try:
                return json.loads(html[start:i])
            except Exception as e:
                self._log(f"player_aaaa JSON解析失败: {e}")
        return None

    def _get_play_url(self, vod_id, sid, nid):
        play_page = f"{self.base_url}/vodplay/{vod_id}-{sid}-{nid}.html"
        cache_key = f"{vod_id}-{sid}-{nid}"
        now = time.time()
        if cache_key in self._play_cache:
            url, ts = self._play_cache[cache_key]
            if now - ts < self._cache_ttl:
                self._log(f"播放地址缓存命中: {cache_key}")
                return url

        try:
            html = self._get(play_page, max_retry=2, timeout=8)
            if not html:
                self._log(f"播放页无响应, 回退播放页: {play_page}")
                return play_page

            player_data = self._extract_player_aaaa(html)
            if not player_data:
                self._log("未能提取到player_aaaa, 回退播放页")
                return play_page

            enc_url = player_data.get("url", "")
            encrypt = str(player_data.get("encrypt", "0"))
            self._log(f"player_aaaa encrypt={encrypt}, url={enc_url[:60]}...")

            # MacCMS 加密方式处理
            if encrypt == "1":
                try:
                    enc_url = urllib.parse.unquote(enc_url)
                except Exception:
                    pass
            elif encrypt == "2":
                try:
                    enc_url = urllib.parse.unquote(base64.b64decode(enc_url).decode('utf-8'))
                except Exception:
                    pass

            if not enc_url:
                return play_page

            if re.search(r'\.(m3u8|mp4|flv|ts|mkv)(\?|#|$)', enc_url, re.I):
                self._log(f"已是直链: {enc_url[:70]}")
                self._play_cache[cache_key] = (enc_url, now)
                return enc_url

            # 非直链：交给壳子解析
            self._play_cache[cache_key] = (enc_url, now)
            return enc_url
        except Exception as e:
            self._log(f"获取播放地址异常: {e}")
            return play_page

    # ==================== TVBox 核心方法 ====================
    def init(self, extend=''):
        self._log("初始化完成")

    def homeContent(self, filter=False):
        result = {
            "class": [
                {"type_id": tid, "type_name": name}
                for tid, name in self.CATEGORY_NAMES.items()
            ]
        }
        if filter:
            result["filters"] = self.FILTERS
            result["filter"] = self.FILTERS
        return result

    def homeVideoContent(self):
        try:
            html = self._get(self.base_url)
            if not html:
                return {"list": []}
            videos = self._parse_video_list(html)
            return {"list": videos[:20]}
        except Exception as e:
            self._log(f"homeVideoContent异常: {e}")
            return {"list": []}

    def categoryContent(self, tid, pg, filter=False, content=None):
        try:
            pg = int(pg)
            if str(tid) not in self.CATEGORY_NAMES:
                return {"list": [], "page": pg, "pagecount": 1, "limit": 20, "total": 0}

            flt = {}
            if content:
                try:
                    flt = json.loads(content) if isinstance(content, str) else content
                except Exception:
                    flt = {}

            url = self._build_show_url(tid, pg, flt)
            self._log(f"分类请求: {url}")
            html = self._get(url)
            if not html:
                return {"list": [], "page": pg, "pagecount": 1, "limit": 20, "total": 0}
            videos = self._parse_video_list(html)

            # 总页数：hl-page-total "2&nbsp;/&nbsp;4页"
            pagecount = 1
            total = re.search(r'hl-page-total[^>]*>\s*(\d+)\s*(?:&nbsp;)?/\s*(?:&nbsp;)?(\d+)页', html)
            if total:
                pagecount = int(total.group(2))
            else:
                last = re.search(r'href="/vodshow/\d+(?:-[^"]*?)?--------(\d+)---\.html"[^>]*>尾页</a>', html)
                if last:
                    pagecount = int(last.group(1))
            return {
                "list": videos,
                "page": pg,
                "pagecount": pagecount,
                "limit": 20,
                "total": pagecount * 20
            }
        except Exception as e:
            self._log(f"categoryContent异常: {e}")
            return {"list": [], "page": pg, "pagecount": 1, "limit": 20, "total": 0}

    def searchContent(self, key, quick=False, pg="1"):
        try:
            pg = max(1, int(pg or 1))
        except (TypeError, ValueError):
            pg = 1
        keyword = str(key or "").strip()
        if not keyword:
            return {"page": pg, "pagecount": 1, "limit": 0, "total": 0, "list": []}
        encoded_key = quote(keyword)
        if pg > 1:
            url = f"{self.base_url}/vodsearch/{encoded_key}----------{pg}---.html"
        else:
            url = f"{self.base_url}/vodsearch/{encoded_key}-------------.html"
        self._log(f"搜索请求: {url}, quick={bool(quick)}")

        try:
            # 搜索限速：站点要求搜索间隔3秒，主动拉开间隔避免触发提示页
            now = time.time()
            wait = self._search_interval - (now - self._last_search_time)
            if wait > 0:
                self._log(f"搜索冷却中，等待{wait:.1f}s")
                time.sleep(wait)
            html = self._get(url)
            self._last_search_time = time.time()
            if not html:
                return {"list": [], "page": pg, "pagecount": 1, "limit": 20, "total": 0}
            videos = self._parse_video_list(html)

            # quick（聚合搜索）模式直接返回，减少壳子聚合等待
            if not bool(quick):
                key_lower = keyword.lower()
                def _sort_score(v):
                    name = v.get('vod_name', '').lower()
                    if name == key_lower:
                        return 0
                    if name.startswith(key_lower):
                        return 1
                    if key_lower in name:
                        return 2
                    return 3
                videos = sorted(videos, key=_sort_score)

            return {
                "list": videos,
                "page": pg,
                "pagecount": 9999,
                "limit": 20,
                "total": 999999
            }
        except Exception as e:
            self._log(f"搜索Content异常: {e}")
            return {"list": [], "page": pg, "pagecount": 1, "limit": 20, "total": 0}

    def detailContent(self, ids):
        try:
            vod_id = ids[0] if isinstance(ids, list) else str(ids)
            url = f"{self.base_url}/voddetail/{vod_id}.html"
            self._log(f"详情请求: {url}")
            html = self._get(url)
            if not html:
                return {"list": []}

            info = self._parse_detail_info(html)
            vod_name = info.get("片名", "")
            if not vod_name:
                tm = re.search(r'<title>《?([^《》]{1,40})》?[^<]*</title>', html)
                vod_name = tm.group(1).strip() if tm else ""
            vod_name = self._clean_vod_name(vod_name)

            # 封面：hl-topbg-pic 背景图，兜底任意 vod 图片
            vod_pic = ""
            pm = re.search(r'hl-topbg-pic[^>]*style="background-image:\s*url\(([^)]+)\)', html)
            if pm:
                vod_pic = pm.group(1).strip().strip('"\'')
            if not vod_pic:
                im = re.search(r'<img[^>]*data-original="(https?://[^"]*(?:webp|jpg|jpeg|png)[^"]*)"', html)
                if im:
                    vod_pic = im.group(1)
            if vod_pic.startswith("//"):
                vod_pic = "https:" + vod_pic

            sources = self._parse_play_sources(html)
            if not sources:
                self._log("未能解析到播放源")
                return {"list": []}

            from_list, url_list = [], []
            for src in sources:
                from_list.append(src["source_name"])
                eps_str = "#".join([f"{ep['name']}${ep['link']}" for ep in src["episodes"]])
                url_list.append(eps_str)

            video = {
                "vod_id": vod_id,
                "vod_name": vod_name,
                "vod_pic": vod_pic,
                "vod_year": info.get("年份", ""),
                "vod_area": info.get("地区", ""),
                "vod_actor": info.get("主演", ""),
                "vod_director": info.get("导演", ""),
                "vod_content": info.get("简介", ""),
                "vod_remarks": info.get("状态", ""),
                "vod_play_from": "$$$".join(from_list),
                "vod_play_url": "$$$".join(url_list),
            }
            self._log(f"详情解析成功: {vod_name}, 线路: {'/'.join(from_list)}")
            return {"list": [video]}
        except Exception as e:
            self._log(f"detailContent异常: {e}")
            return {"list": []}

    def playerContent(self, flag, id, vipFlags=None):
        try:
            parts = str(id).split("-")
            if len(parts) != 3:
                return {"parse": 0, "url": "", "header": ""}
            vod_id, sid, nid = parts
            play_page = f"{self.base_url}/vodplay/{vod_id}-{sid}-{nid}.html"
            play_url = self._get_play_url(vod_id, sid, nid)
            if not play_url:
                play_url = play_page

            is_direct = bool(re.search(r'\.(m3u8|mp4|flv|ts|mkv)([?#&]|$)', play_url, re.I))
            is_parse_page = play_url.startswith(play_page)
            parse_flag = 0 if (is_direct or not is_parse_page) else 1
            self._log(f"播放URL: {play_url[:70]}..., parse={parse_flag}")

            if parse_flag == 0:
                return {"parse": 0, "url": play_url, "header": self.play_headers.copy()}
            else:
                return {"parse": 1, "url": play_url, "header": ""}
        except Exception as e:
            self._log(f"playerContent异常: {e}")
            return {"parse": 0, "url": "", "header": ""}

    def getName(self):
        return self.name

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def destroy(self):
        pass

    def localProxy(self, param):
        pass
