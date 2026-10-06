# -*- coding: utf-8 -*-
# 西饭短剧 Spider - 全异步多线程并发版（首载7路100+，下滑并发3路预填充）
import requests
import re
import json
import traceback
import sys
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.append('../../')
try:
    from base.spider import Spider
except ImportError:
    # 定义一个基础接口类，用于本地测试
    class Spider:
        def init(self, extend=""):
            pass


class Spider(Spider):
    def __init__(self):
        super().__init__()
        self.siteUrl = "https://xifan-api-cn.youlishipin.com"
        self.cateManual = {
            "都市": "都市",
            "甜宠": "甜宠",
            "逆袭": "逆袭",
            "战神": "战神",
            "古装": "古装",
            "穿越": "穿越",
            "萌宝": "萌宝"
        }
        self.headers = {
            "User-Agent": "okhttp/3.12.11",
            "Connection": "keep-alive",
            "Accept-Encoding": "gzip, deflate"
        }
        self.session = requests.Session()
        
    def getName(self):
        return "西饭短剧"
    
    def init(self, extend=""):
        return self
    
    def fetch(self, url, headers=None, retry=2):
        """统一的网络请求接口（完全对齐河马，带重试机制）"""
        if headers is None:
            headers = self.headers
        
        for i in range(retry + 1):
            try:
                response = self.session.get(url, headers=headers, timeout=5, verify=False, allow_redirects=True)
                response.raise_for_status()
                return response
            except Exception as e:
                if i == retry:
                    print(f"请求异常: {url}, 错误: {str(e)}")
                    return None
                continue
    
    def isVideoFormat(self, url):
        video_formats = ['.mp4', '.mkv', '.avi', '.wmv', '.m3u8', '.flv', '.rmvb']
        return any(format in url.lower() for format in video_formats)
    
    def manualVideoCheck(self):
        return False
    
    def homeContent(self, filter):
        result = {}
        classes = [{'type_name': k, 'type_id': v} for k, v in self.cateManual.items()]
        result['class'] = classes
        result['filters'] = {}
        
        try:
            result['list'] = self.homeVideoContent()['list']
        except:
            result['list'] = []
        return result
    
    def homeVideoContent(self):
        # 默认推荐直接加载“都市”分类
        return self.categoryContent('都市', '1', False, {})
    
    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg) if pg else 1
        result = {'list': [], 'page': pg, 'pagecount': 1, 'limit': 15, 'total': 0}
        seen_ids = set()
        videos = []
        limit_size = 15  # 西饭单页固定大小

        try:
            # ----------------------------------------------------
            # 第一页加载：7路多线程并发，极速渲染首屏 105 个
            # 对应 offset: 0, 15, 30, 45, 60, 75, 90
            # ----------------------------------------------------
            if pg == 1:
                urls = []
                for i in range(7):
                    offset = i * limit_size
                    search_url = f"{self.siteUrl}/xifan/search/getSearchList?reqType=search&offset={offset}&keyword={quote(tid)}&quickEngineVersion=-1&scene="
                    urls.append(search_url)

                # 7路线程池并发
                temp_results = [None] * 7
                with ThreadPoolExecutor(max_workers=7) as executor:
                    future_to_index = {executor.submit(self.fetch, url): index for index, url in enumerate(urls)}
                    for future in as_completed(future_to_index):
                        idx = future_to_index[future]
                        try:
                            temp_results[idx] = future.result()
                        except:
                            pass

                # 顺序合并去重
                for res in temp_results:
                    if not res:
                        continue
                    try:
                        res_json = res.json()
                        elements = res_json.get('result', {}).get('elements', [])
                        for block in elements:
                            contents = block.get('contents', []) if 'contents' in block else [block]
                            for item in contents:
                                dj = item.get('duanjuVo') or {}
                                did = dj.get('duanjuId')
                                if not did or did in seen_ids:
                                    continue
                                seen_ids.add(did)
                                videos.append({
                                    "vod_id": f"西饭@{did}#{dj.get('source', 'xifan')}",
                                    "vod_name": dj.get('title', ''),
                                    "vod_pic": dj.get('coverImageUrl', ''),
                                    "vod_remarks": f"{dj.get('total', '')}集"
                                })
                    except:
                        pass

                # 动态页码判定，保证后续能下滑
                page_count = pg + 1 if len(videos) > 0 else pg

                result.update({
                    'list': videos,
                    'page': 1,
                    'pagecount': page_count,
                    'limit': 15,
                    'total': 9999 if len(videos) > 0 else len(videos)
                })

            # ----------------------------------------------------
            # 后续下滑：pg >= 2，瞬间并发 3 路加载 45 个视频预填满屏幕！
            # pg = 2 -> 对应 offset: 105, 120, 135
            # pg = 3 -> 对应 offset: 150, 165, 180
            # ----------------------------------------------------
            else:
                base_offset = 105 + (pg - 2) * 45
                urls = []
                for i in range(3):  # 并发 3 个页面，极大减轻等待感
                    offset = base_offset + (i * limit_size)
                    search_url = f"{self.siteUrl}/xifan/search/getSearchList?reqType=search&offset={offset}&keyword={quote(tid)}&quickEngineVersion=-1&scene="
                    urls.append(search_url)

                # 3路线程池并发预加载
                temp_results = [None] * 3
                with ThreadPoolExecutor(max_workers=3) as executor:
                    future_to_index = {executor.submit(self.fetch, url): index for index, url in enumerate(urls)}
                    for future in as_completed(future_to_index):
                        idx = future_to_index[future]
                        try:
                            temp_results[idx] = future.result()
                        except:
                            pass

                # 合并新加载的内容
                for res in temp_results:
                    if not res:
                        continue
                    try:
                        res_json = res.json()
                        elements = res_json.get('result', {}).get('elements', [])
                        for block in elements:
                            contents = block.get('contents', []) if 'contents' in block else [block]
                            for item in contents:
                                dj = item.get('duanjuVo') or {}
                                did = dj.get('duanjuId')
                                if not did:
                                    continue
                                videos.append({
                                    "vod_id": f"西饭@{did}#{dj.get('source', 'xifan')}",
                                    "vod_name": dj.get('title', ''),
                                    "vod_pic": dj.get('coverImageUrl', ''),
                                    "vod_remarks": f"{dj.get('total', '')}集"
                                })
                    except:
                        pass

                # 动态下滑判定
                page_count = pg + 1 if len(videos) > 0 else pg

                result.update({
                    'list': videos,
                    'page': pg,
                    'pagecount': page_count,
                    'limit': 15,
                    'total': 9999 if len(videos) > 0 else (base_offset + len(videos))
                })

        except Exception as e:
            print(f"分类内容获取出错: {e}")
            
        return result
    
    def searchContent(self, key, quick, pg=1):
        return self.searchContentPage(key, quick, pg)
    
    def searchContentPage(self, key, quick, pg=1):
        pg = int(pg) if pg else 1
        result = {'list': [], 'page': pg, 'pagecount': 1, 'limit': 20, 'total': 0}
        if not key:
            return result

        offset = (pg - 1) * 20
        search_url = f"{self.siteUrl}/xifan/search/getSearchList?reqType=search&offset={offset}&keyword={quote(key)}&quickEngineVersion=-1&scene="
        
        response = self.fetch(search_url)
        if not response:
            return result
            
        try:
            res_json = response.json()
            elements = res_json.get('result', {}).get('elements', [])
            videos = []
            seen = set()
            
            for block in elements:
                contents = [block] if block.get('duanjuVo') else block.get('contents', [])
                for item in contents:
                    dj = item.get('duanjuVo') or {}
                    did = dj.get('duanjuId')
                    if not did or did in seen:
                        continue
                    seen.add(did)
                    videos.append({
                        "vod_id": f"西饭@{did}#{dj.get('source', 'xifan')}",
                        "vod_name": dj.get('title', ''),
                        "vod_pic": dj.get('coverImageUrl', ''),
                        "vod_remarks": f"西饭短剧｜{dj.get('total', '')}集"
                    })
            
            page_count = pg + 1 if len(videos) > 0 else pg
            result.update({
                'list': videos,
                'pagecount': page_count,
                'limit': 20,
                'total': 9999 if len(videos) > 0 else len(videos)
            })
            
        except Exception as e:
            print(f"搜索内容出错: {e}")
            
        return result

    def detailContent(self, ids):
        result = {'list': []}
        if not ids:
            return result
            
        vod_id = ids[0]
        parts = vod_id.split('@', 1)
        if len(parts) < 2:
            return result
        
        did_part = parts[1]
        try:
            duanju_id, source = did_part.split('#', 1)
        except ValueError:
            duanju_id, source = did_part, 'xifan'
            
        detail_url = f"{self.siteUrl}/xifan/drama/getDuanjuInfo?duanjuId={duanju_id}&source={source}"
        response = self.fetch(detail_url)
        if not response:
            return result
            
        try:
            res_json = response.json()
            if res_json and res_json.get('result'):
                d = res_json['result']
                episode_list = d.get('episodeList', [])
                
                # 拼接播放集数格式
                episodes = [f"第{e['index']}集${e['playUrl']}" for e in episode_list]
                play_url = '#'.join(episodes)
                
                status = '已完结' if d.get('updateStatus') == 'over' else f"更新{d.get('total', '')}集"
                
                vod = {
                    "vod_id": vod_id,
                    "vod_name": d.get('title', '未知'),
                    "vod_pic": d.get('coverImageUrl', ''),
                    "type_name": "短剧",
                    "vod_year": "",
                    "vod_area": "中国",
                    "vod_remarks": f"{d.get('total', '')}集 {status}",
                    "vod_actor": "",
                    "vod_director": "",
                    "vod_content": d.get('intro', d.get('title', '')),
                    "vod_play_from": "西饭剧场",
                    "vod_play_url": play_url
                }
                result['list'] = [vod]
                
        except Exception as e:
            print(f"详情页解析出错: {e}")
            traceback.print_exc()
            
        return result

    def playerContent(self, flag, id, vipFlags):
        result = {
            "parse": 0,
            "url": id,
            "header": json.dumps(self.headers)
        }
        
        if 'http' in id:
            try:
                # 重定向解析最终播放源
                res = self.session.get(id, headers=self.headers, timeout=3, verify=False, allow_redirects=True)
                if res.url:
                    result["url"] = res.url
            except:
                pass
                
        return result

    def localProxy(self, param):
        return [200, "video/MP2T", {}, param]

    def destroy(self):
        pass