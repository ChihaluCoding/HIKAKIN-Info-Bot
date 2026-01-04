# -*- coding: utf-8 -*-
"""Twitchのコメントを監視してXに投稿するメインモジュール。"""

# 標準ライブラリの読み込みに関するコメント
import asyncio
import json
import logging
import os
import re
import ssl
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Tuple

# 外部ライブラリの読み込みに関するコメント
from dotenv import load_dotenv
import httpx
import tweepy

# Xの最大文字数を定数として定義するコメント
MAX_TWEET_LENGTH = 280

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

# 投稿対象にするTwitchユーザー名を固定するコメント
TARGET_TWITCH_USER = "hikakin"

# 大文字小文字の差を吸収するために小文字化するコメント
TARGET_TWITCH_USER_LOWER = TARGET_TWITCH_USER.lower()

# 投稿時の見出しを固定するコメント
POST_HEADER = "新着コメント😎"

# 稼働状況APIのホストを固定するコメント
STATUS_SERVER_HOST = "127.0.0.1"

# 稼働状況APIのポートを固定するコメント
STATUS_SERVER_PORT = 8080

# 稼働状況の文字数上限を設定するコメント
STATUS_TEXT_LIMIT = 200

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

    # 投稿制御に関する設定値のコメント
    x_post_interval_seconds: float
    x_queue_size: int


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

    # オプション設定の読み込みに関するコメント
    x_post_interval_seconds = parse_float_env("X_POST_INTERVAL_SECONDS", 5.0)
    x_queue_size = parse_int_env("X_QUEUE_SIZE", 200)

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
        x_post_interval_seconds=x_post_interval_seconds,
        x_queue_size=x_queue_size,
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


# UNIX時刻をISO文字列に変換する関数に関するコメント
def format_iso_time(timestamp: Optional[float]) -> Optional[str]:
    """UNIX時刻をISO 8601形式に変換する。"""

    # 未設定の場合はNoneを返すコメント
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


# 稼働状況を保持するクラスに関するコメント
class BotStatus:
    """稼働状況をスレッドセーフに管理するクラス。"""

    # 初期化処理に関するコメント
    def __init__(self, twitch_channel: str, target_user: str) -> None:
        # 状態を保護するロックを用意するコメント
        self._lock = threading.Lock()

        # 初期状態を保持するコメント
        now = time.time()
        self._started_at = now
        self._status = "starting"
        self._status_message = "起動中"
        self._status_updated_at = now
        self._twitch_channel = twitch_channel
        self._target_user = target_user
        self._last_comment_at: Optional[float] = None
        self._last_comment_user: Optional[str] = None
        self._last_comment_text: Optional[str] = None
        self._last_post_at: Optional[float] = None
        self._last_post_text: Optional[str] = None
        self._last_error_at: Optional[float] = None
        self._last_error_message: Optional[str] = None

    # ステータスを更新する処理に関するコメント
    def set_status(self, status: str, message: str) -> None:
        """稼働状態とメッセージを更新する。"""

        # 状態の更新をロック内で行うコメント
        with self._lock:
            now = time.time()
            self._status = status
            self._status_message = clip_text(message, STATUS_TEXT_LIMIT)
            self._status_updated_at = now

    # コメント受信を記録する処理に関するコメント
    def record_comment(self, user: str, message: str) -> None:
        """最新コメント情報を更新する。"""

        # コメント情報をロック内で更新するコメント
        with self._lock:
            now = time.time()
            self._last_comment_at = now
            self._last_comment_user = user
            self._last_comment_text = clip_text(message, STATUS_TEXT_LIMIT)
            self._status = "running"
            self._status_message = "コメント監視中"
            self._status_updated_at = now

    # 投稿完了を記録する処理に関するコメント
    def record_post(self, message: str) -> None:
        """最新投稿情報を更新する。"""

        # 投稿情報をロック内で更新するコメント
        with self._lock:
            now = time.time()
            self._last_post_at = now
            self._last_post_text = clip_text(message, STATUS_TEXT_LIMIT)
            self._status = "running"
            self._status_message = "Xへ投稿済み"
            self._status_updated_at = now

    # エラーを記録する処理に関するコメント
    def record_error(self, message: str) -> None:
        """最新エラー情報を更新する。"""

        # エラー情報をロック内で更新するコメント
        with self._lock:
            now = time.time()
            self._last_error_at = now
            self._last_error_message = clip_text(message, STATUS_TEXT_LIMIT)
            self._status = "warning"
            self._status_message = "エラー発生"
            self._status_updated_at = now

    # 現在の状態をスナップショット化する処理に関するコメント
    def snapshot(self) -> dict:
        """フロント表示用の状態情報を返す。"""

        # 状態のコピーを作成するコメント
        with self._lock:
            now = time.time()
            return {
                "status": self._status,
                "status_message": self._status_message,
                "status_updated_at": self._status_updated_at,
                "status_updated_at_iso": format_iso_time(self._status_updated_at),
                "started_at": self._started_at,
                "started_at_iso": format_iso_time(self._started_at),
                "uptime_seconds": max(0.0, now - self._started_at),
                "twitch_channel": self._twitch_channel,
                "target_user": self._target_user,
                "last_comment_at": self._last_comment_at,
                "last_comment_at_iso": format_iso_time(self._last_comment_at),
                "last_comment_user": self._last_comment_user,
                "last_comment_text": self._last_comment_text,
                "last_post_at": self._last_post_at,
                "last_post_at_iso": format_iso_time(self._last_post_at),
                "last_post_text": self._last_post_text,
                "last_error_at": self._last_error_at,
                "last_error_at_iso": format_iso_time(self._last_error_at),
                "last_error_message": self._last_error_message,
            }


