"""渠道注册表：按配置实例化启用的适配器，全局单例。"""

from __future__ import annotations

import threading

class Registry:

    def __init__(self) -> None:

        self._adapters: dict[str, "ChannelAdapter"] = {}

        self._lock = threading.Lock()

    def register(self, adapter) -> None:

        with self._lock:

            self._adapters[adapter.name] = adapter

    def get(self, name: str):

        return self._adapters.get(name)

    def all(self) -> list:

        return list(self._adapters.values())

    def start_all(self) -> None:

        for a in self._adapters.values():

            a.start()

    def stop_all(self) -> None:

        for a in self._adapters.values():

            try:

                a.stop()

            except Exception:  # noqa: BLE001

                pass

    def meta(self) -> list[dict]:

        return [a.meta() for a in self._adapters.values()]

registry = Registry()
