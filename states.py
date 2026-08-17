"""
State management - foydalanuvchi holatlari boshqaruvi
Har bir foydalanuvchi uchun joriy holat saqlanadi
"""
from enum import Enum
from typing import Dict, Any, Optional
import asyncio


class UserState(Enum):
    """Foydalanuvchi holatlari ro'yxati"""
    IDLE = "idle"
    WAITING_VIDEO = "waiting_video"
    WAITING_TRIM_START = "waiting_trim_start"
    WAITING_TRIM_END = "waiting_trim_end"
    WAITING_TEXT = "waiting_text"
    WAITING_TEXT_POSITION = "waiting_text_position"
    WAITING_TEXT_SIZE = "waiting_text_size"
    WAITING_TEXT_COLOR = "waiting_text_color"
    WAITING_MUSIC = "waiting_music"
    WAITING_SPEED = "waiting_speed"
    WAITING_FILTER = "waiting_filter"
    WAITING_CROP = "waiting_crop"
    WAITING_CROP_RATIO = "waiting_crop_ratio"
    WAITING_MERGE_FIRST = "waiting_merge_first"
    WAITING_MERGE_SECOND = "waiting_merge_second"
    WAITING_COMPRESS = "waiting_compress"
    WAITING_ROTATE = "waiting_rotate"
    WAITING_LINK = "waiting_link"
    WAITING_MUSIC_VOLUME = "waiting_music_volume"
    WAITING_BRIGHTNESS = "waiting_brightness"
    WAITING_CONTRAST = "waiting_contrast"
    WAITING_ADMIN_VIDEO = "waiting_admin_video"
    WAITING_BROADCAST = "waiting_broadcast"
    GENERATING = "generating"


class StateManager:
    """Foydalanuvchi holatlari boshqaruvchi sinf (in-memory)"""

    def __init__(self):
        self._states: Dict[int, UserState] = {}
        self._data: Dict[int, Dict[str, Any]] = {}
        self._tasks: Dict[int, asyncio.Task] = {}
        self._cancel_flags: Dict[int, bool] = {}

    def get_state(self, user_id: int) -> UserState:
        return self._states.get(user_id, UserState.IDLE)

    def set_state(self, user_id: int, state: UserState) -> None:
        self._states[user_id] = state

    def reset_state(self, user_id: int) -> None:
        self._states[user_id] = UserState.IDLE
        self._data[user_id] = {}
        self._cancel_flags[user_id] = False

    def get_data(self, user_id: int) -> Dict[str, Any]:
        if user_id not in self._data:
            self._data[user_id] = {}
        return self._data[user_id]

    def set_data(self, user_id: int, key: str, value: Any) -> None:
        if user_id not in self._data:
            self._data[user_id] = {}
        self._data[user_id][key] = value

    def get_data_value(self, user_id: int, key: str, default: Any = None) -> Any:
        return self._data.get(user_id, {}).get(key, default)

    def clear_data(self, user_id: int) -> None:
        self._data[user_id] = {}

    def is_generating(self, user_id: int) -> bool:
        return self._states.get(user_id) == UserState.GENERATING

    def set_task(self, user_id: int, task: asyncio.Task) -> None:
        self._tasks[user_id] = task

    def get_task(self, user_id: int) -> Optional[asyncio.Task]:
        return self._tasks.get(user_id)

    def cancel_task(self, user_id: int) -> bool:
        task = self._tasks.get(user_id)
        if task and not task.done():
            task.cancel()
            self._cancel_flags[user_id] = True
            return True
        return False

    def should_cancel(self, user_id: int) -> bool:
        return self._cancel_flags.get(user_id, False)

    def clear_task(self, user_id: int) -> None:
        if user_id in self._tasks:
            del self._tasks[user_id]
        self._cancel_flags[user_id] = False

    def get_all_active_users(self) -> list:
        return [uid for uid, state in self._states.items() if state != UserState.IDLE]

    def is_idle(self, user_id: int) -> bool:
        return self.get_state(user_id) == UserState.IDLE


# Global state manager
state_manager = StateManager()
