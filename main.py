"""Twitchのコメントを監視してXに投稿するメインモジュール。"""

# 標準ライブラリの読み込みに関するコメント
import asyncio
import json
import logging
import math
import os
import re
import ssl
import tempfile
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Deque, Dict, List, Optional, Set, Tuple

# 外部ライブラリの読み込みに関するコメント
from dotenv import load_dotenv
import httpx
import tweepy

# Xの最大文字数を定数として定義するコメント
MAX_TWEET_LENGTH = 280

# 投稿に付与するハッシュタグを定義するコメント
POST_HASHTAG = "#ヒカキン"

# Xの返信設定で許可する値を定義するコメント
X_REPLY_SETTINGS = {"everyone", "mentionedUsers", "following"}

# Twitch IRCの既定サーバー設定に関するコメント
DEFAULT_TWITCH_SERVER = "irc.chat.twitch.tv"
DEFAULT_TWITCH_PORT_TLS = 6697

# Twitch IRCの固定接続設定に関するコメント
TWITCH_SERVER = DEFAULT_TWITCH_SERVER
TWITCH_USE_TLS = True
TWITCH_PORT = DEFAULT_TWITCH_PORT_TLS
TWITCH_RECONNECT_DELAY_SECONDS = 5.0

# Twitchのトークン更新エンドポイントに関するコメント
TWITCH_TOKEN_ENDPOINT = "https://id.twitch.tv/oauth2/token"

# Twitchのユーザー情報取得エンドポイントに関するコメント
TWITCH_USERS_ENDPOINT = "https://api.twitch.tv/helix/users"

# Twitchの配信情報取得エンドポイントに関するコメント
TWITCH_STREAMS_ENDPOINT = "https://api.twitch.tv/helix/streams"

# YouTubeの検索エンドポイントに関するコメント
YOUTUBE_SEARCH_ENDPOINT = "https://www.googleapis.com/youtube/v3/search"

# YouTubeの配信詳細取得エンドポイントに関するコメント
YOUTUBE_VIDEOS_ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"

# YouTube配信予定のキャッシュファイル名を定義するコメント
YOUTUBE_UPCOMING_CACHE_FILENAME = "youtube_upcoming_cache.json"

# 配信履歴のキャッシュファイル名を定義するコメント
STREAM_HISTORY_CACHE_FILENAME = "twitch_stream_history.json"

# 月次配信統計のキャッシュファイル名を定義するコメント
MONTHLY_STATS_CACHE_FILENAME = "monthly_stats_cache.json"

# 日本語フォントのファイル名を定義するコメント
JAPANESE_FONT_FILE = "NotoSansCJKjp-Regular.otf"

# 日本語フォントの相対パスを定義するコメント
JAPANESE_FONT_RELATIVE_PATH = Path("assets") / "fonts" / JAPANESE_FONT_FILE

# 投稿対象にするTwitchユーザー名を固定するコメント
TARGET_TWITCH_USER = "hikakin"

# 大文字小文字の差を吸収するために小文字化するコメント
TARGET_TWITCH_USER_LOWER = TARGET_TWITCH_USER.lower()

# 投稿時の見出しを固定するコメント
POST_HEADER = "【新着コメント😎】"


# トークン更新時の安全マージンに関するコメント
TOKEN_REFRESH_MARGIN_SECONDS = 60.0

# ロガーの設定に関するコメント
LOGGER = logging.getLogger("twitch_to_x")

# TwitchのPRIVMSGを解析する正規表現に関するコメント
PRIVMSG_PATTERN = re.compile(
    r"^:(?P<user>[^!]+)![^ ]+ PRIVMSG #(?P<channel>[^ ]+) :(?P<message>.*)$"
)


# 設定値をまとめるデータクラスに関するコメント
@dataclass(frozen=True)
class Settings:
    """環境変数から読み込んだ設定値を保持するクラス。"""

    # Twitch関連の設定値に関するコメント
    twitch_channel: str
    twitch_nick: Optional[str]
    twitch_client_id: str
    twitch_client_secret: str
    twitch_refresh_token: str

    # X関連の設定値に関するコメント
    x_api_key: str
    x_api_secret: str
    x_access_token: str
    x_access_secret: str
    x_bearer_token: Optional[str]
    x_reply_setting: str
    x_reply_mention_users: Tuple[str, ...]

    # 投稿制御に関する設定値のコメント
    x_post_interval_seconds: float
    x_queue_size: int

    # Twitch配信監視に関する設定値のコメント
    twitch_stream_poll_interval_seconds: float
    twitch_stream_sample_max_points: int

    # YouTube配信監視に関する設定値のコメント
    youtube_api_key: Optional[str]
    youtube_channel_ids: Tuple[str, ...]
    youtube_poll_interval_seconds: float
    youtube_sample_max_points: int
    youtube_upcoming_poll_interval_seconds: float


# X投稿ジョブを表すデータクラスに関するコメント
@dataclass(frozen=True)
class XPostJob:
    """Xへの投稿内容とメディア情報をまとめる。"""

    # 投稿本文を保持するコメント
    text: str
    # 添付画像パスを保持するコメント
    media_path: Optional[str] = None
    # 投稿後に削除するファイルパスを保持するコメント
    cleanup_path: Optional[str] = None


# 同接サンプルを保持するデータクラスに関するコメント
@dataclass(frozen=True)
class ViewerSample:
    """同接の記録用サンプルを保持する。"""

    # 記録時刻のUNIX秒を保持するコメント
    timestamp: float
    # 同接数を保持するコメント
    viewer_count: int


# 配信セッション情報を保持するデータクラスに関するコメント
@dataclass
class StreamSession:
    """配信開始から終了までの記録を保持する。"""

    # Twitchの配信IDを保持するコメント
    stream_id: str
    # 配信開始時刻のUNIX秒を保持するコメント
    started_at: float
    # 配信タイトルを保持するコメント
    title: str
    # 同接サンプルの一覧を保持するコメント
    samples: Deque[ViewerSample]
    # YouTubeチャンネルの順序を保持するコメント
    youtube_channel_ids: Tuple[str, ...]
    # YouTubeチャンネルごとの状態を保持するコメント
    youtube_channels: Dict[str, "YouTubeChannelSession"]


# Twitch配信情報を保持するデータクラスに関するコメント
@dataclass(frozen=True)
class TwitchStreamInfo:
    """Twitch APIの配信情報を整形して保持する。"""

    # Twitchの配信IDを保持するコメント
    stream_id: str
    # 配信開始時刻のUNIX秒を保持するコメント
    started_at: float
    # 同接数を保持するコメント
    viewer_count: int
    # 配信タイトルを保持するコメント
    title: str


# YouTube配信情報を保持するデータクラスに関するコメント
@dataclass(frozen=True)
class YouTubeStreamInfo:
    """YouTube APIの配信情報を整形して保持する。"""

    # YouTubeの動画IDを保持するコメント
    video_id: str
    # 配信開始時刻のUNIX秒を保持するコメント
    started_at: float
    # 同接数を保持するコメント
    viewer_count: int
    # 配信タイトルを保持するコメント
    title: str
    # チャンネル名を保持するコメント
    channel_title: str


# YouTube配信予定情報を保持するデータクラスに関するコメント
@dataclass(frozen=True)
class YouTubeUpcomingInfo:
    """YouTubeの配信予定情報を整形して保持する。"""

    # YouTubeの動画IDを保持するコメント
    video_id: str
    # 配信予定開始時刻のUNIX秒を保持するコメント
    scheduled_start: float
    # 配信タイトルを保持するコメント
    title: str
    # チャンネル名を保持するコメント
    channel_title: str
    # 配信URLを保持するコメント
    url: str


# YouTubeチャンネルごとの配信状態を保持するデータクラスに関するコメント
@dataclass
class YouTubeChannelSession:
    """YouTubeチャンネルの同接推移を保持する。"""

    # チャンネルIDを保持するコメント
    channel_id: str
    # 配信動画IDを保持するコメント
    video_id: str
    # 配信タイトルを保持するコメント
    title: str
    # チャンネル名を保持するコメント
    channel_title: str
    # 配信開始時刻のUNIX秒を保持するコメント
    started_at: float
    # 同接サンプルの一覧を保持するコメント
    samples: Deque[ViewerSample]


# 必須の環境変数を取得する関数に関するコメント
def require_env(name: str) -> str:
    """必須環境変数を取得し、未設定なら例外を投げる。"""

    # 取得した値を検証するためのコメント
    value = os.getenv(name)
    if value is None or not value.strip():
        raise ValueError(f"{name} が未設定です。")
    return value.strip()


# 任意の環境変数を取得する関数に関するコメント
def optional_env(name: str) -> Optional[str]:
    """任意環境変数を取得し、空ならNoneを返す。"""

    # 値を取得するためのコメント
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value if value else None


# 整数の環境変数を安全に読む関数に関するコメント
def parse_int_env(name: str, default: int) -> int:
    """整数の環境変数を読み込み、未設定ならデフォルトを返す。"""

    # 値の取得と変換に関するコメント
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        parsed_value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} は整数で設定してください。") from exc
    if parsed_value <= 0:
        raise ValueError(f"{name} は正の整数で設定してください。")
    return parsed_value


# 浮動小数点の環境変数を安全に読む関数に関するコメント
def parse_float_env(name: str, default: float) -> float:
    """浮動小数点の環境変数を読み込み、未設定ならデフォルトを返す。"""

    # 値の取得と変換に関するコメント
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        parsed_value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} は数値で設定してください。") from exc
    if parsed_value <= 0:
        raise ValueError(f"{name} は正の数値で設定してください。")
    return parsed_value