# 稼働状況APIのリクエストハンドラに関するコメント
class StatusRequestHandler(BaseHTTPRequestHandler):
    """稼働状況APIへのリクエストを処理する。"""

    # GETリクエストを処理するコメント
    def do_GET(self) -> None:
        """GETリクエストを処理してJSONを返す。"""

        # 対象パス以外は404を返すコメント
        if self.path.split("?", 1)[0] != "/status":
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("Not Found".encode("utf-8"))
            return

        # ステータス情報を取得してJSON化するコメント
        payload = self.server.status_provider.snapshot()
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        # レスポンスヘッダーを設定するコメント
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()

        # レスポンスボディを送るコメント
        self.wfile.write(body)

    # ログを抑制して統一ログにするコメント
    def log_message(self, format_string: str, *args: object) -> None:
        """標準出力ログを抑制する。"""

        # 未使用引数の警告を避けるコメント
        _ = format_string
        _ = args
        return


# ステータスAPI用のHTTPサーバークラスに関するコメント
class StatusHTTPServer(ThreadingHTTPServer):
    """ステータスAPIのHTTPサーバーを提供する。"""

    # 初期化処理に関するコメント
    def __init__(self, server_address: Tuple[str, int], status_provider: BotStatus) -> None:
        # ステータスプロバイダを保持するコメント
        self.status_provider = status_provider
        super().__init__(server_address, StatusRequestHandler)


