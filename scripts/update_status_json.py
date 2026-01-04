# -*- coding: utf-8 -*-
"""GitHub Actions向けにstatus.jsonを更新するスクリプト。"""

# 標準ライブラリの読み込みに関するコメント
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ステータスファイルのパスを定義するコメント
BASE_DIR = Path(__file__).resolve().parent.parent
STATUS_PATH = BASE_DIR / "status.json"

# 監視対象の既定値を定義するコメント
DEFAULT_TWITCH_CHANNEL = "hikakin"
DEFAULT_TARGET_USER = "HIKAKIN / hikakin"

# GitHub Actions更新時の表示文言を定義するコメント
ACTIONS_STATUS_MESSAGE = "GitHub Actionsで定期更新中"


# 現在時刻をエポック秒で返す関数に関するコメント
def now_epoch() -> int:
    """現在時刻をエポック秒で返す。"""

    # 秒単位で整数化するコメント
    return int(time.time())


# エポック秒をISO文字列に変換する関数に関するコメント
def iso_from_epoch(epoch_seconds: int) -> str:
    """エポック秒をISO 8601形式に変換する。"""

    # UTCのISO文字列を生成するコメント
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat()


# 文字列の検証を行う関数に関するコメント
def normalize_text(value: Any) -> Optional[str]:
    """文字列として有効な場合のみ返す。"""

    # 文字列として扱えるか確認するコメント
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned if cleaned else None


# エポック秒の検証を行う関数に関するコメント
def normalize_epoch(value: Any) -> Optional[int]:
    """エポック秒として有効な場合のみ返す。"""

    # 数値として解釈できるか確認するコメント
    if isinstance(value, (int, float)):
        if value > 0:
            return int(value)
    return None


# 既存のstatus.jsonを読み込む関数に関するコメント
def load_existing_status() -> dict:
    """既存のstatus.jsonがあれば読み込む。"""

    # ファイルがない場合は空の辞書を返すコメント
    if not STATUS_PATH.exists():
        return {}

    # JSONの読み込みを安全に行うコメント
    try:
        with STATUS_PATH.open("r", encoding="utf-8") as file_handle:
            data = json.load(file_handle)
    except (OSError, json.JSONDecodeError):
        return {}

    # 辞書以外は無視するコメント
    return data if isinstance(data, dict) else {}


# 新しいステータスを構築する関数に関するコメント
def build_status_payload(existing: dict, now: int) -> dict:
    """status.jsonに書き込むデータを構築する。"""

    # 既存の開始時刻を再利用するコメント
    started_at = normalize_epoch(existing.get("started_at"))
    if started_at is None:
        started_at = now

    # 既存の詳細情報を維持するコメント
    last_comment_at = normalize_epoch(existing.get("last_comment_at"))
    last_comment_user = normalize_text(existing.get("last_comment_user"))
    last_comment_text = normalize_text(existing.get("last_comment_text"))
    last_post_at = normalize_epoch(existing.get("last_post_at"))
    last_post_text = normalize_text(existing.get("last_post_text"))
    last_error_at = normalize_epoch(existing.get("last_error_at"))
    last_error_message = normalize_text(existing.get("last_error_message"))

    # 監視対象の表示値を決めるコメント
    twitch_channel = normalize_text(existing.get("twitch_channel")) or DEFAULT_TWITCH_CHANNEL
    target_user = normalize_text(existing.get("target_user")) or DEFAULT_TARGET_USER

    # ステータスを構築するコメント
    payload = {
        "data_source": "github-actions",
        "status": "running",
        "status_message": ACTIONS_STATUS_MESSAGE,
        "status_updated_at": now,
        "status_updated_at_iso": iso_from_epoch(now),
        "started_at": started_at,
        "started_at_iso": iso_from_epoch(started_at),
        "uptime_seconds": max(0, now - started_at),
        "twitch_channel": twitch_channel,
        "target_user": target_user,
        "last_comment_at": last_comment_at,
        "last_comment_at_iso": iso_from_epoch(last_comment_at) if last_comment_at else None,
        "last_comment_user": last_comment_user,
        "last_comment_text": last_comment_text,
        "last_post_at": last_post_at,
        "last_post_at_iso": iso_from_epoch(last_post_at) if last_post_at else None,
        "last_post_text": last_post_text,
        "last_error_at": last_error_at,
        "last_error_at_iso": iso_from_epoch(last_error_at) if last_error_at else None,
        "last_error_message": last_error_message,
    }

    return payload


# status.jsonを書き込む関数に関するコメント
def write_status(payload: dict) -> None:
    """status.jsonに整形済みのJSONを書き込む。"""

    # JSONを整形して保存するコメント
    with STATUS_PATH.open("w", encoding="utf-8") as file_handle:
        json.dump(payload, file_handle, ensure_ascii=False, indent=2)
        file_handle.write("\n")


# エントリポイントの処理に関するコメント
def main() -> None:
    """status.jsonを更新する。"""

    # 既存データを読み込むコメント
    existing = load_existing_status()

    # 現在時刻を取得するコメント
    now = now_epoch()

    # 新しいペイロードを作成するコメント
    payload = build_status_payload(existing, now)

    # ファイルを書き込むコメント
    write_status(payload)


# スクリプト実行時の処理に関するコメント
if __name__ == "__main__":
    main()