# Xの返信設定を読み込む関数に関するコメント
def parse_x_reply_setting_env(name: str, default: str) -> str:
    """Xの返信設定を読み込み、未設定ならデフォルトを返す。"""

    # デフォルト値の検証を行うコメント
    if default not in X_REPLY_SETTINGS:
        raise ValueError(f"{name} の既定値が不正です。")

    # 任意の環境変数を取得するコメント
    raw_value = optional_env(name)
    if not raw_value:
        return default

    # 設定値の正当性を確認するコメント
    if raw_value not in X_REPLY_SETTINGS:
        raise ValueError(f"{name} は {', '.join(sorted(X_REPLY_SETTINGS))} のいずれかで設定してください。")

    return raw_value


# Xの返信対象メンションを読み込む関数に関するコメント
def parse_x_reply_mentions_env(name: str) -> Tuple[str, ...]:
    """Xの返信対象メンションをカンマ区切りで読み込む。"""

    # 値を取得して未設定なら空のタプルを返すコメント
    raw_value = optional_env(name)
    if not raw_value:
        return tuple()

    # @を除去して重複を避けるコメント
    mentions = []
    for item in raw_value.split(","):
        cleaned = item.strip().lstrip("@")
        if not cleaned:
            continue
        if cleaned in mentions:
            continue
        mentions.append(cleaned)

    return tuple(mentions)


# カンマ区切りの環境変数を読み込む関数に関するコメント
def parse_csv_env(name: str) -> Tuple[str, ...]:
    """カンマ区切りの環境変数を読み込みタプルで返す。"""

    # 値を取得して未設定なら空のタプルを返すコメント
    raw_value = optional_env(name)
    if not raw_value:
        return tuple()

    # カンマ区切りで分割して空要素を除去するコメント
    items = [item.strip() for item in raw_value.split(",") if item.strip()]
    return tuple(items)


# Twitchチャンネル名を正規化する関数に関するコメント
def normalize_channel_name(channel: str) -> str:
    """Twitchのチャンネル名を正規化する。"""

    # 先頭の#を除去し小文字化するコメント
    normalized = channel.strip()
    if normalized.startswith("#"):
        normalized = normalized[1:]
    return normalized.lower()


# Twitchトークンを正規化する関数に関するコメント
def normalize_twitch_token(token: str) -> str:
    """Twitchトークンのoauth接頭辞を整える。"""

    # oauth: が付いていない場合に補うコメント
    if token.startswith("oauth:"):
        return token
    return f"oauth:{token}"


# 設定値の読み込み関数に関するコメント
def load_settings() -> Settings:
    """環境変数から設定値を読み込みSettingsを返す。"""

    # .envファイルを読み込むコメント
    load_dotenv()

    # Twitchの必須項目の読み込みに関するコメント
    twitch_channel = normalize_channel_name(require_env("TWITCH_CHANNEL"))
    twitch_client_id = require_env("TWITCH_CLIENT_ID")
    twitch_client_secret = require_env("TWITCH_CLIENT_SECRET")
    twitch_refresh_token = require_env("TWITCH_REFRESH_TOKEN")

    # Twitchの任意項目の読み込みに関するコメント
    twitch_nick = optional_env("TWITCH_NICK")

    # Xの必須項目の読み込みに関するコメント
    x_api_key = require_env("X_API_KEY")
    x_api_secret = require_env("X_API_SECRET")
    x_access_token = require_env("X_ACCESS_TOKEN")
    x_access_secret = require_env("X_ACCESS_SECRET")
    x_bearer_token = optional_env("X_BEARER_TOKEN")
    x_reply_setting = parse_x_reply_setting_env("X_REPLY_SETTING", "everyone")
    x_reply_mention_users = parse_x_reply_mentions_env("X_REPLY_MENTION_USERS")

    # オプション設定の読み込みに関するコメント
    x_post_interval_seconds = parse_float_env("X_POST_INTERVAL_SECONDS", 5.0)
    x_queue_size = parse_int_env("X_QUEUE_SIZE", 200)

    # Twitch配信監視の設定を読み込むコメント
    twitch_stream_poll_interval_seconds = parse_float_env(
        "TWITCH_STREAM_POLL_INTERVAL_SECONDS",
        60.0,
    )
    twitch_stream_sample_max_points = parse_int_env(
        "TWITCH_STREAM_SAMPLE_MAX_POINTS",
        5000,
    )

    # YouTube配信監視の設定を読み込むコメント
    youtube_api_key = optional_env("YOUTUBE_API_KEY")
    youtube_channel_ids = parse_csv_env("YOUTUBE_CHANNEL_IDS")
    youtube_poll_interval_seconds = parse_float_env(
        "YOUTUBE_POLL_INTERVAL_SECONDS",
        60.0,
    )
    youtube_sample_max_points = parse_int_env(
        "YOUTUBE_SAMPLE_MAX_POINTS",
        5000,
    )
    youtube_upcoming_poll_interval_seconds = parse_float_env(
        "YOUTUBE_UPCOMING_POLL_INTERVAL_SECONDS",
        300.0,
    )

    # 設定値をまとめるコメント
    return Settings(
        twitch_channel=twitch_channel,
        twitch_nick=twitch_nick,
        twitch_client_id=twitch_client_id,
        twitch_client_secret=twitch_client_secret,
        twitch_refresh_token=twitch_refresh_token,
        x_api_key=x_api_key,
        x_api_secret=x_api_secret,
        x_access_token=x_access_token,
        x_access_secret=x_access_secret,
        x_bearer_token=x_bearer_token,
        x_reply_setting=x_reply_setting,
        x_reply_mention_users=x_reply_mention_users,
        x_post_interval_seconds=x_post_interval_seconds,
        x_queue_size=x_queue_size,
        twitch_stream_poll_interval_seconds=twitch_stream_poll_interval_seconds,
        twitch_stream_sample_max_points=twitch_stream_sample_max_points,
        youtube_api_key=youtube_api_key,
        youtube_channel_ids=youtube_channel_ids,
        youtube_poll_interval_seconds=youtube_poll_interval_seconds,
        youtube_sample_max_points=youtube_sample_max_points,
        youtube_upcoming_poll_interval_seconds=youtube_upcoming_poll_interval_seconds,
    )


# 文字列を指定長で切り詰める関数に関するコメント
def clip_text(text: str, limit: int) -> str:
    """表示用の文字列を指定長で切り詰める。"""

    # 文字数の上限を超えた場合に省略記号を付けるコメント
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return f"{text[: limit - 3]}..."




# ISO時刻をUNIX秒に変換する関数に関するコメント
def parse_iso_datetime(value: Optional[str]) -> Optional[float]:
    """ISO 8601形式の時刻文字列をUNIX秒に変換する。"""

    # 値がない場合はNoneを返すコメント
    if not value:
        return None

    # ISO文字列をUTCとして解釈するコメント
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed.timestamp()


# ローカル時刻の表示用文字列を作る関数に関するコメント
def format_local_time(timestamp: float) -> str:
    """ローカルタイムゾーンの日時文字列を返す。"""

    # ローカル時刻で整形するコメント
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


# 月日だけの表示文字列を作る関数に関するコメント
def format_month_day(timestamp: float) -> str:
    """月日だけの表示文字列を返す。"""

    # 月日を取り出して整形するコメント
    date_value = datetime.fromtimestamp(timestamp)
    return f"{date_value.month}月{date_value.day}日"


# 符号付き整数を整形する関数に関するコメント
def format_signed_int(value: int) -> str:
    """符号付きの整数を +N / -N 形式で返す。"""

    # 符号を判定するコメント
    sign = "+" if value >= 0 else "-"
    return f"{sign}{abs(value)}"


# 符号付きの時間差を整形する関数に関するコメント
def format_signed_duration(seconds: float) -> str:
    """符号付きの時間差をX時間Y分で返す。"""

    # 絶対値の分数を求めるコメント
    total_minutes = int(round(abs(seconds) / 60))
    hours, minutes = divmod(total_minutes, 60)

    # 符号を判定するコメント
    sign = "+" if seconds >= 0 else "-"
    return f"{sign}{hours}時間{minutes}分"


# 月次配信統計の投稿文を構築する関数に関するコメント
def build_monthly_stats_tweet(
    start_timestamp: float,
    end_timestamp: float,
    total_days: int,
    total_seconds: float,
    diff_days: int,
    diff_seconds: float,
) -> str:
    """月次配信統計の投稿文を作る。"""

    # 期間の表示を作るコメント
    start_label = format_month_day(start_timestamp)
    end_label = format_month_day(max(0.0, end_timestamp - 1))

    # 総配信時間を時間と分に変換するコメント
    total_minutes = int(round(total_seconds / 60))
    hours, minutes = divmod(total_minutes, 60)

    # 投稿文を組み立てるコメント
    message = (
        "【配信統計📊】\n\n"
        f"{start_label}〜{end_label}\n\n"
        f"配信日数：{total_days}日（先月比 {format_signed_int(diff_days)}）\n"
        f"総配信時間：{hours}時間{minutes}分（先月比 {format_signed_duration(diff_seconds)}）"
    )
    return truncate_for_x(message, MAX_TWEET_LENGTH)


# 同接の最大と平均を計算する関数に関するコメント
def compute_viewer_stats(samples: Deque[ViewerSample]) -> Tuple[int, int]:
    """同接サンプルから最大と平均を返す。"""

    # サンプルがない場合は0で返すコメント
    if not samples:
        return 0, 0

    # 同接の統計を計算するコメント
    counts = [sample.viewer_count for sample in samples]
    max_count = max(counts)
    avg_count = int(sum(counts) / max(1, len(counts)))
    return max_count, avg_count


