# -*- coding: utf-8 -*-
import re
import os
import json
import time
import tempfile
import requests
import warnings
from urllib.parse import quote, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

try:
    warnings.filterwarnings('ignore')
    requests.packages.urllib3.disable_warnings()
except Exception:
    pass

from base.spider import Spider

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'

# 多线路聚合配置
LINE_BATCH = 8
AUX_TIMEOUT = 2
# SPEED_TIMEOUT: 线路测速超时秒数（HEAD 探测首集 m3u8 响应时间）
SPEED_TIMEOUT = 3
# SPEED_WORKERS: 测速并发数
SPEED_WORKERS = 35
# 搜索结果上限
SEARCH_RESULT_LIMIT = 100
# 渐进加载：首页/分类首轮只拉前 N 个源，避免启动慢
FIRST_LOAD_SOURCES = 4
# 首页列表并发数
HOME_LIST_WORKERS = 4

SOURCES = [
   {'key': 'iqiyi', 'name': '奇艺资源', 'api': 'https://iqiyizyapi.com/api.php/provide/vod'},
    {'key':'hdzyk','name':'优质资源','api':'https://api.yyzy-tv.vip/inc/apijson.php?ac=list'},
    {'key':'dyttzy','name':'天堂资源','api':'https://caiji.dyttzyapi.com/api.php/provide/vod'},
   {'key':'lzi','name':'量子资源','api':'https://cj.lziapi.com/api.php/provide/vod'},
    {'key':'ruyi','name':'如意资源','api':'https://cj.rycjapi.com/api.php/provide/vod'},
    {'key':'bfzy','name':'暴风资源','api':'https://bfzyapi.com/api.php/provide/vod'},
    {'key':'ffzy','name':'非凡资源','api':'https://ffzy5.tv/api.php/provide/vod'},
    {'key':'zy360','name':'360资源','api':'https://360zy.com/api.php/provide/vod'},
    {'key':'jisu','name':'极速资源','api':'https://jszyapi.com/api.php/provide/vod'},
    {'key':'zuid','name':'最大资源','api':'https://api.zuidapi.com/api.php/provide/vod'},
    {'key':'ty','name':'天涯资源','api':'https://tyyszyapi.com/api.php/provide/vod'},
    {'key':'hhzy','name':'火狐资源','api':'https://hhzyapi.com/api.php/provide/vod'},
    {'key':'myzy','name':'猫眼资源','api':'https://api.maoyanapi.top/api.php/provide/vod'},
    {'key':'155zy','name':'155资源','api':'https://155api.com/api.php/provide/vod'},
    {'key':'hnzy','name':'红牛资源','api':'https://www.hongniuzy2.com/api.php/provide/vod'},
    {'key':'hyzy','name':'虎牙资源','api':'https://www.huyaapi.com/api.php/provide/vod'},
    {'key':'uku','name':'优酷资源','api':'https://api.ukuapi88.com/api.php/provide/vod'},
    {'key':'guangsu','name':'光速资源','api':'https://api.guangsuapi.com/api.php/provide/vod'},
    {'key':'xinlang','name':'新浪资源','api':'https://api.xinlangapi.com/xinlangapi.php/provide/vod'},
    {'key':'yhzy','name':'樱花资源','api':'https://m3u8.apiyhzy.com/api.php/provide/vod'},
    {'key':'nnzy','name':'牛牛资源','api':'https://api.niuniuzy.me/api.php/provide/vod'},
    {'key':'baiduyun','name':'百度资源','api':'https://api.apibdzy.com/api.php/provide/vod'},
    {'key':'subo','name':'速播资源','api':'https://subocaiji.com/api.php/provide/vod'},
    {'key':'jinying','name':'金鹰资源','api':'https://jinyingzy.com/api.php/provide/vod'},
   {'key':'piaoling','name':'飘零资源','api':'https://p2100.net/api.php/provide/vod'},
    {'key':'modu','name':'魔都资源','api':'https://www.mdzyapi.com/api.php/provide/vod'},
    {'key':'xgzy','name':'西瓜资源','api':'https://caiji.xgzyapi.com/api.php/provide/vod'},
    {'key':'dzzy','name':'大众资源','api':'https://cdn.dzzyapi.com/api.php/provide/vod'},
   {'key':'wsyzy','name':'无水印资源','api':'https://api.wsyzy.net/api.php/provide/vod'},
    {'key':'mtzy','name':'茅台资源','api':'https://caiji.maotaizy.cc/api.php/provide/vod'},
    {'key':'xsd','name':'闪电资源','api':'https://xsd.sdzyapi.com/api.php/provide/vod/'},
    {'key':'sdzy','name':'速度资源','api':'https://sdzyapi.com/api.php/provide/vod'},
    {'key':'suoni','name':'索尼资源','api':'https://suoniapi.com/api.php/provide/vod'},
    {'key':'dbzy','name':'豆瓣资源','api':'https://caiji.dbzy5.com/api.php/provide/vod'},
    {'key':'wujin','name':'无尽资源','api':'https://api.wujinapi.cc/api.php/provide/vod'},
]

