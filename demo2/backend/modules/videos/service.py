import json
import os


def default_videos():
    return [
        {
            "id": "v1",
            "title": "【高清中文字幕版全网最快】大摩闭门会：Laura Wang：美联储展望，股票波动性即将到来，人民币汇率上修 260115（推荐程度：5星必看）",
            "cover": "https://picsum.photos/seed/bv17jkpb5ebv/640/360",
            "type": "embed",
            "embed_url": "https://player.bilibili.com/player.html?bvid=BV17JkPB5EBv&autoplay=0",
            "open_url": "https://www.bilibili.com/video/BV17JkPB5EBv/",
            "duration": "",
            "tag": "宏观",
        }
    ]


def load_videos(base_dir: str):
    fp = os.path.join(base_dir, "data", "videos.json")
    try:
        with open(fp, "r", encoding="utf-8") as f:
            arr = json.load(f)
        if isinstance(arr, list):
            return arr
    except Exception:
        pass
    return default_videos()