# YouTubeの複数チャンネル同接を合算する関数に関するコメント
def aggregate_youtube_counts(channels: Dict[str, "YouTubeChannelSession"]) -> List[int]:
    """YouTubeチャンネルの同接を時刻ごとに合算して返す。"""

    # 時刻ごとの合算値を保持するコメント
    buckets: Dict[int, int] = {}

    # 各チャンネルのサンプルを合算するコメント
    for channel in channels.values():
        for sample in channel.samples:
            bucket_key = int(sample.timestamp // 60 * 60)
            buckets[bucket_key] = buckets.get(bucket_key, 0) + sample.viewer_count

    # 合算結果がなければ空で返すコメント
    if not buckets:
        return []

    # 時刻順に並べた合算値を返すコメント
    return [buckets[key] for key in sorted(buckets)]


# 残り時間を日本語で整形する関数に関するコメント
def format_time_until(target_timestamp: float, base_timestamp: float) -> str:
    """指定時刻までの残り時間を日本語で返す。"""

    # 残り秒数を計算するコメント
    remaining_seconds = max(0.0, target_timestamp - base_timestamp)
    remaining_minutes = max(1, math.ceil(remaining_seconds / 60))

    # 時間単位で分岐するコメント
    if remaining_minutes < 60:
        return f"{remaining_minutes}分後"

    remaining_hours = math.ceil(remaining_minutes / 60)
    if remaining_hours < 24:
        return f"{remaining_hours}時間後"

    remaining_days = math.ceil(remaining_hours / 24)
    return f"{remaining_days}日後"


# Matplotlibで日本語フォントを設定する関数に関するコメント
def setup_matplotlib_japanese_font() -> object:
    """日本語フォントを登録してFontPropertiesを返す。"""

    # フォントの絶対パスを組み立てるコメント
    font_path = Path(__file__).resolve().parent / JAPANESE_FONT_RELATIVE_PATH
    if not font_path.is_file():
        raise FileNotFoundError(f"日本語フォントが見つかりません: {font_path}")

    # フォント管理モジュールを読み込むコメント
    import matplotlib
    from matplotlib import font_manager

    # フォントを登録してプロパティを取得するコメント
    font_manager.fontManager.addfont(str(font_path))
    font_prop = font_manager.FontProperties(fname=str(font_path))

    # 日本語フォントを既定に設定するコメント
    matplotlib.rcParams["font.family"] = font_prop.get_name()
    matplotlib.rcParams["axes.unicode_minus"] = False

    return font_prop


# Twitchトークンを管理するクラスに関するコメント
class TwitchTokenManager:
    """リフレッシュトークンからアクセストークンを取得する。"""

    # 初期化処理に関するコメント
    def __init__(self, client_id: str, client_secret: str, refresh_token: str) -> None:
        # 認証情報と状態を保持するコメント
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._access_token: Optional[str] = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    # アクセストークンを取得する処理に関するコメント
    async def get_access_token(self) -> str:
        """必要に応じてアクセストークンを更新して返す。"""

        # 同時更新を避けるためにロックするコメント
        async with self._lock:
            if self._access_token and self._is_token_valid():
                return self._access_token
            await self._refresh_token_locked()
            if not self._access_token:
                raise RuntimeError("Twitchアクセストークンの取得に失敗しました。")
            return self._access_token

    # トークンの有効性を確認する処理に関するコメント
    def _is_token_valid(self) -> bool:
        """期限に余裕がある場合のみ有効とみなす。"""

        # 有効期限の判定を行うコメント
        return time.monotonic() < (self._expires_at - TOKEN_REFRESH_MARGIN_SECONDS)

    # トークンを更新する処理に関するコメント
    async def _refresh_token_locked(self) -> None:
        """リフレッシュトークンでアクセストークンを取得する。"""

        # リクエストのペイロードを組み立てるコメント
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }

        # HTTPリクエストを送るコメント
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(TWITCH_TOKEN_ENDPOINT, data=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            LOGGER.exception("Twitchトークンの更新に失敗しました: %s", exc)
            raise

        # レスポンスからトークン情報を取り出すコメント
        access_token = data.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise ValueError("Twitchトークン応答にaccess_tokenがありません。")

        refresh_token = data.get("refresh_token")
        if isinstance(refresh_token, str) and refresh_token:
            if refresh_token != self._refresh_token:
                self._refresh_token = refresh_token
                LOGGER.info("Twitchのrefresh tokenが更新されました。環境変数も更新してください。")

        expires_in = data.get("expires_in")
        try:
            expires_in_seconds = int(expires_in)
        except (TypeError, ValueError):
            expires_in_seconds = 3600

        if expires_in_seconds <= 0:
            expires_in_seconds = 3600

        # 状態を更新するコメント
        self._access_token = access_token
        self._expires_at = time.monotonic() + expires_in_seconds


# Twitchのユーザー名を取得する関数に関するコメント
async def fetch_twitch_user_login(access_token: str, client_id: str) -> str:
    """Twitchのアクセストークンからユーザー名を取得する。"""

    # リクエストヘッダーを組み立てるコメント
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Client-Id": client_id,
    }

    # ユーザー情報を取得するコメント
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(TWITCH_USERS_ENDPOINT, headers=headers)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        LOGGER.exception("Twitchユーザー情報の取得に失敗しました: %s", exc)
        raise

    # レスポンスからユーザー名を取り出すコメント
    users = data.get("data")
    if not isinstance(users, list) or not users:
        raise ValueError("Twitchユーザー情報が取得できませんでした。")

    login = users[0].get("login") if isinstance(users[0], dict) else None
    if not isinstance(login, str) or not login.strip():
        raise ValueError("Twitchユーザー名の取得に失敗しました。")

    return login.strip()


# YouTube配信の動画IDを取得する関数に関するコメント
async def fetch_youtube_live_video_id(api_key: str, channel_id: str) -> Optional[str]:
    """YouTubeの配信中動画IDを取得する。"""

    # クエリパラメータを組み立てるコメント
    params = {
        "part": "snippet",
        "channelId": channel_id,
        "eventType": "live",
        "type": "video",
        "order": "date",
        "maxResults": 1,
        "key": api_key,
    }

    # 配信中の動画を検索するコメント
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(YOUTUBE_SEARCH_ENDPOINT, params=params)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        LOGGER.exception("YouTube配信検索に失敗しました: %s", exc)
        raise

    # 結果がない場合はNoneを返すコメント
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return None

    # 動画IDを取り出すコメント
    item = items[0] if isinstance(items[0], dict) else {}
    item_id = item.get("id") if isinstance(item.get("id"), dict) else {}
    video_id = item_id.get("videoId")
    if not isinstance(video_id, str) or not video_id.strip():
        return None

    return video_id.strip()


# YouTube配信情報を取得する関数に関するコメント
async def fetch_youtube_stream_info(
    api_key: str,
    channel_id: str,
) -> Optional[YouTubeStreamInfo]:
    """YouTubeの配信情報を取得して整形する。"""

    # 配信中の動画IDを取得するコメント
    video_id = await fetch_youtube_live_video_id(api_key, channel_id)
    if not video_id:
        return None

    # クエリパラメータを組み立てるコメント
    params = {
        "part": "liveStreamingDetails,snippet",
        "id": video_id,
        "key": api_key,
    }

    # 配信詳細を取得するコメント
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(YOUTUBE_VIDEOS_ENDPOINT, params=params)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        LOGGER.exception("YouTube配信詳細の取得に失敗しました: %s", exc)
        raise

    # 配信情報が取得できない場合はNoneを返すコメント
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return None

    # 先頭の配信情報を解析するコメント
    item = items[0] if isinstance(items[0], dict) else {}
    snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
    details = (
        item.get("liveStreamingDetails")
        if isinstance(item.get("liveStreamingDetails"), dict)
        else {}
    )

    # 同接数を整数化するコメント
    viewer_count = details.get("concurrentViewers")
    try:
        viewer_count_int = int(viewer_count)
    except (TypeError, ValueError):
        viewer_count_int = 0
    if viewer_count_int < 0:
        viewer_count_int = 0

    # 開始時刻を取得するコメント
    started_at_raw = details.get("actualStartTime")
    if not isinstance(started_at_raw, str) or not started_at_raw:
        started_at_raw = details.get("scheduledStartTime")
    started_at = parse_iso_datetime(started_at_raw if isinstance(started_at_raw, str) else None)
    if started_at is None:
        started_at = time.time()

    # 配信タイトルとチャンネル名を取り出すコメント
    title_value = snippet.get("title")
    channel_title_value = snippet.get("channelTitle")
    title_text = title_value.strip() if isinstance(title_value, str) else ""
    channel_title = channel_title_value.strip() if isinstance(channel_title_value, str) else ""

    return YouTubeStreamInfo(
        video_id=video_id,
        started_at=started_at,
        viewer_count=viewer_count_int,
        title=title_text,
        channel_title=channel_title,
    )


# YouTube配信予定の動画IDを取得する関数に関するコメント
async def fetch_youtube_upcoming_video_meta(
    api_key: str,
    channel_id: str,
) -> Optional[Tuple[str, str, str]]:
    """YouTube配信予定の動画IDとタイトルを取得する。"""

    # クエリパラメータを組み立てるコメント
    params = {
        "part": "snippet",
        "channelId": channel_id,
        "eventType": "upcoming",
        "type": "video",
        "order": "date",
        "maxResults": 1,
        "key": api_key,
    }

    # 配信予定の動画を検索するコメント
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(YOUTUBE_SEARCH_ENDPOINT, params=params)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        LOGGER.exception("YouTube配信予定検索に失敗しました: %s", exc)
        raise

    # 結果がない場合はNoneを返すコメント
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return None

    # 動画IDとタイトルを取り出すコメント
    item = items[0] if isinstance(items[0], dict) else {}
    item_id = item.get("id") if isinstance(item.get("id"), dict) else {}
    snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
    video_id = item_id.get("videoId")
    if not isinstance(video_id, str) or not video_id.strip():
        return None

    title_value = snippet.get("title")
    channel_title_value = snippet.get("channelTitle")
    title_text = title_value.strip() if isinstance(title_value, str) else ""
    channel_title = channel_title_value.strip() if isinstance(channel_title_value, str) else ""
    return video_id.strip(), title_text, channel_title