# ステータスAPIサーバーを管理するクラスに関するコメント
class StatusServerController:
    """ステータスAPIの起動と停止を管理する。"""

    # 初期化処理に関するコメント
    def __init__(self, status_provider: BotStatus) -> None:
        # サーバーとスレッドを保持するコメント
        self._status_provider = status_provider
        self._server: Optional[StatusHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    # サーバーを起動するコメント
    def start(self) -> None:
        """ローカルHTTPサーバーを起動する。"""

        # サーバーの重複起動を避けるコメント
        if self._server is not None:
            return

        # サーバーを作成してスレッドで起動するコメント
        self._server = StatusHTTPServer((STATUS_SERVER_HOST, STATUS_SERVER_PORT), self._status_provider)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        LOGGER.info(
            "ステータスAPIを起動しました: http://%s:%s/status",
            STATUS_SERVER_HOST,
            STATUS_SERVER_PORT,
        )

    # サーバーを停止するコメント
    def stop(self) -> None:
        """ローカルHTTPサーバーを停止する。"""

        # サーバーが未起動なら何もしないコメント
        if self._server is None:
            return

        # サーバー停止処理を行うコメント
        self._server.shutdown()
        self._server.server_close()
        self._server = None

        # スレッドの終了を待機するコメント
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None


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


# ツイート本文を構築する関数に関するコメント
def build_tweet(message: str) -> str:
    """投稿用のテキストを組み立てる。"""

    # 指定フォーマットで本文を構成するコメント
    base_text = f"{POST_HEADER}\n\n「{message}」"
    return truncate_for_x(base_text, MAX_TWEET_LENGTH)


# X投稿を順番に処理するクラスに関するコメント
class XPoster:
    """Xへの投稿をキューで順次実行するクラス。"""

    # 初期化処理に関するコメント
    def __init__(
        self,
        client: tweepy.Client,
        interval_seconds: float,
        queue_size: int,
        status: BotStatus,
    ) -> None:
        # クライアントと制御用の値を保持するコメント
        self._client = client
        self._interval_seconds = interval_seconds
        self._queue: asyncio.Queue[Optional[str]] = asyncio.Queue(maxsize=queue_size)
        self._task: Optional[asyncio.Task[None]] = None
        self._last_post_time = 0.0
        self._status = status

    # ワーカー開始のためのコメント
    def start(self) -> None:
        """投稿ワーカーを起動する。"""

        # 二重起動を避けるコメント
        if self._task is None:
            self._task = asyncio.create_task(self._worker())

    # キューに投稿を追加するためのコメント
    async def enqueue(self, text: str) -> None:
        """投稿テキストをキューに追加する。"""

        # キューが満杯の場合に落とすコメント
        if not text:
            return
        try:
            self._queue.put_nowait(text)
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
    async def _post_to_x(self, text: str) -> None:
        """XのAPIで投稿を行う。"""

        # 投稿前の間隔調整に関するコメント
        await self._wait_for_interval()
        try:
            await asyncio.to_thread(self._client.create_tweet, text=text)
            self._last_post_time = time.monotonic()
            self._status.record_post(text)
            LOGGER.info("Xに投稿しました。")
        except Exception as exc:
            self._status.record_error(f"X投稿失敗: {exc}")
            LOGGER.exception("Xへの投稿に失敗しました: %s", exc)

    # キューから順に投稿するワーカーに関するコメント
    async def _worker(self) -> None:
        """キューの内容を順次Xに投稿する。"""

        # キューの受信ループに関するコメント
        while True:
            text = await self._queue.get()
            try:
                if text is None:
                    return
                await self._post_to_x(text)
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
        status: BotStatus,
    ) -> None:
        # 設定値とポスターを保持するコメント
        self._settings = settings
        self._poster = poster
        self._token_manager = token_manager
        self._nick = nick
        self._status = status
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
                self._status.record_error(f"Twitch接続エラー: {exc}")
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
            self._status.set_status("running", "Twitch IRC接続中")

            # 受信ループに関するコメント
            while not self._stop_event.is_set():
                raw_line = await reader.readline()
                if not raw_line:
                    self._status.record_error("Twitch IRCの接続が切断されました。")
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

        # コメント受信を記録するコメント
        self._status.record_comment(author, content)

        # 投稿文を組み立ててキューに追加するコメント
        tweet_text = build_tweet(content)
        await self._poster.enqueue(tweet_text)

    # PINGへの応答を行う関数に関するコメント
    async def _send_pong(self, line: str, writer: asyncio.StreamWriter) -> None:
        """Twitch IRCのPINGにPONGで応答する。"""

        # PINGの宛先を取得して返すコメント
        payload = line.split(" ", 1)[1] if " " in line else ""
        writer.write(f"PONG {payload}\r\n".encode("utf-8"))
        await writer.drain()


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

    # 稼働状況の初期化を行うコメント
    status = BotStatus(settings.twitch_channel, TARGET_TWITCH_USER)

    # Xクライアントと投稿ワーカーを準備するコメント
    x_client = create_x_client(settings)
    poster = XPoster(
        client=x_client,
        interval_seconds=settings.x_post_interval_seconds,
        queue_size=settings.x_queue_size,
        status=status,
    )

    # Twitchのトークン管理を準備するコメント
    token_manager = TwitchTokenManager(
        client_id=settings.twitch_client_id,
        client_secret=settings.twitch_client_secret,
        refresh_token=settings.twitch_refresh_token,
    )

    # ステータスAPIサーバーを準備するコメント
    status_server = StatusServerController(status)

    # Twitchのユーザー名を解決するコメント
    try:
        resolved_nick = await resolve_twitch_nick(settings, token_manager)
    except Exception as exc:
        status.record_error(f"Twitchユーザー名解決失敗: {exc}")
        raise

    # 投稿ワーカーを起動するコメント
    poster.start()

    # Twitch IRCリスナーを起動するコメント
    listener = TwitchIRCListener(settings, poster, token_manager, resolved_nick, status)
    try:
        # ステータスAPIを起動するコメント
        try:
            status_server.start()
        except OSError as exc:
            status.record_error(f"ステータスAPI起動失敗: {exc}")
            LOGGER.exception("ステータスAPIの起動に失敗しました: %s", exc)

        await listener.run()
    finally:
        # クリーンアップ処理を行うコメント
        await poster.close()
        status.set_status("stopped", "停止済み")
        status_server.stop()


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
