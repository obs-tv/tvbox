import sys
import re
import json
import base64
import requests
 
sys.path.append('..')
from base.spider import Spider as BaseSpider
 
 
class Spider(BaseSpider):
    author = "集多"

    def getName(self):
        return "酷狗音乐[集多]"
 
    def init(self, extend=""):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16 like Mac OS X) '
                          'AppleWebKit/605.1.15 (KHTML, like Gecko) '
                          'Version/16 Mobile/15E148 Safari/604.1',
            'Referer': 'https://www.kugou.com/',
            'Origin': 'https://www.kugou.com',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Accept': 'application/json, text/plain, */*',
        })
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass
        self.log("酷狗音乐初始化完成")
 
    def destroy(self):
        if hasattr(self, 'session'):
            self.session.close()
 
                              
    def homeContent(self, filter):
        classes = [
            {"type_id": "1", "type_name": "🔥 热门榜"},
            {"type_id": "2", "type_name": "🌍 全球榜"},
            {"type_id": "5", "type_name": "🎵 特色榜"},
            {"type_id": "region:zh", "type_name": "🇨🇳 华语"},
            {"type_id": "region:west", "type_name": "🇺🇸 欧美"},
            {"type_id": "region:kr", "type_name": "🇰🇷 韩国"},
            {"type_id": "region:jp", "type_name": "🇯🇵 日本"},
        ]
        return {"class": classes, "filters": {}}

    def homeVideoContent(self):
        return self.categoryContent("1", "1", None, {})

                                 
    def categoryContent(self, tid, pg, filter, ext):
        # 对齐网易：分类下列出榜单「剧集」，点进详情后歌曲才是分集，便于自动连播
        return self._rank_list(tid, pg)

    def _rank_list(self, tid, pg):
        if pg != "1":
            return {"list": [], "page": pg, "pagecount": 0, "limit": 0, "total": 0}
        rank_list = self._get_rank_list()
        if not rank_list:
            return {"list": [], "page": pg, "pagecount": 0, "limit": 0, "total": 0}

        region_ranks = {
            "region:zh": [("🇨🇳", "内地榜"), ("🇭🇰", "香港地区榜"), ("🇹🇼", "台湾地区榜"), ("🇨🇳", "粤语金曲榜")],
            "region:west": [("🇺🇸", "欧美榜"), ("🇺🇸", "欧美金曲榜"), ("🇺🇸", "美国BillBoard榜"), ("🇬🇧", "英国单曲榜")],
            "region:kr": [("🇰🇷", "韩国榜"), ("🇰🇷", "韩国Melon音乐榜")],
            "region:jp": [("🇯🇵", "日本榜"), ("🇯🇵", "日本公信榜"), ("🇯🇵", "日本SS榜")],
        }
        labels = {}
        if tid in region_ranks:
            labels = {name: flag for flag, name in region_ranks[tid]}
            sub_ranks = [item for item in rank_list if item.get("rankname") in labels]
        else:
            try:
                classify = int(tid)
            except (TypeError, ValueError):
                return {"list": [], "page": pg, "pagecount": 0, "limit": 0, "total": 0}
            sub_ranks = []
            for item in rank_list:
                c = item.get("classify", 0)
                if classify == 1 and c == 1:
                    sub_ranks.append(item)
                elif classify == 2 and c in (2, 4):
                    sub_ranks.append(item)
                elif classify == 5 and c not in (1, 2):
                    sub_ranks.append(item)
                elif classify == c:
                    sub_ranks.append(item)

        video_list = []
        for item in sub_ranks:
            rank_cid = str(item.get("rank_cid", ""))
            rankname = item.get("rankname", "")
            img = (item.get("imgurl") or "").replace("{size}", "400")
            if rank_cid and rankname:
                flag = labels.get(rankname, "🏆")
                # 不设 vod_tag=folder：直接当一部「剧」，详情里歌曲=分集
                video_list.append({
                    "vod_id": f"kugou#{rank_cid}",
                    "vod_name": f"{flag} {rankname}",
                    "vod_pic": img,
                    "vod_remarks": "榜单连播",
                })
        return {
            "list": video_list,
            "page": pg, "pagecount": 1,
            "limit": len(video_list), "total": len(video_list)
        }
 
    def detailContent(self, ids):
        vod_id = str(ids[0] if isinstance(ids, list) else ids)
        rank_id = ""
        rank_page = "1"
        selected_hash = ""
        album_id = ""
        mvhash_from_id = ""
        pic_from_id = ""

        if vod_id.startswith("kugou#"):
            rank_id = vod_id.replace("kugou#", "", 1)
        else:
            parts = vod_id.split("|")
            selected_hash = parts[0] if len(parts) > 0 else ""
            album_id = parts[1] if len(parts) > 1 else ""
            mvhash_from_id = parts[2] if len(parts) > 2 else ""
            pic_from_id = parts[3] if len(parts) > 3 else ""
            if len(parts) > 4 and parts[4].startswith("rank:"):
                rank_id = parts[4].split(":", 1)[1]
                rank_page = parts[5] if len(parts) > 5 and parts[5] else "1"

        tracks = []

        def build_track(song, fallback_hash="", fallback_album="", fallback_mv="", fallback_pic=""):
            try:
                h = self._extract_best_hash(song) or fallback_hash
                if not h:
                    return None
                a = self._get_album_id(song) or fallback_album
                mv = self._get_mv_hash(song) or fallback_mv
                pic = self._get_song_cover(song) or fallback_pic
                name = self._get_song_name(song) or song.get("songName") or song.get("songname") or "未知歌曲"
                singer = self._get_singer_name(song)
                if not singer or singer == "未知歌手":
                    singer = self._extract_singer_from_info(song)
                if not singer:
                    singer = "未知歌手"
                return {"hash": h, "album_id": a, "mvhash": mv, "pic": pic, "name": name, "singer": singer, "quality": self._get_quality_hashes(song, h)}
            except Exception as e:
                self.log(f"构建歌曲失败: {e}")
                return None

        if rank_id:
            songs, _ = self._get_all_rank_songs(rank_id)
            for song in songs:
                track = build_track(song)
                if track:
                    tracks.append(track)

        if not tracks and selected_hash:
            song_info = self._get_song_info(selected_hash, album_id)
            if not song_info:
                song_info = self._get_song_info(selected_hash, "")
            if not song_info:
                song_info = {}
            track = build_track(song_info, selected_hash, album_id, mvhash_from_id, pic_from_id)
            if track:
                tracks.append(track)

        if not tracks:
            return {"list": []}

        for origin_idx, item in enumerate(tracks, 1):
            item["_origin_idx"] = origin_idx

        current = tracks[0]
        current_index = 0
        if selected_hash:
            for idx, item in enumerate(tracks):
                if item.get("hash") == selected_hash or selected_hash in item.get("quality", {}).values():
                    current = item
                    current_index = idx
                    break
        ordered_tracks = tracks
        # 标准音质优先：无损/高清在酷狗常需付费，免费档更容易直出。
        quality_order = ["标准音质", "高清音质", "无损音质"]
        # 整榜当剧：不要「当前播放」单集线路，直接多集列表才能自动连播
        is_rank_series = bool(rank_id) and not selected_hash

        play_from_list = []
        play_url_list = []
        if not is_rank_series:
            current_play_hash = ""
            if selected_hash and selected_hash in (current.get("quality") or {}).values():
                current_play_hash = selected_hash
            if not current_play_hash:
                for label in quality_order:
                    h = current.get("quality", {}).get(label)
                    if h:
                        current_play_hash = h
                        break
            if not current_play_hash:
                current_play_hash = current.get("hash", "")
            if current_play_hash:
                play_from_list.append("当前播放")
                play_url_list.append(
                    f"{self._episode_title(current.get('_origin_idx', 1), current)}$"
                    f"{self._pack_play_id(current_play_hash, current.get('album_id', ''), current.get('pic', ''), current.get('name', ''), current.get('singer', ''), current.get('quality'))}"
                )

        for label in quality_order:
            episodes = []
            seen = set()
            for idx, item in enumerate(ordered_tracks, 1):
                h = item.get("quality", {}).get(label)
                if not h or h in seen:
                    continue
                seen.add(h)
                title = self._episode_title(idx, item)
                play_id = self._pack_play_id(
                    h, item.get("album_id", ""), item.get("pic", ""),
                    item.get("name", ""), item.get("singer", ""), item.get("quality"),
                )
                episodes.append(f"{title}${play_id}")
            if episodes:
                play_from_list.append(label)
                play_url_list.append("#".join(episodes))

        mv_episodes = []
        seen_mv = set()
        for idx, item in enumerate(ordered_tracks, 1):
            mv = item.get("mvhash") or ""
            if mv and mv not in seen_mv:
                seen_mv.add(mv)
                title = self._episode_title(idx, item)
                mv_episodes.append(f"{title}${self._pack_mv_id(mv, item.get('pic', ''), item.get('name', ''), item.get('singer', ''))}")
        if mv_episodes:
            play_from_list.append("MV")
            play_url_list.append("#".join(mv_episodes))

        if not play_from_list:
            play_from_list.append("标准音质")
            play_url_list.append(
                f"{self._episode_title(1, current)}$"
                f"{self._pack_play_id(current.get('hash', ''), current.get('album_id', ''), current.get('pic', ''), current.get('name', ''), current.get('singer', ''), current.get('quality'))}"
            )

        pic = current.get("pic") or pic_from_id
        album = ""
        rank_title = ""
        if rank_id:
            try:
                for item in self._get_rank_list():
                    if str(item.get("rank_cid", "")) == str(rank_id):
                        rank_title = item.get("rankname") or ""
                        if not pic:
                            pic = (item.get("imgurl") or "").replace("{size}", "400")
                        break
            except Exception:
                pass
        if selected_hash and not rank_id:
            info = self._get_song_info(selected_hash, album_id) or {}
            album = info.get("albumName") or info.get("album_name") or ""

        if is_rank_series and rank_title:
            vod_name = rank_title
            vod_content = f"酷狗榜单：{rank_title}\n共 {len(tracks)} 首，按分集连播"
            vod_actor = "酷狗音乐"
        else:
            vod_name = current.get("name") or "酷狗音乐"
            vod_content = f"歌手：{current.get('singer', '未知歌手')}\n专辑：{album}\n歌曲数：{len(tracks)}"
            vod_actor = current.get("singer", "未知歌手")

        video_detail = {
            "vod_id": f"{vod_id}|focus:{selected_hash or current.get('hash', '')}",
            "vod_name": vod_name,
            "vod_pic": pic,
            "vod_content": vod_content,
            "vod_actor": vod_actor,
            "vod_remarks": f"共{len(tracks)}首 | 线路：{' / '.join(play_from_list)}",
            "vod_play_from": "$$$".join(play_from_list),
            "vod_play_url": "$$$".join(play_url_list),
            "vod_play_index": current_index + 1,
            "play_index": current_index,
        }
        return {"list": [video_detail]}
 
    def playerContent(self, flag, id, vipFlags):
        meta = {}
        if flag == "MV":
            url = id
            if "$" in id:
                _, url = id.split("$", 1)
            if url.startswith("mvb:"):
                meta = self._unpack_play_id(url)
                mv_urls = self._get_mv_urls(meta.get("hash", ""))
                url = ""
                for q in ["sq", "rq", "le"]:
                    if q in mv_urls:
                        url = mv_urls[q]
                        break
            elif url.startswith("mv:"):
                mv_urls = self._get_mv_urls(url[3:])
                url = ""
                for q in ["sq", "rq", "le"]:
                    if q in mv_urls:
                        url = mv_urls[q]
                        break
            if not url:
                return {"parse": 0, "url": "", "msg": "MV地址为空"}
            result = {
                "parse": 0, "url": url,
                "header": {
                    "User-Agent": self.session.headers["User-Agent"],
                    "Referer": "https://www.kugou.com/"
                }
            }
            self._apply_player_meta(result, meta)
            return result

        play_id = id
        if "$" in id:
            _, play_id = id.split("$", 1)
        meta = self._unpack_play_id(play_id)
        hash_val = meta.get("hash", "")
        album_id = meta.get("album_id", "")
        if not hash_val:
            parts = play_id.split("|")
            hash_val = parts[0]
            album_id = parts[1] if len(parts) > 1 else ""
        if not hash_val and not (meta.get("name") or ""):
            return {"parse": 0, "url": "", "msg": "缺少hash"}

        play_url, song_info, referer = self._resolve_audio(
            hash_val, album_id, meta.get("name", ""), meta.get("singer", ""), meta.get("quality") or {}
        )
        if not play_url:
            return {"parse": 0, "url": "", "msg": "该歌曲需要付费或暂无播放资源"}

        subs = []
        lrc_hash = (song_info or {}).get("hash") or hash_val
        if lrc_hash:
            lrc = self._get_lyric(lrc_hash)
            if lrc:
                ssa = self._create_ssa_subtitle(lrc)
                if ssa:
                    ssa_b64 = base64.b64encode(ssa.encode('utf-8')).decode('utf-8')
                    subs.append({
                        "name": "歌词",
                        "url": f"data:text/x-ssa;base64,{ssa_b64}",
                        "format": "text/x-ssa",
                        "selected": True
                    })

        result = {
            "parse": 0, "jx": 0, "url": play_url,
            "music_player": 1,
            "header": {
                "User-Agent": self.session.headers["User-Agent"],
                "Referer": referer or "https://www.kugou.com/"
            },
            "subs": subs
        }
        self._apply_player_meta(result, meta)
        return result
 
    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if pg else 1
        songs = self._search_songs(key, page=page, pagesize=20)
        if not songs:
            return {"list": [], "page": pg, "pagecount": 0, "limit": 0, "total": 0}
        video_list = []
        for song in songs:
            hash_val = self._extract_best_hash(song)
            if not hash_val:
                continue
            name = self._get_song_name(song)
            singer = self._get_singer_name(song)
            pic = self._get_song_cover(song)
            album_id = self._get_album_id(song)
            mvhash = self._get_mv_hash(song)
            vod_id = f"{hash_val}|{album_id}|{mvhash}|{pic}"
            video_list.append({
                "vod_id": vod_id,
                "vod_name": name,
                "vod_pic": pic,
                "vod_remarks": singer,
            })
        return {
            "list": video_list,
            "page": pg, "pagecount": page + 1 if len(video_list) >= 20 else page,
            "limit": len(video_list), "total": len(video_list)
        }
 
                                  
    def _get_rank_list(self):
        url = "http://mobilecdnbj.kugou.com/api/v3/rank/list"
        params = {
            "version": "9108", "plat": "0", "showtype": "2",
            "parentid": "0", "apiver": "6", "area_code": "1",
            "withsong": "0", "with_res_tag": "0",
        }
        try:
            resp = self.session.get(url, params=params, timeout=(5, 15))
            resp.raise_for_status()
            return resp.json().get("data", {}).get("info", []) or []
        except Exception as e:
            self.log(f"获取榜单列表失败: {e}")
            return []
 

    def _get_all_rank_songs(self, rank_id, pagesize=100, max_pages=30):
        songs = []
        seen = set()
        total = 0
        page = 1
        while page <= max_pages:
            data = self._get_rank_songs(rank_id, page=page, pagesize=pagesize)
            batch = data.get("songs", []) or []
            try:
                total = max(total, int(data.get("total") or 0))
            except Exception:
                total = total or 0
            if not batch:
                break
            for song in batch:
                h = self._extract_best_hash(song)
                key = h or json.dumps(song, ensure_ascii=False, sort_keys=True)
                if key in seen:
                    continue
                seen.add(key)
                songs.append(song)
            if total and len(songs) >= total:
                break
            if len(batch) < pagesize:
                break
            page += 1
        self.log(f"榜单{rank_id}加载歌曲 {len(songs)}/{total or len(songs)} 首")
        return songs, total or len(songs)

    def _pack_play_id(self, hash_val, album_id="", pic="", name="", singer="", quality=None):
        data = {
            "hash": hash_val or "",
            "album_id": album_id or "",
            "pic": pic or "",
            "name": name or "",
            "singer": singer or "",
        }
        if isinstance(quality, dict) and quality:
            data["quality"] = {k: v for k, v in quality.items() if v}
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return "song:" + base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")

    def _pick_url_from_song_info(self, song_info):
        if not song_info or song_info.get("status") != 1:
            return ""
        play_url = song_info.get("url") or ""
        if not play_url:
            backup = song_info.get("backup_urls") or song_info.get("backup_url")
            if isinstance(backup, list) and backup:
                play_url = backup[0]
            elif isinstance(backup, str) and backup:
                play_url = backup
        return play_url if isinstance(play_url, str) and play_url.startswith("http") else ""

    def _resolve_audio(self, hash_val, album_id="", name="", singer="", quality=None):
        """酷狗免费直链优先；付费墙则酷我→抖音→iTunes 试听兜底。"""
        candidates = []
        for h in [hash_val]:
            if h and h not in candidates:
                candidates.append(h)
        for label in ("标准音质", "高清音质", "无损音质"):
            h = (quality or {}).get(label)
            if h and h not in candidates:
                candidates.append(h)
        if isinstance(quality, dict):
            for h in quality.values():
                if h and h not in candidates:
                    candidates.append(h)

        for h in candidates:
            info = self._get_song_info(h, album_id) if album_id else None
            if not info:
                info = self._get_song_info(h, "")
            url = self._pick_url_from_song_info(info)
            if url:
                return url, info, "https://www.kugou.com/"

        fb = self._vip_audio_fallback(name, singer)
        if fb:
            return fb[0], None, fb[1]
        return "", None, "https://www.kugou.com/"

    def _norm_match_text(self, text):
        text = str(text or "").lower()
        text = re.sub(r"[\s\-_/\\|·•\.\,，。！!？?（）()\[\]【】《》\"'“”‘’]", "", text)
        return text

    def _best_kwyy_index(self, listing, name, singer=""):
        best_i, best_score = 1, -1
        n_name = self._norm_match_text(name)
        n_singer = self._norm_match_text(singer)
        for line in str(listing or "").splitlines():
            m = re.match(r"(\d+)\.\s*(.+)$", line.strip())
            if not m:
                continue
            idx = int(m.group(1))
            title = m.group(2)
            n_title = self._norm_match_text(title)
            score = 0
            if n_name and n_name in n_title:
                score += 10
            elif name and name in title:
                score += 8
            if n_singer and n_singer in n_title:
                score += 5
            elif singer and singer in title:
                score += 3
            if score > best_score:
                best_score, best_i = score, idx
        return best_i if best_score > 0 else 1

    def _vip_audio_fallback(self, name, singer=""):
        name = (name or "").strip()
        singer = (singer or "").strip()
        if not name:
            return None
        url = self._fallback_kwyy(name, singer)
        if url:
            return url, "https://www.kuwo.cn/"
        url = self._fallback_dyyy(name, singer)
        if url:
            return url, "https://www.douyin.com/"
        url = self._fallback_itunes(name, singer)
        if url:
            return url, "https://itunes.apple.com/"
        return None

    def _fallback_kwyy(self, name, singer=""):
        queries = []
        if singer:
            queries.append(f"{name} {singer}")
        queries.append(name)
        for q in queries:
            try:
                resp = self.session.get(
                    "http://www.yx520.ltd/API/kwyy/api.php",
                    params={"msg": q, "a": "10", "n": "1"},
                    timeout=(5, 15),
                )
                data = resp.json()
                if str(data.get("code")) != "200":
                    continue
                n = self._best_kwyy_index(data.get("name") or "", name, singer)
                if n != 1:
                    resp = self.session.get(
                        "http://www.yx520.ltd/API/kwyy/api.php",
                        params={"msg": q, "a": "10", "n": str(n)},
                        timeout=(5, 15),
                    )
                    data = resp.json()
                url = data.get("url") or ""
                if isinstance(url, str) and url.startswith("http"):
                    return url
            except Exception as e:
                self.log(f"酷我兜底失败: {e}")
        return ""

    def _fallback_dyyy(self, name, singer=""):
        keyword = f"{name} {singer}".strip() if singer else name
        try:
            resp = self.session.get(
                "http://www.yx520.ltd/API/dyyy/api.php",
                params={"msg": keyword},
                timeout=(5, 15),
            )
            data = resp.json()
            items = data.get("data") or []
            if not isinstance(items, list) or not items:
                return ""
            n_name = self._norm_match_text(name)
            picked = None
            for it in items:
                title = str(it.get("title") or "")
                if n_name and n_name in self._norm_match_text(title):
                    picked = it
                    break
                if name and name in title:
                    picked = it
                    break
            if not picked:
                picked = items[0]
            url = picked.get("url") or ""
            return url if isinstance(url, str) and url.startswith("http") else ""
        except Exception as e:
            self.log(f"抖音兜底失败: {e}")
            return ""

    def _fallback_itunes(self, name, singer=""):
        term = f"{name} {singer}".strip() if singer else name
        try:
            resp = self.session.get(
                "https://itunes.apple.com/search",
                params={"term": term, "limit": 1, "media": "music", "country": "cn"},
                timeout=(5, 15),
            )
            results = (resp.json() or {}).get("results") or []
            if not results:
                return ""
            url = results[0].get("previewUrl") or ""
            return url if isinstance(url, str) and url.startswith("http") else ""
        except Exception as e:
            self.log(f"iTunes兜底失败: {e}")
            return ""

    def _pack_mv_id(self, mv_hash, pic="", name="", singer=""):
        data = {"hash": mv_hash or "", "album_id": "", "pic": pic or "", "name": name or "", "singer": singer or ""}
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return "mvb:" + base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")

    def _unpack_play_id(self, play_id):
        prefix = ""
        if play_id.startswith("song:"):
            prefix = "song:"
        elif play_id.startswith("mvb:"):
            prefix = "mvb:"
        if not prefix:
            return {}
        try:
            raw = play_id[len(prefix):]
            raw += "=" * ((4 - len(raw) % 4) % 4)
            data = json.loads(base64.urlsafe_b64decode(raw.encode("utf-8")).decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception as e:
            self.log(f"解析播放元数据失败: {e}")
            return {}

    def _apply_player_meta(self, result, meta):
        if not meta:
            return result
        name = meta.get("name") or ""
        singer = meta.get("singer") or ""
        pic = meta.get("pic") or ""
        if name:
            result["title"] = name
            result["name"] = name
            result["vod_name"] = name
        if singer:
            result["artist"] = singer
            result["vod_actor"] = singer
        if pic:
            result["pic"] = pic
            result["cover"] = pic
            result["vod_pic"] = pic
        return result

    def _get_rank_songs(self, rank_id, page=1, pagesize=50):
        url = "http://mobilecdnbj.kugou.com/api/v3/rank/song"
        params = {
            "version": "9108", "ranktype": "0", "plat": "0",
            "pagesize": str(pagesize), "area_code": "1",
            "page": str(page), "rankid": str(rank_id),
            "volid": "35050", "with_res_tag": "0",
        }
        try:
            resp = self.session.get(url, params=params, timeout=(5, 15))
            resp.raise_for_status()
            data = resp.json()
            return {
                "songs": data.get("data", {}).get("info", []) or [],
                "total": data.get("data", {}).get("total", 0)
            }
        except Exception as e:
            self.log(f"获取榜单歌曲失败: {e}")
            return {"songs": [], "total": 0}
 
    def _search_songs(self, keyword, page=1, pagesize=20):
        url = "http://songsearch.kugou.com/song_search_v2"
        params = {
            "keyword": keyword, "page": page,
            "pagesize": pagesize, "platform": "WebFilter",
            "format": "json",
        }
        try:
            resp = self.session.get(url, params=params, timeout=(5, 15))
            resp.raise_for_status()
            return resp.json().get("data", {}).get("lists", []) or []
        except Exception as e:
            self.log(f"搜索失败: {e}")
            return []
 
    def _get_song_info(self, hash_val, album_id=""):
        url = "http://m.kugou.com/app/i/getSongInfo.php"
        params = {"hash": hash_val, "cmd": "playInfo"}
        if album_id:
            params["album_id"] = album_id
        try:
            resp = self.session.get(url, params=params, timeout=(5, 15))
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            self.log(f"获取歌曲信息失败: {e}")
            return None
 
    def _get_mv_urls(self, mv_hash):
        url = "https://m.kugou.com/app/i/mv.php"
        params = {"cmd": "100", "hash": mv_hash, "ismp3": "1", "ext": "mp4"}
        result = {}
        try:
            resp = self.session.get(url, params=params, timeout=(5, 15))
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != 1:
                return result
            mvdata = data.get("mvdata", {}) or {}
            for q in ["sq", "rq", "le"]:
                info = mvdata.get(q)
                if info:
                    downurl = info.get("downurl") or ""
                    if not downurl and info.get("backupdownurl"):
                        downurl = info["backupdownurl"][0]
                    if downurl:
                        result[q] = downurl
            return result
        except Exception as e:
            self.log(f"获取MV失败: {e}")
            return result
 
    def _get_lyric(self, hash_val):
        try:
            search_url = "http://lyrics.kugou.com/search"
            params = {"ver": 1, "man": "yes", "client": "pc", "hash": hash_val}
            resp = self.session.get(search_url, params=params, timeout=(5, 15))
            resp.raise_for_status()
            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return None
            c = candidates[0]
            download_url = "http://lyrics.kugou.com/download"
            params = {
                "ver": 1, "client": "pc",
                "id": c.get("id"),
                "accesskey": c.get("accesskey"),
                "fmt": "lrc", "charset": "utf8"
            }
            resp2 = self.session.get(download_url, params=params, timeout=(5, 15))
            resp2.raise_for_status()
            data2 = resp2.json()
            content = data2.get("content")
            if content:
                return base64.b64decode(content).decode("utf-8")
            return None
        except Exception as e:
            self.log(f"获取歌词失败: {e}")
            return None
 
                                

    def _first_value(self, *values):
        for value in values:
            if value:
                return value
        return ""

    def _get_quality_hashes(self, song, fallback_hash=""):
        extra = song.get("extra") or {}
        if not isinstance(extra, dict):
            extra = {}
        return {
            "无损音质": self._first_value(song.get("sqhash"), song.get("SQFileHash"), song.get("SuperFileHash"), extra.get("sqhash"), extra.get("SQFileHash")),
            "高清音质": self._first_value(song.get("320hash"), song.get("HQFileHash"), song.get("320FileHash"), extra.get("320hash"), extra.get("HQFileHash")),
            "标准音质": self._first_value(extra.get("128hash"), song.get("128hash"), song.get("hash"), song.get("FileHash"), song.get("Hash"), fallback_hash),
        }

    def _episode_title(self, idx, item):
        origin_idx = item.get("_origin_idx") or idx
        name = (item.get("name") or "未知歌曲").replace("$", " " ).replace("#", " " ).strip()
        singer = (item.get("singer") or "").replace("$", " " ).replace("#", " " ).strip()
        title = f"{int(origin_idx):02d}. {name}"
        if singer and singer != "未知歌手":
            title += f" - {singer}"
        return title
 
    def _extract_best_hash(self, song):
        # 优先免费常见档（128/标准），付费无损/高清放到后面，减少默认点播失败。
        order = [
            "hash", "FileHash", "Hash", "128hash",
            "320hash", "HQFileHash", "320FileHash",
            "sqhash", "SQFileHash", "SuperFileHash",
            "ResFileHash",
        ]
        for key in order:
            h = song.get(key)
            if h:
                return h
        extra = song.get("extra") or {}
        if isinstance(extra, dict):
            for key in ("128hash", "hash", "320hash", "sqhash"):
                h = extra.get(key)
                if h:
                    return h
        return None
 
    def _get_song_cover(self, song):
        cover = (
            song.get("album_sizable_cover")
            or song.get("album_img")
            or song.get("img")
            or song.get("cover")
            or song.get("AlbumImage")
            or song.get("albumImg")
            or song.get("Image")
            or ""
        )
        if cover and "{size}" in cover:
            cover = cover.replace("{size}", "400")
        return cover
 
    def _get_mv_hash(self, song):
                
        h = (
            song.get("MvHash")
            or song.get("mvhash")
            or song.get("MVHash")
            or ""
        )
        if h:
            return h
                          
        mvdata = song.get("mvdata")
        if mvdata and isinstance(mvdata, list) and len(mvdata) > 0:
            return mvdata[0].get("hash", "")
        return ""
 
    def _get_song_name(self, song):
        return song.get("songname") or song.get("SongName") or "未知歌曲"
 
    def _get_singer_name(self, song):
        authors = song.get("authors")
        if authors and isinstance(authors, list):
            names = "、".join(
                a.get("author_name", "") or a.get("name", "")
                for a in authors
                if a.get("author_name") or a.get("name")
            )
            if names:
                return names
        singers = song.get("Singers")
        if singers and isinstance(singers, list):
            names = "、".join(s.get("name", "") for s in singers if s.get("name"))
            if names:
                return names
        return (
            song.get("singerName")
            or song.get("SingerName")
            or song.get("singer_name")
            or song.get("author_name")
            or "未知歌手"
        )
 
    def _extract_singer_from_info(self, song_info):
        authors = song_info.get("authors")
        if authors and isinstance(authors, list):
            names = "、".join(
                a.get("author_name", "") or a.get("name", "")
                for a in authors
                if a.get("author_name") or a.get("name")
            )
            if names:
                return names
        return (
            song_info.get("singerName")
            or song_info.get("author_name")
            or song_info.get("SingerName")
            or song_info.get("artistName")
            or "未知歌手"
        )
 
    def _get_album_id(self, song):
        return str(
            song.get("album_id")
            or song.get("AlbumID")
            or song.get("albumid")
            or ""
        )
 
                                  
    def _create_ssa_subtitle(self, lrc_text):
        lines = []
        pattern = r'\[(\d{2}):(\d{2})\.(\d{2})\](.*)'
        for line in lrc_text.split('\n'):
            match = re.match(pattern, line)
            if match:
                minutes = int(match.group(1))
                seconds = int(match.group(2))
                hundredths = int(match.group(3))
                text = match.group(4).strip()
                total_seconds = minutes * 60 + seconds + hundredths / 100.0
                if text:
                    lines.append({'start': total_seconds, 'text': text})
        if not lines:
            return ""
        ssa_header = """[Script Info]
ScriptType: v4.00+
Collisions: Normal
PlayResX: 1280
PlayResY: 720
Timer: 100.0000
WrapStyle: 0
 
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: CENTER,Roboto,60,&H0000FF00,&H00808080,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,2,2,2,0,0,340,1
Style: TOP,Roboto,55,&H0000FFFF,&H00808080,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,1,1,2,0,0,200,1
Style: BOTTOM,Roboto,55,&H0000FFFF,&H00808080,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,1,1,2,0,0,500,1
 
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        def fmt(seconds):
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = int(seconds % 60)
            cs = int((seconds * 100) % 100)
            return f"{h}:{m:02d}:{s:02d}.{cs:02d}"
        events = []
        for i, current in enumerate(lines):
            end = lines[i+1]['start'] if i+1 < len(lines) else current['start'] + 5.0
            events.append(f"Dialogue: 1,{fmt(current['start'])},{fmt(end)},CENTER,,0,0,0,,{current['text']}")
            if i > 0:
                prev = lines[i-1]
                events.append(f"Dialogue: 2,{fmt(current['start'])},{fmt(end)},TOP,,0,0,0,,{prev['text']}")
            if i+1 < len(lines):
                next_line = lines[i+1]
                events.append(f"Dialogue: 3,{fmt(current['start'])},{fmt(end)},BOTTOM,,0,0,0,,{next_line['text']}")
        return ssa_header + "\n".join(events)
 
    def localProxy(self, params):
        return [404, "text/plain", b"not found"]