# YouTube配信予定情報を取得する関数に関するコメント
async def fetch_youtube_upcoming_info(
    api_key: str,
    channel_id: str,
) -> Optional[YouTubeUpcomingInfo]:
    """YouTubeの配信予定情報を取得して整形する。"""

    # 配信予定の動画メタ情報を取得するコメント
    meta = await fetch_youtube_upcoming_video_meta(api_key, channel_id)
    if not meta:
        return None
    video_id, title_text, channel_title = meta

    # クエリパラメータを組み立てるコメント
    params = {
        "part": "liveStreamingDetails",
        "id": video_id,
        "key": api_key,
    }

    # 配信予定詳細を取得するコメント
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(YOUTUBE_VIDEOS_ENDPOINT, params=params)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        LOGGER.exception("YouTube配信予定詳細の取得に失敗しました: %s", exc)
        raise

    # 配信情報が取得できない場合はNoneを返すコメント
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return None

    # 配信予定時刻を取得するコメント
    item = items[0] if isinstance(items[0], dict) else {}
    details = (
        item.get("liveStreamingDetails")
        if isinstance(item.get("liveStreamingDetails"), dict)
        else {}
    )
    scheduled_raw = details.get("scheduledStartTime")
    scheduled_start = parse_iso_datetime(scheduled_raw if isinstance(scheduled_raw, str) else None)
    if scheduled_start is None:
        return None

    # URLを組み立てるコメント
    url = f"https://www.youtube.com/watch?v={video_id}"

    # チャンネル名のフォールバックを行うコメント
    if not channel_title:
        channel_title = channel_id

    return YouTubeUpcomingInfo(
        video_id=video_id,
        scheduled_start=scheduled_start,
        title=title_text,
        channel_title=channel_title,
        url=url,
    )


# Twitchの配信情報を取得する関数に関するコメント
async def fetch_twitch_stream_info(
    access_token: str,
    client_id: str,
    user_login: str,
) -> Optional[TwitchStreamInfo]:
    """Twitchの配信情報を取得して整形する。"""

    # リクエストヘッダーを組み立てるコメント
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Client-Id": client_id,
    }

    # クエリパラメータを組み立てるコメント
    params = {
        "user_login": user_login,
    }

    # 配信情報を取得するコメント
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(TWITCH_STREAMS_ENDPOINT, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        LOGGER.exception("Twitch配信情報の取得に失敗しました: %s", exc)
        raise

    # 配信が存在しない場合はNoneを返すコメント
    items = data.get("data")
    if not isinstance(items, list) or not items:
        return None

    # 先頭の配信情報を取得するコメント
    item = items[0] if isinstance(items[0], dict) else {}
    stream_id = item.get("id")
    if not isinstance(stream_id, str) or not stream_id.strip():
        raise ValueError("Twitch配信IDの取得に失敗しました。")

    # 同接数を整数として扱うコメント
    viewer_count = item.get("viewer_count")
    try:
        viewer_count_int = int(viewer_count)
    except (TypeError, ValueError):
        viewer_count_int = 0
    if viewer_count_int < 0:
        viewer_count_int = 0

    # 配信開始時刻を取り出すコメント
    started_at_raw = item.get("started_at")
    started_at = parse_iso_datetime(started_at_raw if isinstance(started_at_raw, str) else None)
    if started_at is None:
        started_at = time.time()

    # 配信タイトルを取り出すコメント
    title_value = item.get("title")
    title_text = title_value.strip() if isinstance(title_value, str) else ""

    return TwitchStreamInfo(
        stream_id=stream_id.strip(),
        started_at=started_at,
        viewer_count=viewer_count_int,
        title=title_text,
    )


# Twitchのユーザー名を解決する関数に関するコメント
async def resolve_twitch_nick(settings: Settings, token_manager: TwitchTokenManager) -> str:
    """環境変数またはAPIからTwitchユーザー名を解決する。"""

    # 環境変数があればそれを優先するコメント
    if settings.twitch_nick:
        return settings.twitch_nick

    # アクセストークンを使ってユーザー名を取得するコメント
    access_token = await token_manager.get_access_token()
    login = await fetch_twitch_user_login(access_token, settings.twitch_client_id)
    LOGGER.info("Twitchユーザー名を自動取得しました: %s", login)
    return login


# 投稿用テキストを安全に整形する関数に関するコメント
def normalize_message_text(text: str) -> str:
    """改行や余計な空白を整形して返す。"""

    # 空白をまとめてトリムするコメント
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned


# Xの文字数制限に合わせて切り詰める関数に関するコメント
def truncate_for_x(text: str, max_length: int) -> str:
    """最大長を超える場合は末尾を切り詰める。"""

    # 長さチェックと切り詰め処理のコメント
    if len(text) <= max_length:
        return text
    if max_length <= 3:
        return text[:max_length]
    return f"{text[: max_length - 3]}..."


# ハッシュタグを末尾に追加する関数に関するコメント
def append_hashtag(text: str, hashtag: str, max_length: int) -> str:
    """指定したハッシュタグを投稿文末尾に追加する。"""

    # 既に含まれている場合はそのまま返すコメント
    if hashtag in text:
        return text

    # 追加する末尾の文字列を作るコメント
    suffix = f"\n\n{hashtag}"
    if len(text) + len(suffix) <= max_length:
        return f"{text}{suffix}"

    # 末尾が入るように本文を切り詰めるコメント
    available_length = max_length - len(suffix)
    if available_length <= 0:
        return truncate_for_x(hashtag, max_length)

    trimmed_text = truncate_for_x(text, available_length)
    return f"{trimmed_text}{suffix}"


# ツイート本文を構築する関数に関するコメント
def build_tweet(message: str) -> str:
    """投稿用のテキストを組み立てる。"""

    # 指定フォーマットで本文を構成するコメント
    base_text = f"{POST_HEADER}\n\n{message}"
    return truncate_for_x(base_text, MAX_TWEET_LENGTH)


# 返信対象のメンションを先頭に追加する関数に関するコメント
def apply_reply_mentions(text: str, mentions: Tuple[str, ...]) -> str:
    """返信可能アカウントのメンションを先頭に付ける。"""

    # メンションがなければそのまま返すコメント
    if not mentions:
        return text

    # メンションのプレフィックスを作るコメント
    mention_prefix = " ".join(f"@{mention}" for mention in mentions)
    combined_text = f"{mention_prefix} {text}"

    # 文字数上限に合わせて切り詰めるコメント
    return truncate_for_x(combined_text, MAX_TWEET_LENGTH)


# 配信サマリー投稿文を構築する関数に関するコメント
def build_stream_summary_tweet(session: StreamSession, ended_at: float) -> str:
    """配信の同接推移まとめ用の投稿文を作る。"""

    # サンプル数が0の場合は安全に整形するコメント
    if not session.samples:
        summary_text = "配信同接推移\n\n同接データが取得できませんでした。"
        return truncate_for_x(summary_text, MAX_TWEET_LENGTH)

    # Twitchの統計値を計算するコメント
    twitch_max, twitch_avg = compute_viewer_stats(session.samples)

    # YouTubeの合算統計を計算するコメント
    youtube_counts = aggregate_youtube_counts(session.youtube_channels)
    youtube_max = max(youtube_counts) if youtube_counts else 0
    youtube_avg = int(sum(youtube_counts) / max(1, len(youtube_counts))) if youtube_counts else 0

    # 見出しの日付を整形するコメント
    header_date = format_month_day(ended_at)

    # 投稿文を組み立てるコメント
    summary_lines = [
        f"【{header_date} 同接推移📈】",
        "",
        "Twitch",
        f"最大同時接続者数：{twitch_max}人",
        f"平均同時接続者数：{twitch_avg}人",
    ]

    # YouTubeの統計値を追加するコメント
    if youtube_counts:
        total_max = twitch_max + youtube_max
        summary_lines.extend(
            [
                "",
                "YouTube",
                f"最大同時接続者数：{youtube_max}人",
                f"平均同時接続者数：{youtube_avg}人",
                "",
                f"最大同時接続者数（総計）：{total_max}人",
            ]
        )

    summary_text = "\n".join(summary_lines)
    return truncate_for_x(summary_text, MAX_TWEET_LENGTH)


# YouTube配信予定の投稿文を構築する関数に関するコメント
def build_youtube_upcoming_tweet(info: YouTubeUpcomingInfo, now: float) -> str:
    """YouTube配信予定の告知文を作る。"""

    # 残り時間を計算するコメント
    time_text = format_time_until(info.scheduled_start, now)
    channel_text = info.channel_title or "チャンネル"
    title_text = clip_text(info.title, 40) if info.title else "タイトル未設定"
    scheduled_text = format_local_time(info.scheduled_start)

    # 告知文を組み立てるコメント
    message = (
        f"【🔴{time_text}に{channel_text}の配信が始まります】\n\n"
        f"開始予定: {scheduled_text}\n"
        f"タイトル: {title_text}\n\n"
        f"{info.url}"
    )
    return truncate_for_x(message, MAX_TWEET_LENGTH)


# 同接グラフを生成する関数に関するコメント
def generate_viewer_graph(
    samples: Deque[ViewerSample],
    output_path: str,
    title: str,
    youtube_series: Optional[List[Tuple[str, Deque[ViewerSample]]]] = None,
    twitch_label: str = "Twitch",
) -> None:
    """同接推移のPNGグラフを生成する。"""

    # 依存ライブラリを遅延読み込みするコメント
    import matplotlib

    # GUIが不要なAggバックエンドを使うコメント
    matplotlib.use("Agg")

    # 必要なモジュールを読み込むコメント
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker

    # 日本語フォントを設定するコメント
    font_prop = setup_matplotlib_japanese_font()

    # サンプルの有無を判定するコメント
    has_twitch_samples = bool(samples)
    has_youtube_samples = bool(youtube_series)

    # サンプルがない場合は空のグラフを作るコメント
    if not has_twitch_samples and not has_youtube_samples:
        fig, ax = plt.subplots(figsize=(10, 4), dpi=160)
        ax.set_title("同接推移", fontproperties=font_prop)
        ax.text(0.5, 0.5, "データなし", ha="center", va="center", fontproperties=font_prop)
        ax.axis("off")
        fig.tight_layout()
        fig.savefig(output_path)
        plt.close(fig)
        return

    # グラフを描画するコメント
    fig, ax = plt.subplots(figsize=(12, 5), dpi=160)

    # Twitchの系列を描画するコメント
    if has_twitch_samples:
        times = [datetime.fromtimestamp(sample.timestamp) for sample in samples]
        counts = [sample.viewer_count for sample in samples]
        label_text = twitch_label if twitch_label else "Twitch"
        ax.plot(times, counts, color="#e56b6f", linewidth=2, label=label_text)
        ax.fill_between(times, counts, color="#e56b6f", alpha=0.18)

    # YouTubeの系列を描画するコメント
    if has_youtube_samples and youtube_series is not None:
        youtube_colors = ["#2a9d8f", "#1f7a70", "#5fb3a7", "#3d8b80"]
        for index, (label, series_samples) in enumerate(youtube_series):
            if not series_samples:
                continue
            youtube_times = [
                datetime.fromtimestamp(sample.timestamp) for sample in series_samples
            ]
            youtube_counts = [sample.viewer_count for sample in series_samples]
            color = youtube_colors[index % len(youtube_colors)]
            ax.plot(youtube_times, youtube_counts, color=color, linewidth=2, label=label)

    # 日本語ラベルを設定するコメント
    ax.set_title("同接推移", fontproperties=font_prop)
    ax.set_xlabel("時刻", fontproperties=font_prop)
    ax.set_ylabel("同接数", fontproperties=font_prop)

    # 配信タイトルをサブタイトルとして表示するコメント
    if title:
        ax.text(
            0.01,
            0.98,
            clip_text(title, 80),
            transform=ax.transAxes,
            va="top",
            fontproperties=font_prop,
        )

    # 軸フォーマットとグリッドを整えるコメント
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    # Y軸の数値を整数で表示するコメント
    ax.yaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    # Y軸の数値フォーマットを整数表示に固定するコメント
    axis_formatter = mticker.ScalarFormatter(useMathText=False)
    axis_formatter.set_scientific(False)
    axis_formatter.set_useOffset(False)
    ax.yaxis.set_major_formatter(axis_formatter)
    ax.grid(True, linestyle="--", alpha=0.3)

    # 凡例を表示するコメント
    if has_twitch_samples or has_youtube_samples:
        ax.legend(prop=font_prop)

    # レイアウトを調整して保存するコメント
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)