BLOCKED_CATEGORIES = {
    '电视剧', 'NBA', '动漫', '综艺', '电影片', '综艺片', '动漫片', '汽车', '资讯', '预告资讯', '影视资讯', '明星资讯', '福利', '足球', '台球', '篮球', '网球', '斯诺克', '演员', '电影资讯', '电影', '连续剧', '短片', '未分类', '影视解说', '预告解说', '科普学习', '娱乐新闻', '体育', '新闻资讯', '预告片', '体育赛事', '其他赛事', 'LPL', '写真热舞','娱乐动态', '八卦爆料', '影片资讯','站内新闻',
    # 成人分类（屏蔽）
    '倫理片', '伦理片', '里番动漫', '擦边短剧', '擦边剧', '伦理', '成人', '18禁', 'AV', 'xxx', 'X视频'
}

# 成人片名关键词：命中即过滤（详情页搜索、聚合都过滤）
ADULT_KEYWORDS = ['里番', '倫理', '伦理', 'AV', '18禁', '成人', 'xxx', 'X片', '啪啪', '毛片', '小电影', '深夜', '偷拍', '自拍福利', '福利视频']

# 已知里番/成人片黑名单（整片名精确匹配，避免"第一次"等常见词误伤正常剧）
ADULT_TITLE_EXACT = [
    '罪恶之渊', 'GuiltyHole', 'Guilty Hole', 'guiltyhole', 'guilty hole',
    '圣华女学院', '聖華女學院', '圣华', '聖華',
    '淫兽们的教师', '淫獸們的教師', '淫兽', '淫獸',
    '人妻初体验', '人妻初體驗', '第一次的人妻',
    '僧侣',
    '里番精选', '里番动画', '里番合集', '里番剧场',
    '罪恶之渊 GuiltyHole',
]

# 成人标签/简介敏感词：命中 vod_tag 或 vod_blurb 即过滤（收窄为成人专属词，避免误伤正常影视）
ADULT_META_KEYWORDS = [
    '福利视频', '色情', 'AV', '里番', '倫理', '伦理', '18禁', 'R18', '深夜档', '偷拍视频', '自拍福利',
    '毛片', '小电影', '无码', '有码', '乱伦', '乱交', '群交', '多P', '3P', 'NTR', '牛头人',
    '人妻OL', '熟女熟妇', '童颜巨乳', '巨乳美臀', '乳交', '足交', '口交', '肛交', '露点', '露骨',
    '裸体', '床戏', '激情戏', '尺度大',
]

