let API_BASE = 'https://www.ixigua.com';
let LVIDEO_API = 'https://ib.snssdk.com/vapp/lvideo/api/info/';
let PLAY_API = 'https://vas.snssdk.com/video/openapi/v1/';
const PAGE_SIZE = 18;

// albumTypeList 期望值，用于滤掉串台内容（综艺串台成电视剧/电影最严重）
const ALBUM_TYPE = {
    dianshiju: 2, dianying: 1, dongman: 3, jilupian: 5, shaoer: 13, zongyi: 4
};
// 接口 filters.type：少儿必须传「儿童」，否则会串成电视剧
const CAT_NAME = {
    dianshiju: '电视剧', dianying: '电影', dongman: '动漫',
    jilupian: '纪录片', shaoer: '儿童', zongyi: '综艺'
};
const CATS = ['dianying', 'dianshiju', 'zongyi', 'dongman', 'jilupian', 'shaoer'];

// 综艺「真实子标签」：tag=全部类型 下只有 13% 是真综艺，其余全是串台的电视剧/电影。
// 实测各标签命中率（最新上线，扫 5 页）：
//   真人秀 100% / 脱口秀 95% / 搞笑 30% / 音乐 21% / 体育 33%(量太少)
//   全部类型、访谈、选秀、旅行、文化、亲子、游戏、新闻、其他 = 均 13% 且返回完全相同的
//   12 部，说明后端把它们一律当成「全部类型」处理，是无效标签，不纳入扇出。
const ZONGYI_TAGS = ['真人秀', '脱口秀', '搞笑', '音乐'];
// 综艺只有「最新上线」能翻出深页内容，热度最高/综合排序的新增都是 0
const ZONGYI_SORT = '最新上线';
const ZY_MAX_PAGE = 12;   // 单个标签最多翻到第几页
const ZY_IDLE_STOP = 2;   // 单个标签连续 N 页无新增就认定到底
// 搜索扫描时综艺只用高命中标签扇出（真人秀/脱口秀 覆盖绝大多数综艺搜索词），
// 其余分类用「全部类型」。分类浏览（fetchZongyiPage）仍用完整 ZONGYI_TAGS 以拉全片库。
const SCAN_TAGS = { zongyi: ['真人秀', '脱口秀'] };
const SCAN_MAX_PAGE = 12;

function getHeaders() {
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Referer': API_BASE + '/cinema/filter/dianshiju/',
        'Origin': API_BASE
    };
}

async function reqData(url, options) {
    try {
        let resp = await req(url, options);
        if (resp && resp.content) {
            return JSON.parse(resp.content);
        }
    } catch (e) { }
    return null;
}

// 副标题优先显示集数：bottomLabel 是官方集数文案（如「98集全」「更新至第1期」），
// 没有时按 totalEpisodes/latestSeq 自行拼，单集（电影等）才回退宣传语 subTitle。
function remarksOf(v) {
    let r = (v.bottomLabel || '').trim();
    if (!r) {
        let total = parseInt(v.totalEpisodes) || 0;
        let latest = parseInt(v.latestSeq) || 0;
        if (total > 1 || latest > 1) {
            r = (latest && total && latest < total)
                ? ('更新至第' + latest + '集')
                : ((total || latest) + '集全');
        } else {
            r = (v.subTitle || '').trim();
        }
    }
    return r;
}

function toVod(v) {
    // 付费内容由 vipControl 非空标识（如 {"vipType":1}），免费则为空 {}
    const isPaid = !!(v.vipControl && Object.keys(v.vipControl || {}).length);
    let rm = remarksOf(v);
    if (isPaid) rm = rm ? (rm + '·付费') : '付费';
    return {
        vod_id: String(v.albumId || ''),
        vod_name: v.title || '',
        vod_pic: (v.coverList && v.coverList.length) ? v.coverList[0].url : '',
        vod_remarks: rm,
        _types: (v.albumTypeList || []).map(Number),
        _actor: (v.actorList || []).join(','),
        _vip: isPaid ? '付费' : ''
    };
}