# X投稿を順番に処理するクラスに関するコメント
class XPoster:
    """Xへの投稿をキューで順次実行するクラス。"""

    # 初期化処理に関するコメント
    def __init__(
        self,
        client: tweepy.Client,
        media_client: tweepy.API,
        interval_seconds: float,
        queue_size: int,
        reply_setting: str,
        reply_mentions: Tuple[str, ...],
    ) -> None:
        # クライアントと制御用の値を保持するコメント
        self._client = client
        self._media_client = media_client
        self._interval_seconds = interval_seconds
        self._queue: asyncio.Queue[Optional[XPostJob]] = asyncio.Queue(maxsize=queue_size)
        self._task: Optional[asyncio.Task[None]] = None
        self._last_post_time = 0.0
        self._reply_setting = reply_setting
        self._reply_mentions = reply_mentions

    # ワーカー開始のためのコメント
    def start(self) -> None:
        """投稿ワーカーを起動する。"""

        # 二重起動を避けるコメント
        if self._task is None:
            self._task = asyncio.create_task(self._worker())

    # キューに投稿を追加するためのコメント
    async def enqueue_text(self, text: str) -> None:
        """テキスト投稿をキューに追加する。"""

        # 空文字は無視するコメント
        if not text:
            return
        await self._enqueue_job(XPostJob(text=text))

    # 画像付き投稿を追加するコメント
    async def enqueue_media(self, text: str, media_path: str, cleanup_path: Optional[str]) -> None:
        """画像付き投稿をキューに追加する。"""

        # 投稿条件を簡易チェックするコメント
        if not text or not media_path:
            return
        await self._enqueue_job(XPostJob(text=text, media_path=media_path, cleanup_path=cleanup_path))

    # 共通のキュー追加処理に関するコメント
    async def _enqueue_job(self, job: XPostJob) -> None:
        """投稿ジョブをキューに追加する。"""

        # キューが満杯の場合に落とすコメント
        try:
            self._queue.put_nowait(job)
        except asyncio.QueueFull:
            LOGGER.info("投稿キューが満杯のためメッセージを破棄しました。")

    # ワーカーの終了処理に関するコメント
    async def close(self) -> None:
        """投稿ワーカーを終了する。"""

        # タスクがない場合は何もしないコメント
        if self._task is None:
            return
        await self._queue.put(None)
        await self._task

    # 投稿間隔を守るためのコメント
    async def _wait_for_interval(self) -> None:
        """設定された投稿間隔を満たすまで待機する。"""

        # 前回投稿時刻との差分を計算するコメント
        elapsed = time.monotonic() - self._last_post_time
        remaining = self._interval_seconds - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)

    # 実際にXに投稿する処理に関するコメント
    async def _post_to_x(self, job: XPostJob) -> None:
        """XのAPIで投稿を行う。"""

        # 投稿前の間隔調整に関するコメント
        await self._wait_for_interval()
        try:
            # 返信対象のメンションを付けるコメント
            post_text = job.text
            if self._reply_setting == "mentionedUsers":
                post_text = apply_reply_mentions(post_text, self._reply_mentions)
            # ハッシュタグを付けるコメント
            post_text = append_hashtag(post_text, POST_HASHTAG, MAX_TWEET_LENGTH)

            if job.media_path:
                # メディアをアップロードするコメント
                media = await asyncio.to_thread(self._media_client.media_upload, job.media_path)
                media_id = getattr(media, "media_id_string", None) or str(media.media_id)
                await asyncio.to_thread(
                    self._client.create_tweet,
                    text=post_text,
                    media_ids=[media_id],
                    reply_settings=self._reply_setting,
                )
            else:
                # テキストのみ投稿するコメント
                await asyncio.to_thread(
                    self._client.create_tweet,
                    text=post_text,
                    reply_settings=self._reply_setting,
                )
            self._last_post_time = time.monotonic()
            LOGGER.info("Xに投稿しました。")
        except Exception as exc:
            LOGGER.exception("Xへの投稿に失敗しました: %s", exc)
        finally:
            # 後始末が必要なファイルを削除するコメント
            if job.cleanup_path:
                try:
                    os.remove(job.cleanup_path)
                except OSError:
                    LOGGER.warning("投稿後のファイル削除に失敗しました: %s", job.cleanup_path)

    # キューから順に投稿するワーカーに関するコメント
    async def _worker(self) -> None:
        """キューの内容を順次Xに投稿する。"""

        # キューの受信ループに関するコメント
        while True:
            job = await self._queue.get()
            try:
                if job is None:
                    return
                await self._post_to_x(job)
            finally:
                self._queue.task_done()


# Twitch IRCの接続情報を組み立てる関数に関するコメント
async def build_twitch_credentials(
    settings: Settings,
    token_manager: TwitchTokenManager,
    nick: str,
) -> Tuple[str, str]:
    """Twitch接続用のPASS/NICKを決定して返す。"""

    # アクセストークンを取得して接続情報にするコメント
    access_token = await token_manager.get_access_token()
    return normalize_twitch_token(access_token), nick


# Twitch IRCのタグを除去する関数に関するコメント
def strip_irc_tags(line: str) -> str:
    """IRCメッセージ先頭のタグ情報を除去する。"""

    # タグがない場合はそのまま返すコメント
    if not line.startswith("@"):
        return line

    # 最初の空白までをタグとして除去するコメント
    parts = line.split(" ", 1)
    return parts[1] if len(parts) == 2 else ""


# PRIVMSGを解析する関数に関するコメント
def parse_privmsg(line: str) -> Optional[Tuple[str, str, str]]:
    """IRCのPRIVMSGからユーザー名とチャンネルと本文を取り出す。"""

    # 正規表現でメッセージを解析するコメント
    match = PRIVMSG_PATTERN.match(line)
    if not match:
        return None
    return match.group("user"), match.group("channel"), match.group("message")


