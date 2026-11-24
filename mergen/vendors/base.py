"""Üretici modüllerinin uyması gereken arayüz. Yazma işlevleri (set_*) her zaman kullanıcı onayından sonra çağrılır."""


class Vendor:
    name = ""

    def detect(self) -> bool:
        raise NotImplementedError

    def capabilities(self) -> dict:
        return {}

    def read(self) -> dict:
        return {}

    def set_fan(self, *args, **kw):
        raise NotImplementedError

    def set_power_mode(self, *args, **kw):
        raise NotImplementedError

    def set_keyboard(self, *args, **kw):
        raise NotImplementedError