// 拉一页并按 albumType 过滤（expectType<=0 表示不过滤）
async function fetchPage(tid, pg, ext, expectType) {
    ext = ext || {};
    let payload = {
        pinyin: tid,
        filters: {
            type: CAT_NAME[tid],
            area: ext.area || '全部地区',
            tag: ext.tag || '全部类型',
            sort: ext.sort || '综合排序',
            paid: ext.paid || '全部资费'
        },
        offset: (Math.max(parseInt(pg) || 1, 1) - 1) * PAGE_SIZE,
        limit: PAGE_SIZE
    };
    let data = await reqData(API_BASE + '/api/cinema/filterv2/albums', {
        method: 'POST',
        headers: { ...getHeaders(), 'content-type': 'application/json' },
        body: JSON.stringify(payload)
    });
    if (!data || data.code !== 200 || !data.data || !data.data.albumList) return [];
    let rows = data.data.albumList.map(toVod).filter(v => v.vod_name && v.vod_id);
    if (expectType > 0) {
        rows = rows.filter(v => v._types.indexOf(expectType) !== -1);
    }
    return rows;
}

// 分页：过滤会减少条目，所以要连翻接口页直到凑够当前页
async function fetchCategoryPage(tid, pg, ext) {
    if (tid === 'zongyi') return await fetchZongyiPage(pg, ext);
    const expect = ALBUM_TYPE[tid] || 0;
    if (expect <= 0) return await fetchPage(tid, pg, ext, 0);
    const need = pg * PAGE_SIZE;
    let merged = [];
    const seen = new Set();
    for (let apiPage = 1; apiPage <= 30; apiPage++) {
        if (merged.length >= need) break;
        const rows = await fetchPage(tid, apiPage, ext, expect);
        if (!rows.length) break;
        for (const v of rows) {
            if (seen.has(v.vod_id)) continue;   // 接口会返回重复条目（如「英雄儿女」出现两次）
            seen.add(v.vod_id);
            merged.push(v);
        }
    }
    return merged.slice((pg - 1) * PAGE_SIZE, pg * PAGE_SIZE);
}

// 综艺专用：多标签扇出 + 会话内缓存 + 单标签「连续深拉」（关键！）。
// 实测发现 filterv2/albums 的分页游标是按「请求序列」维护的：对同一个 tag 连续
// 翻页完全正常（真人秀能拉到 100+ 部），但一旦 真人秀→脱口秀→搞笑… 这样交替
// 发请求，后面的 offset 请求就会返回被污染的错乱页（第 2 页起全变成 8 条、第 3 页
// 空）。所以这里对每个标签要「一口气连续拉到底 / 拉到够本页」再切下一个，绝不能
// 各标签逐页轮询。
const zyCache = new Map();
async function fetchZongyiPage(pg, ext) {
    ext = ext || {};
    const sort = ext.sort || ZONGYI_SORT;
    const userTag = ext.tag || '全部类型';
    // 用户明确选了子标签就只查该标签；选「全部类型」才扇出
    const tags = (userTag && userTag !== '全部类型') ? [userTag] : ZONGYI_TAGS;
    const key = [sort, userTag, ext.area || '', ext.paid || ''].join('|');
    if (!zyCache.has(key)) {
        zyCache.set(key, {
            items: [],
            seen: new Set(),
            cur: Object.create(null),  // tag -> 下一个要拉的接口页
            idle: Object.create(null),  // tag -> 连续无新增次数
            dead: new Set()
        });
    }
    const slot = zyCache.get(key);

    const p = Math.max(parseInt(pg) || 1, 1);
    const need = p * PAGE_SIZE;
    const MAX_FETCH = 24; // 单次调用最多发起的请求数，防止跳页时卡死；缓存跨调用保留会逐步补全

    let fetched = 0;
    let progressed = true;
    while (slot.items.length < need && progressed && fetched < MAX_FETCH) {
        progressed = false;
        for (const tag of tags) {
            if (slot.dead.has(tag)) continue;
            // 连续深拉当前标签，直到：本标签到底 / 请求预算用尽 / 已凑够本页
            while (fetched < MAX_FETCH) {
                const cur = slot.cur[tag] || 1;
                if (cur > ZY_MAX_PAGE) { slot.dead.add(tag); break; }
                const rows = await fetchPage('zongyi', cur, { ...ext, tag: tag, sort: sort }, ALBUM_TYPE.zongyi);
                fetched++;
                slot.cur[tag] = cur + 1;
                let gain = 0;
                for (const v of rows) {
                    if (slot.seen.has(v.vod_id)) continue;
                    slot.seen.add(v.vod_id);
                    slot.items.push(v);
                    gain++;
                }
                if (gain > 0) { progressed = true; slot.idle[tag] = 0; }
                else {
                    slot.idle[tag] = (slot.idle[tag] || 0) + 1;
                    if (slot.idle[tag] >= ZY_IDLE_STOP) { slot.dead.add(tag); break; }
                }
                if (slot.items.length >= need) break; // 够本页了，停手，下次 category 再续
            }
            if (slot.items.length >= need) break;
        }
    }
    return slot.items.slice((p - 1) * PAGE_SIZE, p * PAGE_SIZE);
}