# Twitch IRCのメッセージ監視クラスに関するコメント
class TwitchIRCListener:
    """Twitch IRCに接続してコメントを監視するクラス。"""

    # 初期化処理に関するコメント
    def __init__(
        self,
        settings: Settings,
        poster: XPoster,
        token_manager: TwitchTokenManager,
        nick: str,
    ) -> None:
        # 設定値とポスターを保持するコメント
        self._settings = settings
        self._poster = poster
        self._token_manager = token_manager
        self._nick = nick
        self._stop_event = asyncio.Event()

    # 停止指示を出すためのコメント
    def stop(self) -> None:
        """監視ループを停止する。"""

        # 停止イベントを設定するコメント
        self._stop_event.set()

    # IRC接続と監視を行うためのコメント
    async def run(self) -> None:
        """接続が切れても再接続しながら監視を続ける。"""

        # 再接続ループに関するコメント
        while not self._stop_event.is_set():
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                # キャンセル時はそのまま伝播させるコメント
                raise
            except Exception as exc:
                LOGGER.exception("Twitch接続中に例外が発生しました: %s", exc)

            # 再接続まで待機するコメント
            if not self._stop_event.is_set():
                await asyncio.sleep(TWITCH_RECONNECT_DELAY_SECONDS)

    # 実際の接続と受信処理に関するコメント
    async def _connect_and_listen(self) -> None:
        """Twitch IRCに接続してメッセージを受信する。"""

        # 認証情報を組み立てるコメント
        pass_value, nick = await build_twitch_credentials(
            self._settings,
            self._token_manager,
            self._nick,
        )
        channel = self._settings.twitch_channel

        # SSL設定を必要に応じて作成するコメント
        ssl_context = ssl.create_default_context() if TWITCH_USE_TLS else None

        # IRCサーバーへ接続するコメント
        LOGGER.info("Twitch IRCへ接続します。サーバー: %s", TWITCH_SERVER)
        reader, writer = await asyncio.open_connection(
            TWITCH_SERVER,
            TWITCH_PORT,
            ssl=ssl_context,
        )

        # 接続後の後始末を確実に行うコメント
        try:
            # ログイン情報を送信するコメント
            writer.write(f"PASS {pass_value}\r\n".encode("utf-8"))
            writer.write(f"NICK {nick}\r\n".encode("utf-8"))
            writer.write(f"JOIN #{channel}\r\n".encode("utf-8"))
            await writer.drain()

            # 接続完了ログを出すコメント
            LOGGER.info("認証モードでTwitchコメント監視を開始します。ログイン名: %s", nick)

            # 受信ループに関するコメント
            while not self._stop_event.is_set():
                raw_line = await reader.readline()
                if not raw_line:
                    LOGGER.info("Twitch IRCの接続が切断されました。")
                    return

                # 受信行をデコードするコメント
                decoded_line = raw_line.decode("utf-8", errors="ignore").strip("\r\n")
                await self._handle_irc_line(decoded_line, writer)
        finally:
            # 接続のクローズ処理を行うコメント
            writer.close()
            if hasattr(writer, "wait_closed"):
                await writer.wait_closed()

    # IRC行を処理する関数に関するコメント
    async def _handle_irc_line(self, line: str, writer: asyncio.StreamWriter) -> None:
        """IRCメッセージを処理して投稿対象ならキューに入れる。"""

        # PINGに応答するコメント
        if line.startswith("PING "):
            await self._send_pong(line, writer)
            return

        # タグを除去してPRIVMSGを解析するコメント
        stripped_line = strip_irc_tags(line)
        parsed = parse_privmsg(stripped_line)
        if parsed is None:
            return

        author, channel, message = parsed
        if channel.lower() != self._settings.twitch_channel:
            return

        # 指定ユーザー以外のコメントは除外するコメント
        if author.lower() != TARGET_TWITCH_USER_LOWER:
            return

        # メッセージ本文を整形するコメント
        content = normalize_message_text(message)
        if not content:
            return

        # 投稿文を組み立ててキューに追加するコメント
        tweet_text = build_tweet(content)
        await self._poster.enqueue_text(tweet_text)

    # PINGへの応答を行う関数に関するコメント
    async def _send_pong(self, line: str, writer: asyncio.StreamWriter) -> None:
        """Twitch IRCのPINGにPONGで応答する。"""

        # PINGの宛先を取得して返すコメント
        payload = line.split(" ", 1)[1] if " " in line else ""
        writer.write(f"PONG {payload}\r\n".encode("utf-8"))
        await writer.drain()