CATEGORY_GROUPS = {
    0: [  # 短剧类
        '短剧', '爽文短剧', '女频恋爱', '反转爽剧', '古装仙侠', '穿越年代', '短剧反转爽剧', '短剧古装仙侠', '脑洞', '科幻', '仙侠', '喜剧', '动作','悬疑', '恐怖', '爱情', '年代穿越', '现代言情', '反转爽文', '女恋总裁', '闪婚离婚', '短剧女频恋爱', '短剧成长逆袭', '成长逆袭','都市脑洞', '脑洞悬疑', '现代都市', '擦边短剧', '擦边剧', '漫剧', '短剧现代都市', '短剧脑洞悬疑', '短剧年代穿越', 'AI漫剧', '玄幻', '剧情', '女性成长', '权谋', '豪门', '奇幻', '宫斗', '冒险', '战神', '刑侦', '求生', '商战', '武侠', '短剧大全', '重生民国', '穿越现代', '悬疑烧脑', '言情总裁'
    ],
    1: [  # 剧集类
        '国产剧', '内地剧', '香港剧', '韩国剧', '欧美剧', '日本剧', '韩剧', '日剧', '马泰剧', '大陆剧', '港澳剧', '泰剧', '港台剧', '港剧', '台剧', '台湾剧', '泰国剧', '海外剧', 'Netflix自制剧'
    ],
    2: [  # 电影类
        '动作片', '喜剧片', '爱情片', '科幻片', '恐怖片', '剧情片', '战争片', '动画片', '4K电影', '奇幻片', '邵氏电影', 'Netflix电影', '记录片', '倫理片', '惊悚片', '动画电影', '动漫电影', '家庭片', '家庭篇', '古装片', '历史片', '纪录片', '西部片', '悬疑片', '灾难片', '犯罪片'
    ],
    3: [  # 动漫类
        '国产动漫', '日韩动漫', '欧美动漫', '港台动漫', '中国动漫', '日本动漫', '里番动漫', '海外动漫', '有声动漫'
    ],
    4: [  # 综艺类
        '大陆综艺', '日韩综艺', '港台综艺', '欧美综艺', '演唱会'
    ],
    5: [  # 伦理类
        '伦理', '港台三级', '韩国伦理', '西方伦理', '日本伦理', '两性课堂'
    ]
}

CAT_ORDER = {name: idx for idx, names in CATEGORY_GROUPS.items() for name in names}


def _is_adult_meta(v):
    """检查视频的标签/简介是否含成人敏感词（第三层过滤，详情聚合时调用）。
    命中 vod_tag 或 vod_blurb 即判为成人内容返回 True。"""
    for field in ('vod_tag', 'vod_blurb'):
        val = v.get(field, '') or ''
        if not val:
            continue
        for kw in ADULT_META_KEYWORDS:
            if kw in val:
                return True
    return False


def _same_name(a, b):
    def norm(s):
        s = re.sub(r'[\s·•：:，,。！？!?（）()【】\[\]]', '', str(s or '')).lower()
        s = re.sub(r'(国语|粤语|日语|英语|韩语|韩语中|中文字|国语版|中文字幕|英语原|原声)', '', s)
        s = re.sub(r'(高清版|超清|蓝光|720p|1080p|4k|HDR|4K)', '', s)
        s = re.sub(r'(完整版|全集|正片|高清)', '', s)
        s = re.sub(r'(第一季|第二季|第三季|第四季|第五季|第六季|第[一二三四五六七八九十]季|季)', '', s)
        s = re.sub(r'(电影|电视剧|剧集|动画|动漫|剧|版|部)', '', s)
        s = re.sub(r'(我的|网飞|Netflix|网飞版|Netflix版|官方)', '', s)
        s = re.sub(r'^第?[一二三四五六七八九十\d]+[章节集]?$', '', s)
        return s
    x, y = norm(a), norm(b)
    # 核心片名极短时（如"三体"=2字），要求至少一个出现在另一个中
    if not x or not y:
        return False
    return x in y or y in x


def _is_direct_url(url):
    """直链检测：只保留 .m3u8/.mp4 直链，过滤解析器中间页。"""
    if not url or not isinstance(url, str):
        return False
    u = url.split('?')[0].lower()
    return u.endswith('.m3u8') or u.endswith('.mp4')