function strip(v) {
    return { vod_id: v.vod_id, vod_name: v.vod_name, vod_pic: v.vod_pic, vod_remarks: v.vod_remarks };
}

// 资费筛选：全部资费=默认（接口实际返回免费内容）、免费、付费（vipControl 非空的内容）。
// 实测「全部资费」与「免费」返回完全相同，「付费」是另一批内容，筛选确实生效。
const PAID_FILTER = { "key": "paid", "name": "资费", "value": [{ "n": "全部资费", "v": "全部资费" }, { "n": "免费", "v": "免费" }, { "n": "付费", "v": "付费" }] };

const filtersConfig = {
    "dianshiju": [{"key": "area", "name": "地区", "value": [{"n": "全部地区", "v": "全部地区"}, {"n": "内地", "v": "内地"}, {"n": "韩国", "v": "韩国"}, {"n": "中国香港", "v": "中国香港"}, {"n": "中国台湾", "v": "中国台湾"}, {"n": "美国", "v": "美国"}, {"n": "日本", "v": "日本"}]}, {"key": "tag", "name": "类型", "value": [{"n": "全部类型", "v": "全部类型"}, {"n": "爱情", "v": "爱情"}, {"n": "古装", "v": "古装"}, {"n": "悬疑", "v": "悬疑"}, {"n": "喜剧", "v": "喜剧"}]}, {"key": "sort", "name": "排序", "value": [{"n": "综合排序", "v": "综合排序"}, {"n": "最新上线", "v": "最新上线"}, {"n": "热度最高", "v": "热度最高"}, {"n": "评分最高", "v": "评分最高"}]}, PAID_FILTER],
    "dianying": [{"key": "area", "name": "地区", "value": [{"n": "全部地区", "v": "全部地区"}, {"n": "内地", "v": "内地"}, {"n": "韩国", "v": "韩国"}, {"n": "中国香港", "v": "中国香港"}, {"n": "美国", "v": "美国"}]}, {"key": "tag", "name": "类型", "value": [{"n": "全部类型", "v": "全部类型"}, {"n": "喜剧", "v": "喜剧"}, {"n": "动作", "v": "动作"}, {"n": "科幻", "v": "科幻"}]}, {"key": "sort", "name": "排序", "value": [{"n": "综合排序", "v": "综合排序"}, {"n": "最新上线", "v": "最新上线"}, {"n": "热度最高", "v": "热度最高"}]}, PAID_FILTER],
    "dongman": [{"key": "area", "name": "地区", "value": [{"n": "全部地区", "v": "全部地区"}, {"n": "内地", "v": "内地"}, {"n": "日本", "v": "日本"}, {"n": "美国", "v": "美国"}]}, {"key": "sort", "name": "排序", "value": [{"n": "综合排序", "v": "综合排序"}, {"n": "最新上线", "v": "最新上线"}, {"n": "热度最高", "v": "热度最高"}]}, PAID_FILTER],
    // 综艺「综合排序」必然串台成电视剧，所以该项实际下发「最新上线」；
    // 子标签只列实测有效的（全部类型/访谈/选秀等后端当无效标签处理，会返回同一批串台内容）
    "zongyi": [{"key": "tag", "name": "类型", "value": [{"n": "全部类型", "v": "全部类型"}, {"n": "真人秀", "v": "真人秀"}, {"n": "脱口秀", "v": "脱口秀"}, {"n": "搞笑", "v": "搞笑"}, {"n": "音乐", "v": "音乐"}]}, {"key": "sort", "name": "排序", "value": [{"n": "最新上线", "v": "最新上线"}, {"n": "热度最高", "v": "热度最高"}, {"n": "评分最高", "v": "评分最高"}]}, PAID_FILTER],
    "jilupian": [{"key": "sort", "name": "排序", "value": [{"n": "综合排序", "v": "综合排序"}, {"n": "最新上线", "v": "最新上线"}, {"n": "热度最高", "v": "热度最高"}]}, PAID_FILTER],
    "shaoer": [{"key": "sort", "name": "排序", "value": [{"n": "综合排序", "v": "综合排序"}, {"n": "最新上线", "v": "最新上线"}, {"n": "热度最高", "v": "热度最高"}]}, PAID_FILTER]
};