# Twitch配信の同接を監視するクラスに関するコメント
class TwitchStreamMonitor:
    """Twitch配信の同接推移を記録して投稿する。"""

    # 初期化処理に関するコメント
    def __init__(
        self,
        settings: Settings,
        poster: XPoster,
        token_manager: TwitchTokenManager,
    ) -> None:
        # 設定と依存関係を保持するコメント
        self._settings = settings
        self._poster = poster
        self._token_manager = token_manager
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task[None]] = None
        self._lock = asyncio.Lock()
        self._session: Optional[StreamSession] = None
        self._youtube_last_polled_at = 0.0
        self._youtube_upcoming_last_polled_at = 0.0
        self._youtube_upcoming_posted_ids = self._load_youtube_upcoming_cache()
        self._stream_history = self._load_stream_history_cache()
        self._monthly_stats_posted = self._load_monthly_stats_cache()

    # 監視タスクを開始するコメント
    def start(self) -> None:
        """配信監視タスクを開始する。"""

        # 二重起動を避けるコメント
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    # 停止指示を出すコメント
    def stop(self) -> None:
        """配信監視を停止する。"""

        # 停止イベントを通知するコメント
        self._stop_event.set()

    # 停止完了まで待機するコメント
    async def close(self) -> None:
        """監視タスクの終了を待つ。"""

        # タスクがない場合は何もしないコメント
        if self._task is None:
            return
        await self._task

    # メインの監視ループに関するコメント
    async def _run(self) -> None:
        """一定間隔で配信状態を確認する。"""

        # 監視ループを実行するコメント
        while not self._stop_event.is_set():
            try:
                await self._poll_once()
            except Exception as exc:
                LOGGER.exception("Twitch配信監視中に例外が発生しました: %s", exc)
            await self._wait_for_next_poll()

    # 次のポーリングまで待機するコメント
    async def _wait_for_next_poll(self) -> None:
        """停止要求が来るまで待機する。"""

        # 取得間隔を決定するコメント
        poll_interval = self._settings.twitch_stream_poll_interval_seconds
        if self._is_youtube_enabled():
            poll_interval = min(
                poll_interval,
                self._settings.youtube_poll_interval_seconds,
                self._settings.youtube_upcoming_poll_interval_seconds,
            )

        # 指定間隔または停止まで待機するコメント
        try:
            await asyncio.wait_for(
                self._stop_event.wait(),
                timeout=poll_interval,
            )
        except asyncio.TimeoutError:
            return

    # YouTube連携の有効判定を行うコメント
    def _is_youtube_enabled(self) -> bool:
        """YouTube連携が設定されているか判定する。"""

        # APIキーとチャンネルID群がある場合のみ有効とするコメント
        return bool(self._settings.youtube_api_key and self._settings.youtube_channel_ids)

    # YouTube配信予定のキャッシュを読み込むコメント
    def _load_youtube_upcoming_cache(self) -> Set[str]:
        """配信予定の投稿済みIDを読み込む。"""

        # ファイルパスを組み立てるコメント
        cache_path = Path(__file__).resolve().parent / YOUTUBE_UPCOMING_CACHE_FILENAME
        if not cache_path.is_file():
            return set()

        # JSONを読み込むコメント
        try:
            with cache_path.open("r", encoding="utf-8") as file_handle:
                data = json.load(file_handle)
        except (OSError, json.JSONDecodeError):
            return set()

        # リストをセットに変換するコメント
        if not isinstance(data, list):
            return set()
        return {item for item in data if isinstance(item, str) and item.strip()}

    # 配信履歴キャッシュを読み込むコメント
    def _load_stream_history_cache(self) -> List[dict]:
        """配信履歴のキャッシュを読み込む。"""

        # ファイルパスを組み立てるコメント
        cache_path = Path(__file__).resolve().parent / STREAM_HISTORY_CACHE_FILENAME
        if not cache_path.is_file():
            return []

        # JSONを読み込むコメント
        try:
            with cache_path.open("r", encoding="utf-8") as file_handle:
                data = json.load(file_handle)
        except (OSError, json.JSONDecodeError):
            return []

        # リスト以外は無視するコメント
        if not isinstance(data, list):
            return []

        # 有効なレコードだけを残すコメント
        records = []
        for item in data:
            if not isinstance(item, dict):
                continue
            started_at = item.get("started_at")
            ended_at = item.get("ended_at")
            stream_id = item.get("stream_id")
            if not isinstance(started_at, (int, float)):
                continue
            if not isinstance(ended_at, (int, float)):
                continue
            if not isinstance(stream_id, str) or not stream_id.strip():
                continue
            if ended_at <= started_at:
                continue
            records.append(
                {
                    "stream_id": stream_id,
                    "started_at": float(started_at),
                    "ended_at": float(ended_at),
                }
            )

        return records

    # 配信履歴キャッシュを書き込むコメント
    def _save_stream_history_cache(self) -> None:
        """配信履歴のキャッシュを書き込む。"""

        # ファイルパスを組み立てるコメント
        cache_path = Path(__file__).resolve().parent / STREAM_HISTORY_CACHE_FILENAME

        # JSONを書き込むコメント
        try:
            with cache_path.open("w", encoding="utf-8") as file_handle:
                json.dump(self._stream_history, file_handle, ensure_ascii=False, indent=2)
                file_handle.write("\n")
        except OSError:
            LOGGER.warning("配信履歴キャッシュの保存に失敗しました。")

    # 月次投稿のキャッシュを読み込むコメント
    def _load_monthly_stats_cache(self) -> Set[str]:
        """月次配信統計の投稿済み月を読み込む。"""

        # ファイルパスを組み立てるコメント
        cache_path = Path(__file__).resolve().parent / MONTHLY_STATS_CACHE_FILENAME
        if not cache_path.is_file():
            return set()

        # JSONを読み込むコメント
        try:
            with cache_path.open("r", encoding="utf-8") as file_handle:
                data = json.load(file_handle)
        except (OSError, json.JSONDecodeError):
            return set()

        # リストをセットに変換するコメント
        if not isinstance(data, list):
            return set()
        return {item for item in data if isinstance(item, str) and item.strip()}

    # 月次投稿のキャッシュを書き込むコメント
    def _save_monthly_stats_cache(self) -> None:
        """月次配信統計の投稿済み月を保存する。"""

        # ファイルパスを組み立てるコメント
        cache_path = Path(__file__).resolve().parent / MONTHLY_STATS_CACHE_FILENAME
        payload = sorted(self._monthly_stats_posted)

        # JSONを書き込むコメント
        try:
            with cache_path.open("w", encoding="utf-8") as file_handle:
                json.dump(payload, file_handle, ensure_ascii=False, indent=2)
                file_handle.write("\n")
        except OSError:
            LOGGER.warning("月次配信統計キャッシュの保存に失敗しました。")

    # YouTube配信予定のキャッシュを保存するコメント
    def _save_youtube_upcoming_cache(self) -> None:
        """配信予定の投稿済みIDを保存する。"""

        # ファイルパスを組み立てるコメント
        cache_path = Path(__file__).resolve().parent / YOUTUBE_UPCOMING_CACHE_FILENAME
        payload = sorted(self._youtube_upcoming_posted_ids)

        # JSONを書き込むコメント
        try:
            with cache_path.open("w", encoding="utf-8") as file_handle:
                json.dump(payload, file_handle, ensure_ascii=False, indent=2)
                file_handle.write("\n")
        except OSError:
            LOGGER.warning("YouTube配信予定キャッシュの保存に失敗しました。")

    # YouTube配信情報を取得するコメント
    async def _fetch_youtube_stream_infos(self, now: float) -> Dict[str, YouTubeStreamInfo]:
        """必要に応じてYouTube配信情報を取得する。"""

        # 取得結果を初期化するコメント
        results: Dict[str, YouTubeStreamInfo] = {}

        # 設定がなければ取得しないコメント
        if not self._is_youtube_enabled():
            return results

        # 取得間隔を満たしていなければスキップするコメント
        if (now - self._youtube_last_polled_at) < self._settings.youtube_poll_interval_seconds:
            return results

        # 最終取得時刻を更新するコメント
        self._youtube_last_polled_at = now

        # APIキーとチャンネルID群を取り出すコメント
        api_key = self._settings.youtube_api_key
        channel_ids = self._settings.youtube_channel_ids
        if not api_key or not channel_ids:
            return results

        # チャンネルごとに取得タスクを作るコメント
        tasks = []
        for channel_id in channel_ids:
            tasks.append(fetch_youtube_stream_info(api_key=api_key, channel_id=channel_id))

        # 取得結果を待つコメント
        try:
            fetched = await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as exc:
            LOGGER.exception("YouTube配信情報の取得に失敗しました: %s", exc)
            return results

        # チャンネルごとの結果を整理するコメント
        for channel_id, result in zip(channel_ids, fetched):
            if isinstance(result, Exception):
                LOGGER.error("YouTube配信情報の取得に失敗しました: %s", result)
                continue
            if result is None:
                continue
            results[channel_id] = result

        return results

    # YouTube配信予定情報を取得するコメント
    async def _fetch_youtube_upcoming_infos(self, now: float) -> Dict[str, YouTubeUpcomingInfo]:
        """必要に応じてYouTube配信予定情報を取得する。"""

        # 取得結果を初期化するコメント
        results: Dict[str, YouTubeUpcomingInfo] = {}

        # 設定がなければ取得しないコメント
        if not self._is_youtube_enabled():
            return results

        # 取得間隔を満たしていなければスキップするコメント
        if (now - self._youtube_upcoming_last_polled_at) < self._settings.youtube_upcoming_poll_interval_seconds:
            return results

        # 最終取得時刻を更新するコメント
        self._youtube_upcoming_last_polled_at = now

        # APIキーとチャンネルID群を取り出すコメント
        api_key = self._settings.youtube_api_key
        channel_ids = self._settings.youtube_channel_ids
        if not api_key or not channel_ids:
            return results

        # チャンネルごとに取得タスクを作るコメント
        tasks = []
        for channel_id in channel_ids:
            tasks.append(fetch_youtube_upcoming_info(api_key=api_key, channel_id=channel_id))

        # 取得結果を待つコメント
        try:
            fetched = await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as exc:
            LOGGER.exception("YouTube配信予定情報の取得に失敗しました: %s", exc)
            return results

        # チャンネルごとの結果を整理するコメント
        for channel_id, result in zip(channel_ids, fetched):
            if isinstance(result, Exception):
                LOGGER.error("YouTube配信予定情報の取得に失敗しました: %s", result)
                continue
            if result is None:
                continue
            results[channel_id] = result

        return results

    # 配信履歴を追加するコメント
    def _record_stream_history(self, session: StreamSession, ended_at: float) -> None:
        """配信履歴をキャッシュに追加する。"""

        # 正常な時刻のみ記録するコメント
        started_at = session.started_at
        if ended_at <= started_at:
            return

        # 新しいレコードを作成するコメント
        record = {
            "stream_id": session.stream_id,
            "started_at": float(started_at),
            "ended_at": float(ended_at),
        }

        # 同じIDがあれば置き換えるコメント
        self._stream_history = [
            item for item in self._stream_history if item.get("stream_id") != session.stream_id
        ]
        self._stream_history.append(record)

        # 古い履歴を削るコメント
        cutoff = time.time() - 400 * 24 * 60 * 60
        self._stream_history = [
            item for item in self._stream_history if item.get("ended_at", 0) >= cutoff
        ]

        # キャッシュを書き込むコメント
        self._save_stream_history_cache()

    # 月次配信統計を投稿するコメント
    async def _maybe_post_monthly_stats(self, now: float) -> None:
        """月初めに先月の配信統計を投稿する。"""

        # 現在時刻をローカル日時に変換するコメント
        now_local = datetime.fromtimestamp(now)

        # 月初め以外は処理しないコメント
        if now_local.day != 1:
            return

        # 先月の期間を算出するコメント
        current_month_start = datetime(now_local.year, now_local.month, 1)
        previous_month_end = current_month_start - timedelta(days=1)
        previous_month_start = datetime(previous_month_end.year, previous_month_end.month, 1)
        previous_previous_end = previous_month_start - timedelta(days=1)
        previous_previous_start = datetime(previous_previous_end.year, previous_previous_end.month, 1)
        previous_month_key = f"{previous_month_start.year:04d}-{previous_month_start.month:02d}"

        # 既に投稿済みならスキップするコメント
        if previous_month_key in self._monthly_stats_posted:
            return

        # 先月の配信統計を計算するコメント
        start_timestamp = previous_month_start.timestamp()
        end_timestamp = current_month_start.timestamp()
        total_days, total_seconds = self._calculate_monthly_stats(start_timestamp, end_timestamp)

        # 先々月の配信統計を計算するコメント
        prev_start_timestamp = previous_previous_start.timestamp()
        prev_end_timestamp = previous_month_start.timestamp()
        prev_days, prev_seconds = self._calculate_monthly_stats(prev_start_timestamp, prev_end_timestamp)

        # 投稿文を作成するコメント
        message = build_monthly_stats_tweet(
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            total_days=total_days,
            total_seconds=total_seconds,
            diff_days=total_days - prev_days,
            diff_seconds=total_seconds - prev_seconds,
        )

        # 投稿をキューに追加するコメント
        await self._poster.enqueue_text(message)
        self._monthly_stats_posted.add(previous_month_key)
        self._save_monthly_stats_cache()

    # 月次配信統計を計算するコメント
    def _calculate_monthly_stats(self, start_timestamp: float, end_timestamp: float) -> Tuple[int, float]:
        """指定期間の配信日数と総配信時間を計算する。"""

        # 配信日数を保持するコメント
        active_days: Set[datetime.date] = set()
        total_seconds = 0.0

        # 履歴から集計するコメント
        for item in self._stream_history:
            started_at = float(item.get("started_at", 0))
            ended_at = float(item.get("ended_at", 0))
            if ended_at <= start_timestamp or started_at >= end_timestamp:
                continue

            # 期間内の重なりを計算するコメント
            overlap_start = max(started_at, start_timestamp)
            overlap_end = min(ended_at, end_timestamp)
            if overlap_end <= overlap_start:
                continue

            total_seconds += overlap_end - overlap_start

            # 日付単位で配信日数を数えるコメント
            current_date = datetime.fromtimestamp(overlap_start).date()
            last_date = datetime.fromtimestamp(max(overlap_start, overlap_end - 1)).date()
            while current_date <= last_date:
                active_days.add(current_date)
                current_date += timedelta(days=1)

        return len(active_days), total_seconds

    # YouTube配信予定の告知を投稿するコメント
    async def _post_youtube_upcoming_infos(
        self,
        upcoming_infos: Dict[str, YouTubeUpcomingInfo],
        now: float,
    ) -> None:
        """YouTube配信予定を未投稿なら投稿する。"""

        # 投稿対象がない場合は終了するコメント
        if not upcoming_infos:
            return

        # 新規投稿があるかを判定するコメント
        posted_any = False
        for upcoming_info in upcoming_infos.values():
            # 既に投稿済みならスキップするコメント
            if upcoming_info.video_id in self._youtube_upcoming_posted_ids:
                continue
            # 予定時刻が過去ならスキップするコメント
            if upcoming_info.scheduled_start <= now:
                continue

            # 投稿文を作成するコメント
            message = build_youtube_upcoming_tweet(upcoming_info, now)
            await self._poster.enqueue_text(message)
            self._youtube_upcoming_posted_ids.add(upcoming_info.video_id)
            posted_any = True

        # 新規投稿があればキャッシュを保存するコメント
        if posted_any:
            self._save_youtube_upcoming_cache()

    # 配信状態を1回確認するコメント
    async def _poll_once(self) -> None:
        """配信状態を取得し、同接を記録する。"""

        # アクセストークンを取得するコメント
        access_token = await self._token_manager.get_access_token()

        # Twitch配信情報を取得するコメント
        stream_info = await fetch_twitch_stream_info(
            access_token=access_token,
            client_id=self._settings.twitch_client_id,
            user_login=self._settings.twitch_channel,
        )

        # 現在時刻を取得するコメント
        now = time.time()

        # YouTube配信情報を必要に応じて取得するコメント
        youtube_infos = await self._fetch_youtube_stream_infos(now)

        # YouTube配信予定情報を取得して投稿するコメント
        upcoming_infos = await self._fetch_youtube_upcoming_infos(now)
        await self._post_youtube_upcoming_infos(upcoming_infos, now)

        # 月次配信統計を必要に応じて投稿するコメント
        await self._maybe_post_monthly_stats(now)

        # 配信中かどうかで処理を分岐するコメント
        if stream_info is None:
            await self._handle_stream_offline(now)
        else:
            await self._handle_stream_live(stream_info, now, youtube_infos)

    # 配信中の処理に関するコメント
    async def _handle_stream_live(
        self,
        stream_info: TwitchStreamInfo,
        now: float,
        youtube_infos: Dict[str, YouTubeStreamInfo],
    ) -> None:
        """配信中の同接情報を記録する。"""

        # セッションの更新をロック内で行うコメント
        previous_session = None
        async with self._lock:
            if self._session is None:
                # 新しい配信セッションを作成するコメント
                self._session = StreamSession(
                    stream_id=stream_info.stream_id,
                    started_at=stream_info.started_at,
                    title=stream_info.title,
                    samples=deque(maxlen=self._settings.twitch_stream_sample_max_points),
                    youtube_channel_ids=self._settings.youtube_channel_ids,
                    youtube_channels={},
                )
            elif self._session.stream_id != stream_info.stream_id:
                # 配信IDが変わった場合は前のセッションを退避するコメント
                previous_session = self._session
                self._session = StreamSession(
                    stream_id=stream_info.stream_id,
                    started_at=stream_info.started_at,
                    title=stream_info.title,
                    samples=deque(maxlen=self._settings.twitch_stream_sample_max_points),
                    youtube_channel_ids=self._settings.youtube_channel_ids,
                    youtube_channels={},
                )

            # 同接サンプルを追加するコメント
            self._session.samples.append(
                ViewerSample(
                    timestamp=now,
                    viewer_count=stream_info.viewer_count,
                )
            )

            # YouTubeの同接サンプルを追加するコメント
            for channel_id, youtube_info in youtube_infos.items():
                channel_session = self._session.youtube_channels.get(channel_id)
                if channel_session is None or channel_session.video_id != youtube_info.video_id:
                    self._session.youtube_channels[channel_id] = YouTubeChannelSession(
                        channel_id=channel_id,
                        video_id=youtube_info.video_id,
                        title=youtube_info.title,
                        channel_title=youtube_info.channel_title,
                        started_at=youtube_info.started_at,
                        samples=deque(maxlen=self._settings.youtube_sample_max_points),
                    )
                    channel_session = self._session.youtube_channels[channel_id]
                else:
                    channel_session.title = youtube_info.title
                    channel_session.channel_title = youtube_info.channel_title
                    channel_session.started_at = youtube_info.started_at
                channel_session.samples.append(
                    ViewerSample(
                        timestamp=now,
                        viewer_count=youtube_info.viewer_count,
                    )
                )

        # 配信IDが変わった場合は前セッションを投稿するコメント
        if previous_session is not None:
            await self._post_session_summary(previous_session, now)

    # 配信終了時の処理に関するコメント
    async def _handle_stream_offline(self, now: float) -> None:
        """配信が終了した場合にグラフ投稿を行う。"""

        # セッションを取り出すコメント
        async with self._lock:
            session = self._session
            self._session = None

        # セッションがない場合は何もしないコメント
        if session is None:
            return

        # セッションのサマリーを投稿するコメント
        await self._post_session_summary(session, now)

    # セッションのサマリー投稿処理に関するコメント
    async def _post_session_summary(self, session: StreamSession, ended_at: float) -> None:
        """同接グラフとサマリーを投稿キューに追加する。"""

        # 配信履歴を記録するコメント
        self._record_stream_history(session, ended_at)

        # YouTubeの系列データを整形するコメント
        youtube_series: List[Tuple[str, Deque[ViewerSample]]] = []
        youtube_channel_ids = [
            channel_id
            for channel_id in session.youtube_channel_ids
            if channel_id in session.youtube_channels and session.youtube_channels[channel_id].samples
        ]
        for index, channel_id in enumerate(youtube_channel_ids, start=1):
            channel_session = session.youtube_channels[channel_id]
            label = channel_session.channel_title or channel_id
            if not label:
                label = f"YouTube{index}"
            youtube_series.append((f"[YouTube]{label}", channel_session.samples))

        # グラフ画像を生成するコメント
        graph_path = self._create_graph_path()
        generate_viewer_graph(
            session.samples,
            graph_path,
            session.title,
            youtube_series if youtube_series else None,
            twitch_label=f"[Twitch]{self._settings.twitch_channel}",
        )

        # 投稿文を作成するコメント
        summary_text = build_stream_summary_tweet(session, ended_at)

        # 画像付き投稿をキューに追加するコメント
        await self._poster.enqueue_media(summary_text, graph_path, graph_path)

    # 一時ファイルのパスを作成するコメント
    def _create_graph_path(self) -> str:
        """グラフ保存用の一時ファイルを作成する。"""

        # 一時ファイルを生成してパスを返すコメント
        temp_file = tempfile.NamedTemporaryFile(prefix="viewer_graph_", suffix=".png", delete=False)
        temp_file.close()
        return temp_file.name