class Spider(Spider):
    def getName(self):
        return '采集资源'

    def init(self, extend=''):
        self.header = {'User-Agent': UA}
        self.sess = requests.Session()
        self.sess.headers.update(self.header)
        self.sess.verify = False
        self.by_key = {s['key']: s for s in SOURCES}
        self.class_cache = {}
        self.detail_cache = {}
        self.speed_cache = {}  # key -> 响应秒数
        self._disk_cache = self._load_disk_cache()
        # 从磁盘缓存恢复分类和测速结果（分类24小时有效，测速1小时有效）
        for key, cats in self._disk_cache.get('classes', {}).items():
            if key in self.by_key:
                self.class_cache[key] = cats
        for key, sp in self._disk_cache.get('speeds', {}).items():
            if key in self.by_key:
                self.speed_cache[key] = sp

    def _disk_cache_path(self):
        """缓存文件路径：优先 /storage/emulated/0，失败回退临时目录。"""
        for p in ('/storage/emulated/0/cc_cache.json', '/data/data/.../cc_cache.json'):
            try:
                d = os.path.dirname(p)
                if os.path.isdir(d) and os.access(d, os.W_OK):
                    return p
            except Exception:
                continue
        return os.path.join(tempfile.gettempdir(), 'cc_cache.json')

    def _load_disk_cache(self):
        try:
            p = self._disk_cache_path()
            if os.path.exists(p):
                with open(p, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_disk_cache(self, cache=None):
        """落盘缓存：分类结果24小时有效，测速结果1小时有效。"""
        try:
            import time as _t
            now = _t.time()
            data = {}
            data['classes'] = {k: v for k, v in (self.class_cache or {}).items()}
            # 分类：过期丢弃
            cls_kept = {}
            for k, v in data['classes'].items():
                ts = self._disk_cache.get('classes_ts', {}).get(k)
                if not ts or now - ts < 86400:
                    cls_kept[k] = v
            data['classes'] = cls_kept
            # 测速：过期丢弃
            spd_kept = {}
            for k, sp in (self.speed_cache or {}).items():
                ts = self._disk_cache.get('speeds_ts', {}).get(k)
                if ts and now - ts < 3600:
                    spd_kept[k] = sp
            data['speeds'] = spd_kept
            data['classes_ts'] = self._disk_cache.get('classes_ts', {})
            data['speeds_ts'] = self._disk_cache.get('speeds_ts', {})
            # 记录本次新获取的时间戳
            data['classes_ts'].update({k: now for k in self.class_cache})
            data['speeds_ts'].update({k: now for k in self.speed_cache})
            with open(self._disk_cache_path(), 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass

    def _speed_key(self, s):
        sp = self.speed_cache.get(s['key'])
        if sp is not None:
            return (0, sp)
        return (1, SOURCES.index(s))

    def sorted_sources(self):
        return sorted(SOURCES, key=lambda s: self._speed_key(s))

    def _is_blocked(self, category_name):
        if not category_name:
            return False
        return category_name.strip() in BLOCKED_CATEGORIES

    def _get(self, source, timeout=8, retry=True, **params):
        attempts = 2 if retry else 1
        for attempt in range(attempts):
            try:
                api = source['api'].split('?')[0]
                r = self.sess.get(api, params=params, timeout=timeout)
                if r.status_code == 200:
                    return r.json()
                return {}
            except Exception:
                if attempt == 0:
                    continue
                return {}
        return {}

    def _fmt(self, v, key, show_source=False):
        vod_name = v.get('vod_name', '') or ''
        # 第一层：成人片名关键词
        for kw in ADULT_KEYWORDS:
            if kw in vod_name:
                return None
        # 第二层：黑名单整片名精确匹配（绕过分类过滤的里番）
        clean_name = re.sub(r'[\s·•：:，,。！？!?（）()【】\[\]]', '', vod_name).strip()
        for bl in ADULT_TITLE_EXACT:
            if clean_name == re.sub(r'[\s·•：:，,。！？!?（）()【】\[\]]', '', bl).strip():
                return None
        return self._fmt_impl(v, key, show_source)

    def _fmt_impl(self, v, key, show_source=False):
        remarks = v.get('vod_remarks', '')
        
        if show_source:
            source_name = self.by_key.get(key, {}).get('name', '')
            if remarks:
                remarks = f"{source_name} {remarks}"
            else:
                remarks = source_name
        
        return {
            'vod_id': key + '|' + str(v.get('vod_id', '')),
            'vod_name': v.get('vod_name', ''),
            'vod_pic': v.get('vod_pic', ''),
            'vod_remarks': remarks,
            'vod_actor': v.get('vod_actor', ''),
            'vod_year': v.get('vod_year', ''),
        }

    def _batch_enrich_pics(self, items):
        if not items:
            return
        need_pic = [item for item in items if not item.get('vod_pic')]
        if not need_pic:
            return
        groups = {}
        for item in need_pic:
            vid = item.get('vod_id', '')
            if '|' not in vid:
                continue
            src_key, real_id = vid.split('|', 1)
            if not src_key or not real_id:
                continue
            groups.setdefault(src_key, []).append((item, real_id))
        for src_key, pairs in groups.items():
            src = self.by_key.get(src_key)
            if not src:
                continue
            real_ids = [p[1] for p in pairs]
            for i in range(0, len(real_ids), 50):
                batch_ids = real_ids[i:i+50]
                ids_str = ','.join(batch_ids)
                if not ids_str:
                    continue
                j = self._get(src, ac='detail', ids=ids_str)
                if not j or not j.get('list'):
                    continue
                pic_map = {}
                for v in j['list']:
                    vid = str(v.get('vod_id', ''))
                    if vid:
                        pic_map[vid] = v.get('vod_pic', '')
                for item, real_id in pairs:
                    if real_id in pic_map and pic_map[real_id]:
                        item['vod_pic'] = pic_map[real_id]

    def _get_categories(self, source):
        key = source['key']
        if key in self.class_cache:
            return self.class_cache[key]
        try:
            d = self._get(source, ac='list', pg=1)
            classes = d.get('class', [])
            cats = []
            for c in classes:
                type_id = c.get('type_id', '')
                type_name = c.get('type_name', '')
                if type_id and type_name:
                    if self._is_blocked(type_name):
                        continue
                    cats.append({'v': type_id, 'n': type_name})
            def sort_key(x):
                return CAT_ORDER.get(x['n'], 99)
            cats.sort(key=sort_key)
            self.class_cache[key] = cats
            return cats
        except Exception:
            return []

    def homeContent(self, filter):
        sources = self.sorted_sources()
        classes = [{'type_id': s['key'], 'type_name': s['name']} for s in sources]
        filters = {}

        # 首页同步拉全部分类（35路并发，首次~5s，落盘缓存后二次秒开）
        with ThreadPoolExecutor(max_workers=35) as executor:
            futures = {executor.submit(self._get_categories, s): s for s in sources}
            for future in as_completed(futures):
                s = futures[future]
                try:
                    cats = future.result(timeout=4)
                    filters[s['key']] = [{
                        'key': 'cateId',
                        'name': '分类',
                        'value': cats if cats else [{'v': '', 'n': '全部'}]
                    }]
                except Exception:
                    filters[s['key']] = [{
                        'key': 'cateId',
                        'name': '分类',
                        'value': [{'v': '', 'n': '全部'}]
                    }]

        self._save_disk_cache()

        # 首页列表：只拉前 FIRST_LOAD_SOURCES 个源（分类已拉完，此处再花 2-3s 补图）
        items = []
        seen = set()
        target_sources = sources[:FIRST_LOAD_SOURCES]

        with ThreadPoolExecutor(max_workers=HOME_LIST_WORKERS) as executor:
            futures = {executor.submit(self._get, s, timeout=4, ac='list', pg=1): s for s in target_sources}
            for future in as_completed(futures):
                s = futures[future]
                try:
                    data = future.result(timeout=5)
                    if data and data.get('list'):
                        for v in data.get('list', []):
                            type_name = v.get('vod_class', '') or v.get('type_name', '')
                            if self._is_blocked(type_name):
                                continue
                            item = self._fmt(v, s['key'])
                            if item is None:
                                continue
                            if item['vod_id'] in seen:
                                continue
                            seen.add(item['vod_id'])
                            items.append(item)
                except Exception:
                    continue

        items = items[:20]
        self._batch_enrich_pics(items)

        # 后台异步测速
        self._background_speed_test()

        return {
            'class': classes,
            'filters': filters,
            'list': items
        }

    def _background_fetch_categories(self, sources):
        """后台线程异步拉取分类，不阻塞首页返回。完成即落盘，下次启动直接用缓存。"""
        def worker():
            try:
                with ThreadPoolExecutor(max_workers=8) as executor:
                    futures = {executor.submit(self._get_categories, s): s for s in sources}
                    for future in as_completed(futures):
                        s = futures[future]
                        try:
                            cats = future.result(timeout=5)
                            if cats:
                                self.class_cache[s['key']] = cats
                        except Exception:
                            continue
                self._save_disk_cache()
            except Exception:
                pass
        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _background_speed_test(self):
        """后台线程并发 HEAD 探测各源响应时间，写入 speed_cache。
        下次详情页用 sorted_sources() 就能让快源优先。"""
        def worker():
            try:
                with ThreadPoolExecutor(max_workers=35) as executor:
                    futures = {executor.submit(self._speed_one, s): s for s in SOURCES}
                    for future in as_completed(futures):
                        s = futures[future]
                        try:
                            sp = future.result(timeout=4)
                            if sp is not None:
                                self.speed_cache[s['key']] = sp
                        except Exception:
                            continue
                self._save_disk_cache()
            except Exception:
                pass
        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _speed_one(self, s):
        """HEAD 探测单个源的响应秒数，失败返回 None。"""
        try:
            api = s['api'].split('?')[0]
            t0 = time.time()
            r = self.sess.head(api, timeout=SPEED_TIMEOUT, allow_redirects=True)
            dt = time.time() - t0
            return dt if r.status_code < 500 else None
        except Exception:
            return None

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if str(pg).isdigit() else 1
        site_key = tid
        cate_id = ''

        if extend:
            if isinstance(extend, dict):
                cate_id = extend.get('cateId', '') or extend.get('category', '')
            elif isinstance(extend, str):
                cate_id = extend

        src = self.by_key.get(site_key)
        if not src:
            return {'list': []}

        cats = self._get_categories(src)

        if cate_id:
            if cats:
                valid = any(str(c['v']) == str(cate_id) for c in cats)
                if not valid:
                    return {'list': [], 'page': page, 'pagecount': 0, 'limit': 30, 'total': 0}

        params = {'ac': 'list', 'pg': page}
        if cate_id:
            params['t'] = cate_id

        d = self._get(src, **params)
        items = []
        for v in d.get('list', []):
            type_name = v.get('vod_class', '') or v.get('type_name', '')
            if self._is_blocked(type_name):
                continue
            item = self._fmt(v, site_key)
            if item is None:
                continue
            items.append(item)

        self._batch_enrich_pics(items)

        return {
            'list': items,
            'page': page,
            'pagecount': int(d.get('pagecount', 1) or 1),
            'limit': 30,
            'total': int(d.get('total', 0) or 0),
            'filters': {
                'cateId': [{
                    'key': 'cateId',
                    'name': '分类',
                    'value': cats if cats else [{'v': '', 'n': '全部'}]
                }]
            }
        }

    def searchContent(self, key, quick, pg='1'):
        items = []
        seen = set()
        # 按测速排序，只搜前 12 个源（快源优先，2s 超时，搜索 2 秒内完成）
        sources = self.sorted_sources()[:12]

        with ThreadPoolExecutor(max_workers=12) as executor:
            futures = {executor.submit(self._get, s, retry=False, timeout=2, ac='list', wd=key): s for s in sources}
            for future in as_completed(futures):
                s = futures[future]
                try:
                    d = future.result(timeout=3)
                    for v in d.get('list', [])[:5]:
                        type_name = v.get('vod_class', '') or v.get('type_name', '')
                        if self._is_blocked(type_name):
                            continue
                        item = self._fmt(v, s['key'], True)
                        if item is None:
                            continue
                        if item['vod_id'] in seen:
                            continue
                        seen.add(item['vod_id'])
                        items.append(item)
                except Exception:
                    continue

        # 搜索不补图（提速，封面用源自带 vod_pic）
        return {'list': items[:100]}

    def detailContent(self, ids):
        if isinstance(ids, list):
            ids = ids[0]

        if '|' not in ids:
            return {'list': []}

        key, vid = ids.split('|', 1)
        src = self.by_key.get(key)
        if not src:
            return {'list': []}

        cache_key = f"{key}|{vid}"
        if cache_key in self.detail_cache:
            return self.detail_cache[cache_key]

        d = self._get(src, ac='detail', ids=vid)
        if not d.get('list'):
            return {'list': []}

        vod = d['list'][0]
        name = vod.get('vod_name', '') or ''

        type_name = vod.get('vod_class', '') or vod.get('type_name', '')
        if self._is_blocked(type_name):
            return {'list': []}

        # ====== 多线路聚合：主源 + 其他采集同名资源（渐进加载：快源优先）======
        play_froms = []
        play_urls = []

        # 主源线路（立即返回的基础线路）
        self._collect_lines(src, vod, play_froms, play_urls)

        # 渐进聚合：只拉前 6 个快源，2s 超时；先到的线路先返回，慢源不阻塞
        # 用户刷新时能追加更多线路（sorted_sources 测速排序保证快源优先）
        AGGREGATE_FIRST = 6  # 首轮聚合前 6 快源
        others = [s for s in self.sorted_sources() if s['key'] != key][:AGGREGATE_FIRST]
        with ThreadPoolExecutor(max_workers=AGGREGATE_FIRST) as executor:
            futures = {executor.submit(self._fetch_matches, s, name): s for s in others}
            for future in as_completed(futures):
                if len(play_froms) >= LINE_BATCH:
                    break
                s = futures[future]
                try:
                    d = future.result(timeout=2)
                    if not d or not d.get('list'):
                        continue
                    for v2 in d['list']:
                        n2 = v2.get('vod_name', '') or ''
                        if not _same_name(n2, name):
                            continue
                        # 第三层：标签/简介敏感词过滤（详情字段完整，能准确识别）
                        if _is_adult_meta(v2):
                            continue
                        f2, u2 = [], []
                        self._collect_lines(s, v2, f2, u2)
                        if u2 and len(play_froms) < LINE_BATCH:
                            play_froms.extend(f2)
                            play_urls.extend(u2)
                        break
                except Exception:
                    continue

        # 去重线路
        play_froms, play_urls = self._deduplicate_playlists(play_froms, play_urls)

        result = {
            'list': [{
                'vod_id': ids,
                'vod_name': name,
                'vod_pic': vod.get('vod_pic', ''),
                'vod_remarks': vod.get('vod_remarks', ''),
                'vod_year': vod.get('vod_year', ''),
                'vod_area': vod.get('vod_area', ''),
                'vod_actor': vod.get('vod_actor', ''),
                'vod_director': vod.get('vod_director', ''),
                'vod_content': re.sub(r'<[^>]+>', '', str(vod.get('vod_content', ''))),
                'vod_play_from': '$$$'.join(play_froms),
                'vod_play_url': '$$$'.join(play_urls)
            }]
        }

        self.detail_cache[cache_key] = result
        return result

    def _collect_lines(self, src, vod, play_froms, play_urls):
        """从一个源的详情数据中提取所有线路（含直链和解析地址），让 playerContent 决定解析。"""
        src_name = src.get('name', src.get('key', ''))
        if src_name in play_froms:
            return
        from_raw = str(vod.get('vod_play_from', '') or '').replace('$$$', ',').replace('，', ',')
        froms = [x.strip() for x in from_raw.split(',') if x.strip()]
        url_groups = [x.strip() for x in str(vod.get('vod_play_url', '') or '').split('$$$') if x.strip()]
        episodes = []
        seen = set()
        for i, url_group in enumerate(url_groups):
            if not url_group:
                continue
            for ep in url_group.split('#'):
                parts = ep.split('$')
                if len(parts) < 2:
                    continue
                ep_name = parts[0]
                ep_url = parts[-1].strip()
                if not ep_url:
                    continue
                mark = ep_name.lower()
                if mark in seen:
                    continue
                seen.add(mark)
                episodes.append(f'{ep_name}${ep_url}')
        if not episodes:
            return
        play_froms.append(src_name)
        play_urls.append('#'.join(episodes))

    def _fetch_matches(self, source, name):
        """两步法：wd 搜同名 → 取 vod_id → detail 拉完整播放数据。
        兼容几乎所有 MacCMS 采集源，返回含 play 的详情（或搜索结果含 play）。"""
        # 第一步：wd 搜
        try:
            d1 = self._get(source, retry=False, timeout=2, ac='list', wd=name)
            if not d1 or not d1.get('list'):
                return None
            # 搜索结果若直接含 play 字段，直接用（省一步）
            for v in d1['list']:
                if _same_name(v.get('vod_name', ''), name) and v.get('vod_play_url'):
                    return {'list': [v]}
            # 第二步：detail 拉
            v1 = d1['list'][0]
            vid = str(v1.get('vod_id', ''))
            if vid:
                d2 = self._get(source, retry=False, timeout=2, ac='detail', ids=vid)
                if d2 and d2.get('list'):
                    v2 = d2['list'][0]
                    if v2.get('vod_play_url'):
                        return {'list': [v2]}
        except Exception:
            pass
        return None

    def _deduplicate_playlists(self, play_froms, play_urls):
        unique_froms = []
        unique_urls = []
        seen_names = set()
        seen_groups = set()
        for pf, pu in zip(play_froms, play_urls):
            n = (pf or '').lower()
            u = (pu or '').lower()
            if not n or not u:
                continue
            if n in seen_names or u in seen_groups:
                continue
            seen_names.add(n)
            seen_groups.add(u)
            unique_froms.append(pf)
            unique_urls.append(pu)
        return unique_froms, unique_urls

    def _is_valid_play_url(self, url):
        if not url or not isinstance(url, str):
            return False
        url_lower = url.lower().strip()
        if not url_lower.startswith(('http://', 'https://')):
            return False
        if 'm3u8' in url_lower or 'mp4' in url_lower:
            return True
        return False

    def playerContent(self, flag, id, vipFlags):
        url = str(id or '').strip()

        try:
            url = unquote(url)
        except Exception:
            pass

        if self._is_valid_play_url(url):
            return {'parse': 0, 'playUrl': '', 'url': url, 'header': self.header}

        if 'url=' in url:
            try:
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(url)
                params = parse_qs(parsed.query)
                if 'url' in params:
                    real_url = unquote(params['url'][0])
                    if self._is_valid_play_url(real_url):
                        return {'parse': 0, 'playUrl': '', 'url': real_url, 'header': self.header}
            except Exception:
                pass

        return {'parse': 1, 'playUrl': '', 'url': url, 'header': self.header}

    def isVideoFormat(self, url):
        if not url:
            return False
        url_lower = url.lower()
        return 'm3u8' in url_lower or 'mp4' in url_lower

    def manualVideoCheck(self):
        return False

    def destroy(self):
        self.sess.close()
        self.class_cache.clear()
        self.detail_cache.clear()