function getTypeName(tid) {
    return CAT_NAME[tid] || '电视剧';
}

async function init(cfg) {
    return {};
}

async function home() {
    let classes = [
        { type_name: '电视剧', type_id: 'dianshiju' },
        { type_name: '电影', type_id: 'dianying' },
        { type_name: '动漫', type_id: 'dongman' },
        { type_name: '纪录片', type_id: 'jilupian' },
        { type_name: '少儿', type_id: 'shaoer' },
        { type_name: '综艺', type_id: 'zongyi' }
    ];
    return JSON.stringify({
        class: classes,
        filters: filtersConfig
    });
}

async function homeVod() {
    let rows = await fetchPage('dianshiju', 1, { sort: '热度最高' }, ALBUM_TYPE.dianshiju);
    return JSON.stringify({ list: rows.slice(0, PAGE_SIZE).map(strip) });
}

async function category(tid, pg, filter, extend) {
    const p = Math.max(parseInt(pg) || 1, 1);
    let ext = extend || {};
    if (typeof ext === 'string') {
        try { ext = ext ? JSON.parse(ext) : {}; } catch (e) { ext = {}; }
    }
    // 综艺「综合排序」会整页串成电视剧
    if (tid === 'zongyi' && (!ext.sort || ext.sort === '综合排序')) ext.sort = '最新上线';

    const list = await fetchCategoryPage(tid, p, ext);
    return JSON.stringify({
        list: list.map(strip),
        page: p,
        pagecount: list.length === PAGE_SIZE ? p + 1 : p
    });
}

async function detail(id) {
    let url = LVIDEO_API + '?album_id=' + id + '&aid=1768&format=json&query_type=0';
    let data = await reqData(url, {
        headers: {
            'User-Agent': 'okhttp/3.12.1',
            'Accept': 'application/json',
            'Referer': 'https://m.ixigua.com/'
        }
    });

    if (!data || !data.album) return JSON.stringify({ list: [] });

    let album = data.album;
    let tags = (album.tag_list || []).join('/');
    let area = (album.area_list || []).join('/');
    let director = (album.director_list || []).map(d => d.name).join('/');
    let actor = (album.actor_list || []).map(a => a.name).join('/');
    let pic = album.cover_list && album.cover_list.length ? album.cover_list[0].url : '';
    let eps = album.total_episodes || album.latest_seq || 1;

    let cells = [];
    if (data.block_list) {
        for (let block of data.block_list) {
            if (block.type === 1001) {
                cells = block.cells || [];
                break;
            }
        }
    }
    if (cells.length === 0 && data.episode) {
        cells = [{ episode: data.episode }];
    }

    const clarities = [
        { id: '4k', name: '4K超清' },
        { id: '1080p', name: '1080P高清' },
        { id: '720p', name: '720P' },
        { id: '480p', name: '480P' },
        { id: '360p', name: '360P' }
    ];

    let playFroms = [];
    let playUrlsGroups = [];

    for (let c of clarities) {
        playFroms.push(c.name);
        let urls = [];
        for (let cell of cells) {
            let ep = cell.episode || {};
            let ep_id = ep.episode_id || '';
            let seq = ep.seq;
            let title = ep.title || ep.name || (seq ? '第' + seq + '集' : '正片');

            let base_id = id;
            if (!ep_id) {
                let vi = ep.video_info || {};
                let vid = vi.vid || '';
                if (vid) {
                    base_id = id + '?vid=' + vid;
                }
            } else {
                base_id = id + '?id=' + ep_id;
            }

            urls.push(title + '$' + base_id + '@' + c.id);
        }
        playUrlsGroups.push(urls.join('#'));
    }

    let vod = {
        vod_id: String(id),
        vod_name: album.title || '',
        vod_pic: pic,
        type_name: tags,
        vod_year: album.year || '',
        vod_area: area,
        vod_remarks: eps > 1 ? eps + '集' : '',
        vod_actor: actor,
        vod_director: director,
        vod_content: album.intro || '暂无简介',
        vod_play_from: playFroms.join('$$$'),
        vod_play_url: playUrlsGroups.join('$$$')
    };

    return JSON.stringify({ list: [vod] });
}