# X APIクライアント作成関数に関するコメント
def create_x_client(settings: Settings) -> tweepy.Client:
    """Xのクライアントを生成して返す。"""

    # Tweepyのクライアントを構築するコメント
    return tweepy.Client(
        bearer_token=settings.x_bearer_token,
        consumer_key=settings.x_api_key,
        consumer_secret=settings.x_api_secret,
        access_token=settings.x_access_token,
        access_token_secret=settings.x_access_secret,
        wait_on_rate_limit=True,
    )


# Xのメディア投稿用クライアントを作成する関数に関するコメント
def create_x_media_client(settings: Settings) -> tweepy.API:
    """Xのメディアアップロード用クライアントを生成する。"""

    # OAuth1.0aの認証情報を作成するコメント
    auth = tweepy.OAuth1UserHandler(
        settings.x_api_key,
        settings.x_api_secret,
        settings.x_access_token,
        settings.x_access_secret,
    )

    # TweepyのAPIクライアントを作成するコメント
    return tweepy.API(auth, wait_on_rate_limit=True)


# ログ設定を初期化する関数に関するコメント
def setup_logging() -> None:
    """ログ設定を初期化する。"""

    # ログの基本設定に関するコメント
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


# Bot起動の非同期処理に関するコメント
async def run_bot(settings: Settings) -> None:
    """Botの起動と終了処理を非同期で行う。"""

    # Xクライアントと投稿ワーカーを準備するコメント
    x_client = create_x_client(settings)
    x_media_client = create_x_media_client(settings)
    poster = XPoster(
        client=x_client,
        media_client=x_media_client,
        interval_seconds=settings.x_post_interval_seconds,
        queue_size=settings.x_queue_size,
        reply_setting=settings.x_reply_setting,
        reply_mentions=settings.x_reply_mention_users,
    )

    # Twitchのトークン管理を準備するコメント
    token_manager = TwitchTokenManager(
        client_id=settings.twitch_client_id,
        client_secret=settings.twitch_client_secret,
        refresh_token=settings.twitch_refresh_token,
    )

    # Twitchのユーザー名を解決するコメント
    try:
        resolved_nick = await resolve_twitch_nick(settings, token_manager)
    except Exception as exc:
        LOGGER.exception("Twitchユーザー名解決に失敗しました: %s", exc)
        raise

    # 投稿ワーカーを起動するコメント
    poster.start()

    # Twitch IRCリスナーを起動するコメント
    listener = TwitchIRCListener(settings, poster, token_manager, resolved_nick)

    # Twitch配信監視を起動するコメント
    stream_monitor = TwitchStreamMonitor(settings, poster, token_manager)
    stream_monitor.start()
    try:
        await listener.run()
    finally:
        # クリーンアップ処理を行うコメント
        stream_monitor.stop()
        await stream_monitor.close()
        await poster.close()


# メイン処理に関するコメント
def main() -> None:
    """設定を読み込みBotを起動する。"""

    # ログ初期化のコメント
    setup_logging()

    # 設定の読み込みと検証に関するコメント
    try:
        settings = load_settings()
    except ValueError as exc:
        LOGGER.error("設定の読み込みに失敗しました: %s", exc)
        raise SystemExit(1) from exc

    # 非同期処理を実行するコメント
    try:
        asyncio.run(run_bot(settings))
    except KeyboardInterrupt:
        LOGGER.info("停止シグナルを受け取りました。")
    except Exception as exc:
        LOGGER.exception("Botの実行中に例外が発生しました: %s", exc)
        raise


# エントリポイントの定義に関するコメント
if __name__ == "__main__":
    main()