function b64decodeIf(s) {
    if (!s) return '';
    if (s.startsWith('http://') || s.startsWith('https://')) return s;
    try {
        if (typeof atob === 'function') return atob(s);
        const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=';
        let output = '';
        s = String(s).replace(/=+$/, '');
        for (let bc = 0, bs, buffer, idx = 0; buffer = s.charAt(idx++); ~buffer && (bs = bc % 4 ? bs * 64 + buffer : buffer, bc++ % 4) ? output += String.fromCharCode(255 & bs >> (-2 * bc & 6)) : 0) {
            buffer = chars.indexOf(buffer);
        }
        return output;
    } catch (e) {
        return '';
    }
}

async function play(flag, id) {
    let album_id = id;
    let episode_id = '';
    let vid = '';
    let targetQuality = '';

    if (id.indexOf('@') !== -1) {
        let parts = id.split('@');
        targetQuality = parts.pop();
        id = parts.join('@');
    }

    if (id.indexOf('?id=') !== -1) {
        let parts = id.split('?id=');
        album_id = parts[0];
        episode_id = parts[1];
    } else if (id.indexOf('?vid=') !== -1) {
        let parts = id.split('?vid=');
        album_id = parts[0];
        vid = parts[1];
    }

    let lvideo_url = LVIDEO_API + '?album_id=' + album_id + '&aid=1768&format=json&query_type=0';
    if (episode_id) lvideo_url += '&episode_id=' + episode_id;

    let data = await reqData(lvideo_url, {
        headers: {
            'User-Agent': 'okhttp/3.12.1',
            'Accept': 'application/json',
            'Referer': 'https://m.ixigua.com/'
        }
    });

    let vi = null;
    let candidates = [];
    if (data && data.episode) candidates.push(data.episode);
    if (data && data.block_list) {
        for (let block of data.block_list) {
            if (block.type === 1001 && block.cells) {
                for (let cell of block.cells) {
                    if (cell.episode) candidates.push(cell.episode);
                }
            }
        }
    }

    if (episode_id) {
        vi = candidates.find(ep => ep.episode_id == episode_id)?.video_info || {};
    } else if (vid) {
        vi = candidates.map(ep => ep.video_info || {}).find(ev => ev.vid == vid) || {};
    } else if (candidates.length > 0) {
        vi = candidates[0].video_info || {};
    }

    if (!vi || !vi.vid || !vi.auth_token || !vi.business_token) {
        return JSON.stringify({ parse: 1, jx: 1, url: 'https://www.ixigua.com/' + id });
    }

    let play_url_api = PLAY_API + '?action=GetPlayInfo&video_id=' + vi.vid + '&nobase64=1&ptoken=' + vi.business_token + '&vfrom=xgplayer';
    let playData = await reqData(play_url_api, {
        headers: {
            'User-Agent': 'Mozilla/5.0',
            'Authorization': vi.auth_token,
            'Origin': API_BASE,
            'Referer': API_BASE + '/',
            'Accept': 'application/json'
        }
    });

    let realUrl = '';
    if (playData && playData.data && playData.data.video_list) {
        let vl = playData.data.video_list;
        let best = null;
        let exactMatch = null;
        let best_score = -1;

        for (let k in vl) {
            let item = vl[k];
            if (typeof item !== 'object') continue;
            let def = (item.definition || '').toLowerCase();

            if (targetQuality && def === targetQuality) {
                exactMatch = item;
                break;
            }

            let score = parseInt(item.vheight) || 0;
            if (def === '4k' || def === 'hdr') score = 4000;
            else if (def === '1080p') score = 1080;

            if (score > best_score) {
                best_score = score;
                best = item;
            }
        }

        best = exactMatch || best;

        if (best) {
            let main = best.main_url || best.backup_url_1 || '';
            realUrl = b64decodeIf(main);
        }
    }

    if (realUrl) {
        return JSON.stringify({
            parse: 0,
            jx: 0,
            url: realUrl,
            header: {
                'User-Agent': 'Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36',
                'Referer': API_BASE + '/',
                'Origin': API_BASE
            }
        });
    }

    return JSON.stringify({ parse: 1, jx: 1, url: id });
}

// ---------- 搜索：片库索引 + 预算扫描 ----------
// 官方搜索接口 /api/searchv2/lvideo 已被 Argus 签名保护（带 ixigua 域名 Referer
// 一律返回 SPA 网页壳），只能用筛选接口做片库扫描兜底。原实现只扫 4 个分类的
// 第 1 页（72 部），漏掉纪录片/少儿，且无缓存无翻页。
// 索引用「分类|标签」为键推进：综艺必须按子标签扇出才扫得到内容，
// 用「全部类型」扫 12 页也只有 12 部真综艺。
const searchIndex = new Map(); // albumId -> vod（跨会话累积，全站片库索引）
const searchCur = new Map();   // "tid|tag" -> 下一个要拉的接口页
const searchIdle = new Map();  // "tid|tag" -> 连续无新增次数
const searchDead = new Set();  // 已扫到尽头

function scanKeys() {
    const out = [];
    for (const tid of CATS) {
        for (const tag of (SCAN_TAGS[tid] || ['全部类型'])) out.push(tid + '|' + tag);
    }
    return out;
}

function pageOut(hits, p, size) {
    size = size || 20;
    const seen = new Set();
    const out = [];
    for (const v of hits) {
        if (!v.vod_id || seen.has(v.vod_id)) continue;
        seen.add(v.vod_id);
        out.push(strip(v));
    }
    const start = (p - 1) * size;
    const pagecount = Math.max(Math.ceil(out.length / size), 1);
    return JSON.stringify({ list: out.slice(start, start + size), page: p, pagecount: pagecount });
}

async function search(wd, quick, pg) {
    const p = Math.max(parseInt(pg) || 1, 1);
    const key = (wd || '').trim().toLowerCase();
    if (!key) return JSON.stringify({ list: [], page: p, pagecount: 1 });

    const budget = quick ? 5000 : 12000; // 毫秒，超时先返回已找到的，避免壳判失败
    const deadline = Date.now() + budget;
    const hit = v => (v.vod_name || '').toLowerCase().indexOf(key) !== -1
        || (v._actor || '').toLowerCase().indexOf(key) !== -1;

    // 1) 先查本地索引（不联网，秒回）
    let hits = [...searchIndex.values()].filter(hit);
    if (hits.length >= Math.max(p * 20, 6)) return pageOut(hits, p);

    // 2) 预算内继续扫描扩充索引（不过滤类型，扫原始页以最大化覆盖）。
    // 同样要避免「交替发请求污染分页游标」：每个 key 一次性连续深拉（同 key 顺序
    // 请求，游标不受污染），处理完一个 key 再处理下一个，绝不逐 key 轮询。
    // 每个分类每次搜索最多深拉 perKey 页，避免单一大分类（如电影库几十页）把
    // 预算耗尽、导致其他分类扫不到；索引跨多次搜索累积，翻页/二次搜索会补全。
    const perKey = quick ? 3 : 6;
    const keys = scanKeys();
    for (const k of keys) {
        if (Date.now() > deadline) break;
        if (searchDead.has(k)) continue;
        const sep = k.indexOf('|');
        const tid = k.slice(0, sep);
        const tag = k.slice(sep + 1);
        const sort = tid === 'zongyi' ? ZONGYI_SORT : '综合排序';
        let pages = 0;
        while (pages < perKey && Date.now() < deadline) {
            const cur = searchCur.get(k) || 1;
            if (cur > SCAN_MAX_PAGE) { searchDead.add(k); break; }
            const rows = await fetchPage(tid, cur, { sort: sort, tag: tag }, 0);
            searchCur.set(k, cur + 1);
            pages++;
            let gain = 0;
            for (const v of rows) {
                if (!searchIndex.has(v.vod_id)) { searchIndex.set(v.vod_id, v); gain++; }
            }
            hits = [...searchIndex.values()].filter(hit);
            if (hits.length >= Math.max(p * 20, 6)) return pageOut(hits, p); // 够本页就返回
            if (gain === 0) {
                const idle = (searchIdle.get(k) || 0) + 1;
                searchIdle.set(k, idle);
                if (idle >= 2) { searchDead.add(k); break; }
            } else {
                searchIdle.set(k, 0);
            }
        }
    }

    hits = [...searchIndex.values()].filter(hit);
    return pageOut(hits, p);
}

export function __jsEvalReturn() {
    return {
        init,
        home,
        homeVod,
        category,
        detail,
        play,
        search
    };
}
